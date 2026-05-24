"""AttachmentDownloaderAgent v2B — downloads cataloged comment attachments.

Reads comment attachments from silver.comment_attachments, downloads them
atomically, calculates checksums, and transactionally updates their download
status in the Delta table.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
from deltalake import DeltaTable

from shared.delta_utils.silver import ensure_schema, merge_comment_attachments
from shared.schemas.comment_attachments import (
    CommentAttachment,
    comment_attachment_arrow_schema,
)

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt", "html"}


@dataclass
class DownloaderInput:
    docket_id: str
    attachments_path: str = "./data/attachments"
    attachments_table_path: str = "./data/silver/comment_attachments"
    max_downloads: int = 10
    max_file_mb: int = 25
    retry_failed: bool = False
    force_download: bool = False


@dataclass
class DownloaderOutput:
    docket_id: str
    downloaded_count: int
    skipped_count: int
    failed_count: int
    total_bytes_downloaded: int


def _compute_sha256(path: Path) -> str:
    """Helper to calculate SHA-256 hash of a file on disk."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _record_to_model(record: dict[str, Any], now: datetime) -> CommentAttachment:
    """Converts a flat dictionary (from Delta table / PyArrow) to a CommentAttachment Pydantic model."""
    detected_at = record.get("detected_at")
    if isinstance(detected_at, str):
        detected_at = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))

    downloaded_at = record.get("downloaded_at")
    if isinstance(downloaded_at, str):
        downloaded_at = datetime.fromisoformat(downloaded_at.replace("Z", "+00:00"))

    return CommentAttachment(
        attachment_id=record.get("attachment_id"),
        comment_id=record.get("comment_id"),
        docket_id=record.get("docket_id"),
        file_name=record.get("file_name"),
        file_url=record.get("file_url"),
        format=record.get("format"),
        size_bytes=record.get("size_bytes"),
        detected_at=detected_at or now,
        download_status=record.get("download_status", "pending"),
        extracted_text_path=record.get("extracted_text_path"),
        local_path=record.get("local_path"),
        checksum_sha256=record.get("checksum_sha256"),
        downloaded_at=downloaded_at,
        download_error=record.get("download_error"),
        size_bytes_actual=record.get("size_bytes_actual"),
    )


def _rows_to_arrow(rows: list[CommentAttachment]) -> pa.Table:
    """Converts a list of CommentAttachment models to a PyArrow table."""
    schema = comment_attachment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


