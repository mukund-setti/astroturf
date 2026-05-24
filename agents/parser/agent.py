"""ParserAgent v2A — bronze.raw_comments -> silver (parsed_comments, comment_details, comment_attachments).

Deterministic-first parsing stage that fetches individual comment detail JSON,
extracts and cleans submitted HTML comments using BeautifulSoup, classifies cover
notes, catalogs attachment files, and logs comprehensive MLflow metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
import httpx
import mlflow
import pyarrow as pa
from deltalake import DeltaTable
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.delta_utils.silver import (
    merge_parsed_comments,
    merge_comment_details,
    merge_comment_attachments,
)
from shared.schemas.comment_details import CommentDetail, comment_detail_arrow_schema
from shared.schemas.comment_attachments import (
    CommentAttachment,
    comment_attachment_arrow_schema,
)
from shared.schemas.parsed_comments import ParsedComment, parsed_comment_arrow_schema

log = logging.getLogger(__name__)

API_BASE = "https://api.regulations.gov/v4"
DEFAULT_BRONZE_PATH = "./data/bronze/raw_comments"
DEFAULT_SILVER_PATH = "./data/silver/parsed_comments"
DEFAULT_DETAILS_PATH = "./data/silver/comment_details"
DEFAULT_ATTACHMENTS_PATH = "./data/silver/comment_attachments"


class _RetryableHTTPError(Exception):
    """Marker for 429 and 5xx — retried by tenacity."""


@dataclass
class ParserInput:
    docket_id: str
    bronze_path: str = DEFAULT_BRONZE_PATH
    silver_path: str = DEFAULT_SILVER_PATH
    details_path: str = DEFAULT_DETAILS_PATH
    attachments_path: str = DEFAULT_ATTACHMENTS_PATH
    max_rows: int | None = None
    max_detail_fetches: int | None = None
    force_enrich: bool = False


@dataclass
class ParserOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type(_RetryableHTTPError),
    reraise=True,
)
def _fetch_comment_detail(client: httpx.Client, comment_id: str) -> dict[str, Any]:
    """GET comment details with attachments included. Retries 429 and 5xx."""
    url = f"/comments/{comment_id}"
    response = client.get(url, params={"include": "attachments"})
    status = response.status_code
    if status == 429 or 500 <= status < 600:
        raise _RetryableHTTPError(f"{status} on {url}")
    response.raise_for_status()
    return response.json()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def clean_html(raw_html: str | None) -> str | None:
    """Strips all HTML tags using BeautifulSoup for clean, safe text extraction."""
    if not raw_html:
        return None
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text()
    except Exception:
        # Robust fallback regex if BS4 encounters unexpected issues
        return re.sub(r"<[^>]+>", "", raw_html)


def is_substantive_comment(
    cleaned_text: str | None, has_attachments: bool, min_length: int = 100
) -> bool:
    """Classifies a comment as substantive vs. a cover note based on heuristic checks.

    If the submission has attachments, extremely short text matching cover note keywords
    (like "see attached") is classified as non-substantive. If there are no attachments,
    even a short text is considered substantive as it is the user's primary response.
    """
    if not cleaned_text or cleaned_text.strip() == "":
        return False
    text = cleaned_text.strip().lower()

    if not has_attachments:
        return True

    if len(text) < min_length:
        cover_phrases = [
            "see attached",
            "see attachment",
            "attached please find",
            "please find attached",
            "attached file",
            "submission attached",
            "find attached",
            "attached is my comment",
            "see file",
            "attached pdf",
            "comments are attached",
            "attached hereto",
            "letter attached",
            "document attached",
        ]
        for phrase in cover_phrases:
            if phrase in text:
                return False
    return True


class ParserAgent:
    """ParserAgent v2A: Transform raw comments in bronze to silver, with detail JSON enrichment.

    Fetches individual comment detail JSON, parses and cleans HTML body text,
    catalogs nested attachment metadata/URLs, runs cover note diagnostics,
    performs three concurrent/sequential Delta MERGEs, and reports metrics to MLflow.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or {}
        if http_client is None:
            api_key = os.environ.get("REGULATIONS_GOV_API_KEY")
            # In test environments or when REGULATIONS_GOV_API_KEY is not defined,
            # allow passing a preconfigured http_client or log a warning.
            if not api_key:
                log.warning(
                    "REGULATIONS_GOV_API_KEY is not set. Real API requests will fail. "
                    "Ignore if mock client is used or this is a test run."
                )
            http_client = httpx.Client(
                base_url=API_BASE,
                headers={"X-Api-Key": api_key or "DUMMY_KEY"},
                timeout=30.0,
            )
        self._http = http_client

    def run(self, inputs: ParserInput) -> ParserOutput:
        start_time = time.monotonic()

        # Resolve paths
        bronze_path = self.config.get("bronze_path", inputs.bronze_path)
        silver_path = self.config.get("silver_path", inputs.silver_path)
        details_path = self.config.get("details_path", inputs.details_path)
        attachments_path = self.config.get("attachments_path", inputs.attachments_path)

        log.info(
            "Starting ParserAgent v2A for docket=%s, bronze=%s, silver=%s, details=%s, attachments=%s",
            inputs.docket_id,
            bronze_path,
            silver_path,
            details_path,
            attachments_path,
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

        # Safety Limit Cap
        if inputs.max_rows is not None:
            log.info(
                "Limiting parsing to max_rows=%s (total read: %s)",
                inputs.max_rows,
                rows_read,
            )
            records = records[: inputs.max_rows]

        # Load already enriched IDs from details table (Checkpoint Pattern)
        already_enriched_ids = set()
        if not inputs.force_enrich and DeltaTable.is_deltatable(details_path):
            try:
                dt_details = DeltaTable(details_path)
                tbl_details = dt_details.to_pyarrow_table()
                import pyarrow.compute as pc

                filtered_tbl = tbl_details.filter(
                    pc.field("enrichment_status") == "success"
                )
                already_enriched_ids = set(
                    filtered_tbl.column("comment_id").to_pylist()
                )
            except Exception as e:
                log.warning(
                    "Could not read existing comment_details for checkpointing: %s", e
                )

        log.info("Already enriched comments: %s", len(already_enriched_ids))

        # Filter out records already enriched
        records_to_enrich = [
            r for r in records if r.get("comment_id") not in already_enriched_ids
        ]
        log.info("Comments to enrich in this run: %s", len(records_to_enrich))

        parsed_rows: list[ParsedComment] = []
        detail_rows: list[CommentDetail] = []
        attachment_rows: list[CommentAttachment] = []

        already_enriched_count = len(records) - len(records_to_enrich)
        api_fetches_attempted = 0
        api_fetches_success = 0
        api_fetches_failed = 0
        comments_enriched_substantive = 0
        comments_enriched_cover_note = 0

        now = datetime.now(timezone.utc)
        delay_seconds = self.config.get("delay_seconds", 0.0)

        for record in records_to_enrich:
            if (
                inputs.max_detail_fetches is not None
                and api_fetches_attempted >= inputs.max_detail_fetches
            ):
                log.info(
                    "Stopping detail enrichment. Reached max_detail_fetches safety cap of %s",
                    inputs.max_detail_fetches,
                )
                break

            comment_id = record.get("comment_id")
            if not comment_id:
                log.warning("Skipping bronze row with missing comment_id: %s", record)
                continue

            if delay_seconds > 0:
                time.sleep(delay_seconds)

            log.info("Enriching comment_id=%s", comment_id)
            api_fetches_attempted += 1

            try:
                # Fetch details from API
                detail_json = _fetch_comment_detail(self._http, comment_id)
                api_fetches_success += 1

                data_obj = detail_json.get("data") or {}
                attrs = data_obj.get("attributes") or {}
                comment_html = attrs.get("comment")

                # Clean HTML
                cleaned_comment_text = clean_html(comment_html)

                # Attachment discovery from API included payload
                included = detail_json.get("included") or []
                attachments = [
                    item for item in included if item.get("type") == "attachments"
                ]
                has_attachments = bool(
                    attachments
                    or attrs.get("hasAttachments")
                    or record.get("has_attachments")
                    or False
                )
                attachment_count = 0

                # Catalog attachments
                for attachment in attachments:
                    attachment_id_raw = attachment.get("id")
                    if not attachment_id_raw:
                        continue
                    a_attrs = attachment.get("attributes") or {}
                    file_name = a_attrs.get("title") or a_attrs.get("file_name")
                    file_formats = a_attrs.get("fileFormats") or []
                    for fmt_def in file_formats:
                        file_url = fmt_def.get("fileUrl")
                        fmt = fmt_def.get("format")
                        size = fmt_def.get("size")
                        if not file_url or not fmt:
                            continue

                        attachment_id = f"{attachment_id_raw}_{fmt}"
                        attachment_rows.append(
                            CommentAttachment(
                                attachment_id=attachment_id,
                                comment_id=comment_id,
                                docket_id=inputs.docket_id,
                                file_name=file_name,
                                file_url=file_url,
                                format=fmt,
                                size_bytes=size,
                                detected_at=now,
                                download_status="pending",
                                extracted_text_path=None,
                            )
                        )
                        attachment_count += 1

                # Substantive classification check
                substantive_min_length = self.config.get("substantive_min_length", 100)
                is_sub = is_substantive_comment(
                    cleaned_comment_text, has_attachments, substantive_min_length
                )

                if (
                    cleaned_comment_text is not None
                    and cleaned_comment_text.strip() != ""
                ):
                    raw_text = cleaned_comment_text
                    if is_sub:
                        text_source = "detail_comment_text"
                        parse_status = "parsed"
                        comments_enriched_substantive += 1
                        is_cover = False
                    else:
                        text_source = "detail_cover_note"
                        parse_status = "parsed"
                        comments_enriched_cover_note += 1
                        is_cover = True
                else:
                    # Fallback to title
                    title = record.get("title") or attrs.get("title")
                    if title is not None and title.strip() != "":
                        raw_text = title
                        text_source = "title_only"
                        parse_status = "title_only"
                    else:
                        raw_text = None
                        text_source = "missing"
                        parse_status = "missing_text"
                    is_cover = False

                # Normalize text and compute metadata
                if raw_text is not None:
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

                # Form ParsedComment
                parsed_row = ParsedComment(
                    comment_id=comment_id,
                    docket_id=inputs.docket_id,
                    title=record.get("title") or attrs.get("title"),
                    posted_date=_parse_dt(attrs.get("postedDate"))
                    or record.get("posted_date"),
                    last_modified_date=_parse_dt(attrs.get("lastModifiedDate"))
                    or record.get("last_modified_date"),
                    received_date=_parse_dt(attrs.get("receivedDate"))
                    or record.get("received_date"),
                    source_system_version="regulations.gov_v4",
                    parser_version="v2A",
                    text_source=text_source,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                    token_estimate=token_estimate,
                    char_count=char_count,
                    has_attachments=has_attachments,
                    attachment_count=attachment_count,
                    parse_status=parse_status,
                    parse_error=None,
                    parsed_at=now,
                )

                # Form CommentDetail
                detail_row = CommentDetail(
                    comment_id=comment_id,
                    docket_id=inputs.docket_id,
                    enrichment_status="success",
                    enrichment_error=None,
                    raw_detail_json=json.dumps(
                        detail_json, default=str, sort_keys=True
                    ),
                    extracted_at=now,
                    api_version="regulations.gov_v4",
                    has_substantive_comment=is_sub,
                    is_cover_note=is_cover,
                )

            except Exception as e:
                log.exception("Error enriching comment_id=%s", comment_id)
                api_fetches_failed += 1

                # Form ParsedComment fallback using bronze metadata
                title = record.get("title")
                comment_text = record.get("comment_text")

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

                if raw_text is not None:
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
                    parser_version="v2A",
                    text_source=text_source,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                    token_estimate=token_estimate,
                    char_count=char_count,
                    has_attachments=bool(record.get("has_attachments") or False),
                    attachment_count=0,
                    parse_status="error",
                    parse_error=f"{type(e).__name__}: {str(e)}",
                    parsed_at=now,
                )

                # Form CommentDetail failure record
                detail_row = CommentDetail(
                    comment_id=comment_id,
                    docket_id=inputs.docket_id,
                    enrichment_status="failed",
                    enrichment_error=f"{type(e).__name__}: {str(e)}",
                    raw_detail_json=None,
                    extracted_at=now,
                    api_version="regulations.gov_v4",
                    has_substantive_comment=False,
                    is_cover_note=False,
                )

            parsed_rows.append(parsed_row)
            detail_rows.append(detail_row)

        # Write to three silver tables (idempotent merge)
        rows_written = 0
        details_written = 0
        attachments_written = 0

        if parsed_rows:
            arrow_parsed = _parsed_rows_to_arrow(parsed_rows)
            write_metrics = merge_parsed_comments(silver_path, arrow_parsed)
            rows_written = write_metrics["inserted"] + write_metrics["updated"]

        if detail_rows:
            arrow_details = _detail_rows_to_arrow(detail_rows)
            write_details_metrics = merge_comment_details(details_path, arrow_details)
            details_written = (
                write_details_metrics["inserted"] + write_details_metrics["updated"]
            )

        if attachment_rows:
            arrow_attachments = _attachment_rows_to_arrow(attachment_rows)
            write_attachments_metrics = merge_comment_attachments(
                attachments_path, arrow_attachments
            )
            attachments_written = (
                write_attachments_metrics["inserted"]
                + write_attachments_metrics["updated"]
            )

        # Calculate metrics
        duration = time.monotonic() - start_time
        parsed_count = sum(1 for r in parsed_rows if r.parse_status == "parsed")
        title_only_count = sum(1 for r in parsed_rows if r.parse_status == "title_only")
        missing_text_count = sum(
            1 for r in parsed_rows if r.parse_status == "missing_text"
        )
        error_count = sum(1 for r in parsed_rows if r.parse_status == "error")

        # Emit MLflow metrics and params
        with mlflow.start_run(run_name=f"parser-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("bronze_path", bronze_path)
            mlflow.log_param("silver_path", silver_path)
            mlflow.log_param("details_path", details_path)
            mlflow.log_param("attachments_path", attachments_path)
            mlflow.log_param("max_rows", inputs.max_rows)
            mlflow.log_param("max_detail_fetches", inputs.max_detail_fetches)
            mlflow.log_param("force_enrich", inputs.force_enrich)
            mlflow.log_param("parser_version", "v2A")

            mlflow.log_metric("rows_read", rows_read)
            mlflow.log_metric("already_enriched_count", already_enriched_count)
            mlflow.log_metric("api_fetches_attempted", api_fetches_attempted)
            mlflow.log_metric("api_fetches_success", api_fetches_success)
            mlflow.log_metric("api_fetches_failed", api_fetches_failed)
            mlflow.log_metric("detail_fetches_attempted", api_fetches_attempted)
            mlflow.log_metric("detail_fetches_succeeded", api_fetches_success)
            mlflow.log_metric("detail_fetches_failed", api_fetches_failed)
            mlflow.log_metric(
                "comments_enriched_substantive", comments_enriched_substantive
            )
            mlflow.log_metric(
                "comments_enriched_cover_note", comments_enriched_cover_note
            )
            mlflow.log_metric("attachments_detected", len(attachment_rows))
            mlflow.log_metric("rows_written", rows_written)
            mlflow.log_metric("details_written", details_written)
            mlflow.log_metric("attachments_written", attachments_written)
            mlflow.log_metric("parsed_count", parsed_count)
            mlflow.log_metric("title_only_count", title_only_count)
            mlflow.log_metric("missing_text_count", missing_text_count)
            mlflow.log_metric("error_count", error_count)
            mlflow.log_metric("duration_seconds", duration)

        log.info(
            "ParserAgent run complete. Read=%s, Skipped=%s, Fetched=%s, Written=%s, Details=%s, Attachments=%s, Duration=%.2fs",
            rows_read,
            already_enriched_count,
            api_fetches_success,
            rows_written,
            details_written,
            attachments_written,
            duration,
        )

        return ParserOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata={
                "rows_read": rows_read,
                "already_enriched_count": already_enriched_count,
                "api_fetches_attempted": api_fetches_attempted,
                "api_fetches_success": api_fetches_success,
                "api_fetches_failed": api_fetches_failed,
                "detail_fetches_attempted": api_fetches_attempted,
                "detail_fetches_succeeded": api_fetches_success,
                "detail_fetches_failed": api_fetches_failed,
                "comments_enriched_substantive": comments_enriched_substantive,
                "comments_enriched_cover_note": comments_enriched_cover_note,
                "attachments_detected": len(attachment_rows),
                "rows_written": rows_written,
                "details_written": details_written,
                "attachments_written": attachments_written,
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
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _detail_rows_to_arrow(rows: list[CommentDetail]) -> pa.Table:
    schema = comment_detail_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _attachment_rows_to_arrow(rows: list[CommentAttachment]) -> pa.Table:
    schema = comment_attachment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)
