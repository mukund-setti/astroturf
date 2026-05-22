"""IngestionAgent — regulations.gov v4 -> bronze.raw_comments (local Delta via delta-rs).

See docs/architecture.md and docs/decisions/0002-deltalake-for-local-bronze.md.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx
import mlflow
import pyarrow as pa
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.delta_utils.bronze import merge_comments
from shared.schemas.comments import RawComment, raw_comment_arrow_schema

log = logging.getLogger(__name__)

API_BASE = "https://api.regulations.gov/v4"
PAGE_SIZE = 250
MAX_PAGES_PER_REQUEST = 20  # regulations.gov v4 caps at 20 pages * 250 records = 5000
DEFAULT_BRONZE_PATH = "./data/bronze/raw_comments"
LOG_EVERY = 1000


class _RetryableHTTPError(Exception):
    """Marker for 429 and 5xx — retried by tenacity."""


class CursorStalledError(RuntimeError):
    """Raised when date-window cursoring cannot advance past one ``lastModifiedDate``."""


@dataclass
class IngestionInput:
    docket_id: str
    page_size: int = PAGE_SIZE
    max_outer_iterations: int | None = None  # safety cap for tests / dry runs
    max_comments: int | None = None  # stop ingestion after at least this many comments


@dataclass
class IngestionOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type(_RetryableHTTPError),
    reraise=True,
)
def _fetch_page(
    client: httpx.Client, url: str, params: dict[str, Any]
) -> dict[str, Any]:
    """GET one page. Raises ``_RetryableHTTPError`` on 429/5xx (tenacity retries)."""
    response = client.get(url, params=params)
    status = response.status_code
    if status == 429 or 500 <= status < 600:
        raise _RetryableHTTPError(f"{status} on {url}")
    response.raise_for_status()
    return response.json()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # regulations.gov returns ISO-8601 with trailing Z
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_raw_comment(
    record: dict[str, Any], docket_id: str, now: datetime
) -> RawComment:
    attrs = record.get("attributes") or {}
    return RawComment(
        comment_id=record["id"],
        docket_id=docket_id,
        document_type=attrs.get("documentType"),
        title=attrs.get("title"),
        posted_date=_parse_dt(attrs.get("postedDate")),
        received_date=_parse_dt(attrs.get("receivedDate")),
        last_modified_date=_parse_dt(attrs.get("lastModifiedDate")),
        comment_text=attrs.get("comment"),
        submitter_name=attrs.get("submitterName"),
        first_name=attrs.get("firstName"),
        last_name=attrs.get("lastName"),
        organization=attrs.get("organization"),
        city=attrs.get("city"),
        state_province_region=attrs.get("stateProvinceRegion"),
        country=attrs.get("country"),
        agency_id=attrs.get("agencyId"),
        has_attachments=bool(attrs.get("hasAttachments") or False),
        attributes_json=json.dumps(attrs, default=str, sort_keys=True),
        ingested_at=now,
    )


def _rows_to_arrow(rows: list[RawComment]) -> pa.Table:
    schema = raw_comment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _last_lmd_string(records: list[dict[str, Any]]) -> str | None:
    """Return the raw ``lastModifiedDate`` string of the last record (records are sorted asc)."""
    for record in reversed(records):
        attrs = record.get("attributes") or {}
        lmd = attrs.get("lastModifiedDate")
        if lmd:
            return lmd
    return None


class IngestionAgent:
    """Fetch all comments for a docket from regulations.gov v4 and merge into bronze.

    Uses date-window cursoring on ``lastModifiedDate`` to walk past the API's
    5000-record-per-query cap. Idempotent: a re-run merges by ``comment_id`` and
    will not produce duplicates.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or {}
        self.bronze_path: str = self.config.get("bronze_path", DEFAULT_BRONZE_PATH)
        if http_client is None:
            api_key = os.environ.get("REGULATIONS_GOV_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "REGULATIONS_GOV_API_KEY is not set. Required to fetch comments."
                )
            http_client = httpx.Client(
                base_url=API_BASE,
                headers={"X-Api-Key": api_key},
                timeout=30.0,
            )
        self._http = http_client

    def run(self, inputs: IngestionInput) -> IngestionOutput:
        start = time.monotonic()
        comments_fetched = 0
        comments_written = 0
        api_calls = 0
        next_log_threshold = LOG_EVERY

        with mlflow.start_run(run_name=f"ingestion-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("page_size", inputs.page_size)
            mlflow.log_param("bronze_path", self.bronze_path)

            cursor: str | None = None
            outer_iter = 0

            while True:
                outer_iter += 1
                if (
                    inputs.max_outer_iterations is not None
                    and outer_iter > inputs.max_outer_iterations
                ):
                    log.warning(
                        "Reached max_outer_iterations=%s; stopping early.",
                        inputs.max_outer_iterations,
                    )
                    break

                pages_this_window = 0
                last_lmd_in_window: str | None = None

                for page_json in self._iter_pages(
                    docket_id=inputs.docket_id,
                    page_size=inputs.page_size,
                    cursor=cursor,
                ):
                    api_calls += 1
                    pages_this_window += 1

                    records = page_json.get("data") or []
                    if records:
                        rows = [
                            _to_raw_comment(
                                r, inputs.docket_id, datetime.now(timezone.utc)
                            )
                            for r in records
                        ]
                        last_lmd_in_window = (
                            _last_lmd_string(records) or last_lmd_in_window
                        )

                        metrics = merge_comments(self.bronze_path, _rows_to_arrow(rows))
                        comments_written += metrics["inserted"] + metrics["updated"]
                        comments_fetched += len(rows)

                        while comments_fetched >= next_log_threshold:
                            log.info(
                                "docket=%s fetched=%s written=%s api_calls=%s cursor=%s",
                                inputs.docket_id,
                                comments_fetched,
                                comments_written,
                                api_calls,
                                cursor,
                            )
                            next_log_threshold += LOG_EVERY

                        if (
                            inputs.max_comments is not None
                            and comments_fetched >= inputs.max_comments
                        ):
                            break

                    if pages_this_window >= MAX_PAGES_PER_REQUEST:
                        break

                if (
                    inputs.max_comments is not None
                    and comments_fetched >= inputs.max_comments
                ):
                    log.info(
                        "Reached max_comments=%s; stopping ingestion.",
                        inputs.max_comments,
                    )
                    break

                if pages_this_window < MAX_PAGES_PER_REQUEST:
                    # Window drained — docket fully ingested.
                    break

                if last_lmd_in_window is None or last_lmd_in_window == cursor:
                    raise CursorStalledError(
                        f"Cursor did not advance for docket_id={inputs.docket_id!r} "
                        f"at lastModifiedDate={last_lmd_in_window!r}; "
                        f"records seen so far: {comments_fetched}. "
                        f"More than {MAX_PAGES_PER_REQUEST * inputs.page_size} comments "
                        f"share this timestamp. "
                        f"Resolution: add documentId tiebreaking to the cursor or split the "
                        f"date range recursively."
                    )

                cursor = last_lmd_in_window

            duration = time.monotonic() - start
            mlflow.log_metric("comments_fetched", comments_fetched)
            mlflow.log_metric("comments_written", comments_written)
            mlflow.log_metric("api_calls_made", api_calls)
            mlflow.log_metric("duration_seconds", duration)

            log.info(
                "Ingestion complete docket=%s fetched=%s written=%s api_calls=%s duration=%.2fs",
                inputs.docket_id,
                comments_fetched,
                comments_written,
                api_calls,
                duration,
            )

        return IngestionOutput(
            docket_id=inputs.docket_id,
            rows_written=comments_written,
            metadata={
                "comments_fetched": comments_fetched,
                "api_calls_made": api_calls,
                "duration_seconds": duration,
            },
        )

    def _iter_pages(
        self,
        *,
        docket_id: str,
        page_size: int,
        cursor: str | None,
    ) -> Iterator[dict[str, Any]]:
        """Yield JSON pages within one cursor window. Stops at ``links.next`` absent or 20-page cap."""
        base_params: dict[str, Any] = {
            "filter[docketId]": docket_id,
            "sort": "lastModifiedDate,documentId",
            "page[size]": page_size,
        }
        if cursor is not None:
            base_params["filter[lastModifiedDate][ge]"] = cursor

        page_number = 1
        while page_number <= MAX_PAGES_PER_REQUEST:
            params = {**base_params, "page[number]": page_number}
            page = _fetch_page(self._http, "/comments", params)
            yield page
            meta = page.get("meta") or {}
            has_next = meta.get("hasNextPage", False) or bool(
                (page.get("links") or {}).get("next")
            )
            if not has_next:
                return
            page_number += 1