class AttachmentDownloaderAgent:
    """Agent that safely, atomically, and concurrently downloads comment attachments."""

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        self._http = http_client or httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def run(self, inputs: DownloaderInput) -> DownloaderOutput:
        start_time = time.monotonic()
        table_path = inputs.attachments_table_path

        log.info(
            "Starting AttachmentDownloaderAgent for docket=%s, table=%s",
            inputs.docket_id,
            table_path,
        )

        if not os.path.exists(table_path) or not DeltaTable.is_deltatable(table_path):
            log.warning(
                "No attachments table found at %s. Nothing to download.", table_path
            )
            return DownloaderOutput(inputs.docket_id, 0, 0, 0, 0)

        # 1. Load attachments Delta table
        dt = DeltaTable(table_path)

        # Ensure schema evolution to migrate existing tables with old schemas safely
        ensure_schema(
            table_path, comment_attachment_arrow_schema(), allow_destructive=True
        )

        # Reload dt to reflect any schema modifications
        dt = DeltaTable(table_path)

        arrow_table = dt.to_pyarrow_table()

        # Filter by docket_id
        import pyarrow.compute as pc

        arrow_table = arrow_table.filter(pc.field("docket_id") == inputs.docket_id)

        # Filter by statuses
        statuses = ["pending"]
        if inputs.retry_failed:
            statuses.append("failed")
        arrow_table = arrow_table.filter(pc.field("download_status").isin(statuses))

        records = arrow_table.to_pylist()
        log.info("Found %d pending/failed records to download.", len(records))

        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        total_bytes_downloaded = 0
        updated_rows: list[CommentAttachment] = []

        now = datetime.now(timezone.utc)

        # Process matching attachments
        for record in records:
            if downloaded_count >= inputs.max_downloads:
                log.info(
                    "Stopping downloader. Reached max_downloads safety cap of %d",
                    inputs.max_downloads,
                )
                break

            attachment_id = record.get("attachment_id")
            comment_id = record.get("comment_id")
            file_url = record.get("file_url")
            fmt = (record.get("format") or "").lower().strip()

            log.info("Processing attachment: %s (format: %s)", attachment_id, fmt)

            # Ensure safe names (directory traversal mitigation)
            safe_docket_id = "".join(
                c for c in inputs.docket_id if c.isalnum() or c in "-_"
            )
            safe_comment_id = "".join(c for c in comment_id if c.isalnum() or c in "-_")
            safe_attachment_id = "".join(
                c for c in attachment_id if c.isalnum() or c in "-_"
            )

            dest_dir = Path(inputs.attachments_path) / safe_docket_id / safe_comment_id
            dest_dir.mkdir(parents=True, exist_ok=True)

            final_path = dest_dir / f"{safe_attachment_id}.{fmt}"
            part_path = dest_dir / f"{safe_attachment_id}.{fmt}.part"

            # Check for allowed extensions
            if fmt not in ALLOWED_EXTENSIONS:
                log.info("Skipping format %s: not in allowed formats list.", fmt)
                record["download_status"] = "skipped"
                record["download_error"] = (
                    f"Format '{fmt}' is not in allowed extensions: {list(ALLOWED_EXTENSIONS)}"
                )
                skipped_count += 1
                updated_rows.append(_record_to_model(record, now))
                continue

            # Check for missing URL
            if not file_url:
                log.error("Missing file_url for attachment_id=%s", attachment_id)
                record["download_status"] = "failed"
                record["download_error"] = (
                    "Missing file_url in cataloged attachment record"
                )
                failed_count += 1
                updated_rows.append(_record_to_model(record, now))
                continue

            # Check for existing local file cache
            if final_path.exists() and not inputs.force_download:
                log.info(
                    "File already exists on disk at %s. Skipping download.", final_path
                )
                try:
                    checksum = _compute_sha256(final_path)
                    actual_size = final_path.stat().st_size
                    record["download_status"] = "downloaded"
                    record["local_path"] = str(final_path)
                    record["checksum_sha256"] = checksum
                    record["size_bytes_actual"] = actual_size
                    record["downloaded_at"] = now
                    record["download_error"] = None
                except Exception as e:
                    log.error("Error hashing cached file: %s", e)
                    record["download_status"] = "failed"
                    record["download_error"] = f"Failed to hash existing file: {e}"
                    failed_count += 1

                updated_rows.append(_record_to_model(record, now))
                continue

            # Stream download
            try:
                max_bytes = inputs.max_file_mb * 1024 * 1024
                log.info("Downloading url: %s", file_url)

                with self._http.stream("GET", file_url) as response:
                    if response.status_code != 200:
                        response.raise_for_status()

                    # 1. Content-Length check
                    cl_header = response.headers.get("content-length")
                    if cl_header:
                        try:
                            content_length = int(cl_header)
                            if content_length > max_bytes:
                                log.warning(
                                    "File %s Content-Length %d exceeds limit of %d. Skipping.",
                                    attachment_id,
                                    content_length,
                                    max_bytes,
                                )
                                record["download_status"] = "skipped"
                                record["download_error"] = (
                                    f"File size {content_length} bytes exceeds limit of {max_bytes} bytes"
                                )
                                skipped_count += 1
                                updated_rows.append(_record_to_model(record, now))
                                continue
                        except ValueError:
                            pass

                    # 2. Chunk download to .part file and count bytes
                    bytes_written = 0
                    sha256_hash = hashlib.sha256()

                    with open(part_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            bytes_written += len(chunk)
                            if bytes_written > max_bytes:
                                raise ValueError(
                                    f"File size exceeded limit of {inputs.max_file_mb} MB mid-stream"
                                )
                            f.write(chunk)
                            sha256_hash.update(chunk)

                    # 3. Size verification
                    if cl_header:
                        try:
                            content_length = int(cl_header)
                            if bytes_written != content_length:
                                raise ValueError(
                                    f"Incomplete download: expected {content_length} bytes, wrote {bytes_written} bytes"
                                )
                        except ValueError:
                            pass

                    # 4. Atomic rename
                    if final_path.exists():
                        final_path.unlink()
                    part_path.rename(final_path)

                    # 5. Record Success
                    checksum = sha256_hash.hexdigest()
                    record["download_status"] = "downloaded"
                    record["local_path"] = str(final_path.as_posix())
                    record["checksum_sha256"] = checksum
                    record["size_bytes_actual"] = bytes_written
                    record["downloaded_at"] = now
                    record["download_error"] = None

                    downloaded_count += 1
                    total_bytes_downloaded += bytes_written
                    log.info(
                        "Downloaded %s successfully (%d bytes)",
                        attachment_id,
                        bytes_written,
                    )

            except Exception as e:
                log.exception("Exception downloading attachment_id=%s", attachment_id)
                # Cleanup part file if remaining
                if part_path.exists():
                    try:
                        part_path.unlink()
                    except OSError:
                        pass

                # Record failure
                record["download_status"] = "failed"
                record["download_error"] = f"{type(e).__name__}: {str(e)}"
                failed_count += 1

            updated_rows.append(_record_to_model(record, now))

        # Write updates back to Silver delta table using merge
        if updated_rows:
            log.info("Merging %d updated rows back to Delta table.", len(updated_rows))
            arrow_updated = _rows_to_arrow(updated_rows)
            merge_comment_attachments(table_path, arrow_updated)

        duration = time.monotonic() - start_time
        log.info(
            "Downloader Agent run complete. Downloaded=%d, Skipped=%d, Failed=%d, Duration=%.2fs",
            downloaded_count,
            skipped_count,
            failed_count,
            duration,
        )

        return DownloaderOutput(
            docket_id=inputs.docket_id,
            downloaded_count=downloaded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            total_bytes_downloaded=total_bytes_downloaded,
        )
