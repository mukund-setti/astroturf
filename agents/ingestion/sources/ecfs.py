"""ECFS public API source for IngestionAgent.

Fetches filings from the FCC Electronic Comment Filing System public API at
``publicapi.fcc.gov/ecfs`` and merges them into ``bronze.raw_comments`` using
the unified schema defined in ``shared/schemas/comments.py``. See ADR-0012 for
the schema unification and ``docs/operations/ecfs-setup.md`` for the observed API quirks.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterator

import httpx
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

ECFS_API_BASE = "https://publicapi.fcc.gov/ecfs"
DEFAULT_PAGE_SIZE = 100
DEFAULT_RATE_LIMIT_QPS = 1.0
MAX_SAFE_OFFSET = 9999
LOG_EVERY = 500

# Fields we drop before stringifying the raw filing into attributes_json.
# These are Elasticsearch-internal metadata that leak through the public API
# and are not stable contract.
_ATTRIBUTES_JSON_STRIP = ("_index", "@timestamp", "@version")


class ECFSRetryableError(Exception):
    """Marker for 429 / 5xx — retried by tenacity."""


class ECFSOffsetCeilingError(RuntimeError):
    """Raised when the API silently refuses pagination past offset 9999.

    The ECFS API returns HTTP 200 with the body
    ``"Parameters incorrectly formatted. For more information..."`` once the
    Elasticsearch ``index.max_result_window=10000`` ceiling is hit. We detect
    that body and raise rather than treating it as a real empty page.
    """


@dataclass
class ECFSClientConfig:
    """Configuration for ``ECFSClient``."""

    api_key: str
    base_url: str = ECFS_API_BASE
    page_size: int = DEFAULT_PAGE_SIZE
    rate_limit_qps: float = DEFAULT_RATE_LIMIT_QPS
    timeout_seconds: float = 30.0


class ECFSClient:
    """Thin client for the FCC ECFS public API.

    Pagination is offset+limit. Date filtering uses Lucene ``q=`` because the
    intuitive ``received_from`` / ``date_received_from`` query parameters are
    silently ignored (returned 200 + unfiltered results in observed testing).
    """

    def __init__(
        self,
        config: ECFSClientConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._http = http_client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        self._last_request_monotonic: float | None = None

    def fetch_filings(
        self,
        *,
        docket: str,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield raw filing dicts for one docket / date window.

        Pages with offset+limit until either the API returns fewer than
        ``page_size`` rows, ``max_pages`` is reached, or the offset would
        exceed ``MAX_SAFE_OFFSET``. Raises ``ECFSOffsetCeilingError`` if the
        next page would need offset > 9999 — the caller is expected to switch
        to date-window cursoring (Phase 2 work).
        """
        offset = 0
        pages = 0
        page_size = self.config.page_size

        while True:
            if max_pages is not None and pages >= max_pages:
                log.info("ECFS fetch reached max_pages=%s; stopping", max_pages)
                return
            if offset + page_size > MAX_SAFE_OFFSET + 1:
                raise ECFSOffsetCeilingError(
                    f"Cannot request offset>={offset} on ECFS /filings (Elasticsearch "
                    f"max_result_window=10000). Switch to date-window cursoring "
                    f"(Phase 2). docket={docket!r} pages_fetched={pages}"
                )

            params = self._build_params(
                docket=docket,
                start_date=start_date,
                end_date=end_date,
                offset=offset,
                page_size=page_size,
            )
            self._respect_rate_limit()
            page = self._fetch_page(params)
            filings = page.get("filing") or []
            pages += 1

            if not filings:
                return

            for filing in filings:
                yield filing

            if len(filings) < page_size:
                return
            offset += page_size

    def _build_params(
        self,
        *,
        docket: str,
        start_date: date | None,
        end_date: date | None,
        offset: int,
        page_size: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "api_key": self.config.api_key,
            "proceedings.name": docket,
            "limit": page_size,
            "offset": offset,
            "sort": "date_received,ASC",
        }
        q_parts: list[str] = []
        if start_date is not None or end_date is not None:
            start_iso = f"{start_date.isoformat()}T00:00:00Z" if start_date else "*"
            end_iso = f"{end_date.isoformat()}T23:59:59Z" if end_date else "*"
            q_parts.append(f"date_received:[{start_iso} TO {end_iso}]")
        if q_parts:
            params["q"] = " AND ".join(q_parts)
        return params

    def _respect_rate_limit(self) -> None:
        if self.config.rate_limit_qps <= 0:
            return
        min_interval = 1.0 / self.config.rate_limit_qps
        if self._last_request_monotonic is not None:
            elapsed = time.monotonic() - self._last_request_monotonic
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_monotonic = time.monotonic()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(ECFSRetryableError),
        reraise=True,
    )
    def _fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self._http.get("/filings", params=params)
        status = response.status_code
        if status == 429 or 500 <= status < 600:
            raise ECFSRetryableError(f"{status} on /filings")
        # Offset ceiling manifests as 200 with a plain-text error body.
        if status == 200 and response.headers.get("content-type", "").startswith(
            "text/"
        ):
            raise ECFSOffsetCeilingError(
                f"ECFS returned status 200 with non-JSON body: {response.text[:200]!r}"
            )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, str):
            raise ECFSOffsetCeilingError(
                f"ECFS returned status 200 with string body (likely the "
                f"offset>9999 silent failure): {body[:200]!r}"
            )
        return body


