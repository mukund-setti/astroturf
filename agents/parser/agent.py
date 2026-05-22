"""ParserAgent — bronze.raw_comments -> silver.parsed_comments (local Delta via delta-rs).

See docs/architecture.md and docs/decisions/0002-deltalake-for-local-bronze.md.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mlflow
import pyarrow as pa
from deltalake import DeltaTable

from shared.delta_utils.silver import merge_parsed_comments
from shared.schemas.parsed_comments import ParsedComment, parsed_comment_arrow_schema

log = logging.getLogger(__name__)

DEFAULT_BRONZE_PATH = "./data/bronze/raw_comments"
DEFAULT_SILVER_PATH = "./data/silver/parsed_comments"


@dataclass
class ParserInput:
    docket_id: str
    bronze_path: str = DEFAULT_BRONZE_PATH
    silver_path: str = DEFAULT_SILVER_PATH
    max_rows: int | None = None


@dataclass
class ParserOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class ParserAgent:
    """ParserAgent v1: Transform raw comments in bronze Delta to silver.parsed_comments.

    Deterministic-first parsing stage that cleans text, generates whitespace-collapsed
    normalized text, handles title fallback, computes SHA-256 hashes, and tracks metrics.
    Fully idempotent using Delta merge.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def run(self, inputs: ParserInput) -> ParserOutput:
        start_time = time.monotonic()

        # Resolve paths
        bronze_path = self.config.get("bronze_path", inputs.bronze_path)
        silver_path = self.config.get("silver_path", inputs.silver_path)

        log.info(
            "Starting ParserAgent for docket=%s, bronze=%s, silver=%s",
            inputs.docket_id,
            bronze_path,
            silver_path,
        )

        # Ensure bronze Delta table exists
        if not DeltaTable.is_deltatable(bronze_path):
            raise FileNotFoundError(
                f"Bronze Delta table not found at {bronze_path}. Please run ingestion first."
            )

        # Load raw comments from bronze and filter by docket
        dt = DeltaTable(bronze_path)
        arrow_table = dt.to_pyarrow_table()

        if "docket_id" in arrow_table.column_names:
            import pyarrow.compute as pc

            arrow_table = arrow_table.filter(pc.field("docket_id") == inputs.docket_id)
        else:
            log.warning("docket_id column not found in bronze Delta table schema.")
            arrow_table = arrow_table.slice(0, 0)  # Empty table

        records = arrow_table.to_pylist()
        rows_read = len(records)

        # Apply max_rows safety cap/limit if specified
        if inputs.max_rows is not None:
            log.info(
                "Limiting parsing to max_rows=%s (total read: %s)",
                inputs.max_rows,
                rows_read,
            )
            records = records[: inputs.max_rows]

        parsed_rows: list[ParsedComment] = []

        for record in records:
            comment_id = record.get("comment_id")
            if not comment_id:
                log.warning("Skipping bronze row with missing comment_id: %s", record)
                continue

            try:
                comment_text = record.get("comment_text")
                title = record.get("title")

                # Parse rules v1
                if comment_text is not None and comment_text.strip() != "":
                    raw_text = comment_text
                    text_source = "comment_text"
                    parse_status = "parsed"
                elif title is not None and title.strip() != "":
                    raw_text = title
                    text_source = "title_only"
                    parse_status = "title_only"
                else:
                    raw_text = None
                    text_source = "missing"
                    parse_status = "missing_text"

                # Normalize text and compute metadata
                if raw_text is not None:
                    # Collapsing all contiguous whitespace and lowcasing
                    normalized_text = re.sub(r"\s+", " ", raw_text.strip().lower())
                    normalized_text_hash = hashlib.sha256(
                        normalized_text.encode("utf-8")
                    ).hexdigest()
                    char_count = len(raw_text)
                    token_estimate = max(1, char_count // 4)
                else:
                    normalized_text = None
                    normalized_text_hash = None
                    char_count = 0
                    token_estimate = 0

                parsed_row = ParsedComment(
                    comment_id=comment_id,
                    docket_id=inputs.docket_id,
                    title=title,
                    posted_date=record.get("posted_date"),
                    last_modified_date=record.get("last_modified_date"),
                    received_date=record.get("received_date"),
                    source_system_version="regulations.gov_v4",
                    parser_version="v1",
                    text_source=text_source,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                    token_estimate=token_estimate,
                    char_count=char_count,
                    has_attachments=bool(record.get("has_attachments") or False),
                    parse_status=parse_status,
                    parse_error=None,
                    parsed_at=datetime.now(timezone.utc),
                )

            except Exception as e:
                log.exception("Error parsing row comment_id=%s", comment_id)
                parsed_row = ParsedComment(
                    comment_id=comment_id,
                    docket_id=inputs.docket_id,
                    title=record.get("title"),
                    posted_date=record.get("posted_date"),
                    last_modified_date=record.get("last_modified_date"),
                    received_date=record.get("received_date"),
                    source_system_version="regulations.gov_v4",
                    parser_version="v1",
                    text_source="missing",
                    raw_text=None,
                    normalized_text=None,
                    normalized_text_hash=None,
                    token_estimate=0,
                    char_count=0,
                    has_attachments=bool(record.get("has_attachments") or False),
                    parse_status="error",
                    parse_error=f"{type(e).__name__}: {str(e)}",
                    parsed_at=datetime.now(timezone.utc),
                )

            parsed_rows.append(parsed_row)

        # Write to silver table (idempotent merge)
        rows_written = 0
        if parsed_rows:
            arrow_parsed = _parsed_rows_to_arrow(parsed_rows)
            write_metrics = merge_parsed_comments(silver_path, arrow_parsed)
            rows_written = write_metrics["inserted"] + write_metrics["updated"]

        # Calculate metrics
        duration = time.monotonic() - start_time
        parsed_count = sum(1 for r in parsed_rows if r.parse_status == "parsed")
        title_only_count = sum(1 for r in parsed_rows if r.parse_status == "title_only")
        missing_text_count = sum(
            1 for r in parsed_rows if r.parse_status == "missing_text"
        )
        error_count = sum(1 for r in parsed_rows if r.parse_status == "error")

        # Emit MLflow metrics
        with mlflow.start_run(run_name=f"parser-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("bronze_path", bronze_path)
            mlflow.log_param("silver_path", silver_path)
            mlflow.log_param("max_rows", inputs.max_rows)

            mlflow.log_metric("rows_read", rows_read)
            mlflow.log_metric("rows_written", rows_written)
            mlflow.log_metric("parsed_count", parsed_count)
            mlflow.log_metric("title_only_count", title_only_count)
            mlflow.log_metric("missing_text_count", missing_text_count)
            mlflow.log_metric("error_count", error_count)
            mlflow.log_metric("duration_seconds", duration)

        log.info(
            "ParserAgent run complete for docket=%s. Read=%s, Written=%s, Parsed=%s, TitleOnly=%s, MissingText=%s, Error=%s, Duration=%.2fs",
            inputs.docket_id,
            rows_read,
            rows_written,
            parsed_count,
            title_only_count,
            missing_text_count,
            error_count,
            duration,
        )

        return ParserOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata={
                "rows_read": rows_read,
                "parsed_count": parsed_count,
                "title_only_count": title_only_count,
                "missing_text_count": missing_text_count,
                "error_count": error_count,
                "duration_seconds": duration,
            },
        )


def _parsed_rows_to_arrow(rows: list[ParsedComment]) -> pa.Table:
    schema = parsed_comment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)