def filing_to_raw_comment(
    filing: dict[str, Any],
    *,
    docket_id: str,
    now: datetime,
) -> RawComment:
    """Map one ECFS filing dict to a unified-schema ``RawComment``.

    Field mapping per ADR-0012. ``docket_id`` is pinned to the queried docket
    (not ``filing.proceedings[0].name``) so re-runs are stable when a filing
    is cross-listed to multiple proceedings.
    """
    proceedings = filing.get("proceedings") or []
    matched_proceeding = next(
        (p for p in proceedings if p.get("name") == docket_id),
        proceedings[0] if proceedings else None,
    )

    filers = filing.get("filers") or []
    filer_names = [
        f.get("name") for f in filers if isinstance(f, dict) and f.get("name")
    ]
    submitter_name = "; ".join(filer_names) if filer_names else None

    lawfirms = filing.get("lawfirms") or []
    organization = None
    if lawfirms and isinstance(lawfirms[0], dict):
        organization = lawfirms[0].get("name") or None

    documents = filing.get("documents") or []
    attachments = filing.get("attachments") or []
    has_attachments = bool(documents) or bool(attachments)

    submissiontype = filing.get("submissiontype") or {}
    document_type = submissiontype.get("description")
    submission_type_id_raw = submissiontype.get("id")
    submission_type_id: int | None
    try:
        submission_type_id = (
            int(submission_type_id_raw) if submission_type_id_raw is not None else None
        )
    except (TypeError, ValueError):
        submission_type_id = None

    proceeding_id_raw = (
        matched_proceeding.get("id_proceeding") if matched_proceeding else None
    )
    proceeding_id = str(proceeding_id_raw) if proceeding_id_raw is not None else None

    express_comment_raw = filing.get("express_comment")
    if express_comment_raw is None:
        express_comment: bool | None = None
    else:
        express_comment = bool(express_comment_raw)

    last_modified = _parse_ecfs_dt(filing.get("date_last_modified")) or _parse_ecfs_dt(
        filing.get("date_submission")
    )

    attributes = {k: v for k, v in filing.items() if k not in _ATTRIBUTES_JSON_STRIP}

    return RawComment(
        comment_id=str(filing["id_submission"]),
        docket_id=docket_id,
        source="ecfs",
        document_type=document_type,
        title=None,
        posted_date=_parse_ecfs_dt(filing.get("date_disseminated")),
        received_date=_parse_ecfs_dt(filing.get("date_received")),
        last_modified_date=last_modified,
        comment_text=filing.get("text_data"),
        submitter_name=submitter_name,
        first_name=None,
        last_name=None,
        organization=organization,
        city=None,
        state_province_region=None,
        country=None,
        agency_id="FCC",
        has_attachments=has_attachments,
        attributes_json=json.dumps(attributes, default=str, sort_keys=True),
        ingested_at=now,
        ecfs_proceeding_id=proceeding_id,
        ecfs_submission_type_id=submission_type_id,
        ecfs_express_comment=express_comment,
    )


def _parse_ecfs_dt(value: Any) -> datetime | None:
    """Parse one of the three ECFS date encodings into a UTC-aware datetime.

    Observed formats:
    - ``2017-08-28T13:00:06.000Z`` (UTC with milliseconds, the common case)
    - ``2017-05-12T04:00:00.000-04:00`` (Eastern offset, in older proceedings)
    - ``2017-04-27T13:20:07`` (seconds-only, no TZ — assume UTC)
    """
    if not value or not isinstance(value, str):
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        log.warning("Could not parse ECFS date string: %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _rows_to_arrow(rows: list[RawComment]) -> pa.Table:
    schema = raw_comment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def run_ecfs_ingestion(
    *,
    docket_id: str,
    bronze_path: str,
    client: ECFSClient,
    start_date: date | None = None,
    end_date: date | None = None,
    max_comments: int | None = None,
    max_pages: int | None = None,
    batch_size: int = 250,
) -> dict[str, Any]:
    """Walk the ECFS /filings endpoint and merge into ``bronze.raw_comments``.

    Returns a metrics dict with ``comments_fetched``, ``comments_written``,
    ``api_calls_made`` (approximated as page count), and ``duration_seconds``.
    """
    start = time.monotonic()
    fetched = 0
    written = 0
    pages_walked = 0
    next_log_threshold = LOG_EVERY

    log.info(
        "Starting ECFS ingestion docket=%s start=%s end=%s max_comments=%s",
        docket_id,
        start_date,
        end_date,
        max_comments,
    )

    buffer: list[RawComment] = []
    now = datetime.now(timezone.utc)
    last_page_size = 0

    for filing in client.fetch_filings(
        docket=docket_id,
        start_date=start_date,
        end_date=end_date,
        max_pages=max_pages,
    ):
        try:
            row = filing_to_raw_comment(filing, docket_id=docket_id, now=now)
        except Exception:
            log.exception(
                "Failed to map ECFS filing id_submission=%s; skipping",
                filing.get("id_submission"),
            )
            continue
        buffer.append(row)
        fetched += 1
        last_page_size += 1

        if len(buffer) >= batch_size:
            metrics = merge_comments(bronze_path, _rows_to_arrow(buffer))
            written += metrics["inserted"] + metrics["updated"]
            buffer.clear()
            pages_walked += 1
            last_page_size = 0

        while fetched >= next_log_threshold:
            log.info(
                "ECFS docket=%s fetched=%s written=%s",
                docket_id,
                fetched,
                written,
            )
            next_log_threshold += LOG_EVERY

        if max_comments is not None and fetched >= max_comments:
            log.info("Reached max_comments=%s; stopping ECFS ingestion", max_comments)
            break

    if buffer:
        metrics = merge_comments(bronze_path, _rows_to_arrow(buffer))
        written += metrics["inserted"] + metrics["updated"]

    duration = time.monotonic() - start
    log.info(
        "ECFS ingestion complete docket=%s fetched=%s written=%s duration=%.2fs",
        docket_id,
        fetched,
        written,
        duration,
    )
    return {
        "comments_fetched": fetched,
        "comments_written": written,
        "api_calls_made": pages_walked + (1 if last_page_size else 0),
        "duration_seconds": duration,
    }
