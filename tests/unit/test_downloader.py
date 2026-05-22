"""Unit tests for AttachmentDownloaderAgent — real delta-rs writes and streaming mocks."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pytest
from deltalake import DeltaTable
import httpx

from agents.downloader.agent import (
    AttachmentDownloaderAgent,
    DownloaderInput,
    _compute_sha256,
)
from shared.delta_utils.silver import merge_comment_attachments
from shared.schemas.comment_attachments import (
    CommentAttachment,
    comment_attachment_arrow_schema,
    comment_attachment_struct,
)


def _to_attachments_arrow(rows: list[CommentAttachment]) -> pa.Table:
    schema = comment_attachment_arrow_schema()
    columns = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def test_attachments_schema_sync() -> None:
    """Sync check: arrow and Spark schemas stay aligned with the Pydantic source of truth."""
    pydantic_fields = list(CommentAttachment.model_fields.keys())
    arrow_fields = comment_attachment_arrow_schema().names
    spark_fields = [f.name for f in comment_attachment_struct().fields]

    assert arrow_fields == pydantic_fields, (
        "arrow schema drifted from CommentAttachment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comment_attachments.py"
    )
    assert spark_fields == pydantic_fields, (
        "PySpark StructType drifted from CommentAttachment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comment_attachments.py"
    )


def test_compute_sha256(tmp_path: Path) -> None:
    """Verifies that the checksum computation produces stable, correct SHA-256 hashes."""
    test_file = tmp_path / "test.txt"
    test_content = b"Hello, Antigravity!"
    test_file.write_bytes(test_content)

    expected = hashlib.sha256(test_content).hexdigest()
    actual = _compute_sha256(test_file)
    assert actual == expected


def test_download_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests successful atomic download, checksum calculation, and database merge."""
    # 1. Create temporary paths
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    # 2. Add pending mock row
    now = datetime.now(timezone.utc)
    mock_row = CommentAttachment(
        attachment_id="attach_1_pdf",
        comment_id="comment_1",
        docket_id="DOCKET-1",
        file_name="test.pdf",
        file_url="https://example.com/test.pdf",
        format="pdf",
        size_bytes=100,
        detected_at=now,
        download_status="pending",
    )
    merge_comment_attachments(table_path, _to_attachments_arrow([mock_row]))

    # 3. Mock the httpx response stream
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "19"}
    mock_response.iter_bytes.return_value = [b"Hello, ", b"Antigravity!"]

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.return_value.__enter__.return_value = mock_response

    # 4. Run the downloader agent
    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
        max_downloads=5,
        max_file_mb=10,
    )
    output = agent.run(inputs)

    # 5. Assertions
    assert output.downloaded_count == 1
    assert output.skipped_count == 0
    assert output.failed_count == 0
    assert output.total_bytes_downloaded == 19

    # Verify target file exists and has correct content
    expected_file_path = attachments_path / "DOCKET-1" / "comment_1" / "attach_1_pdf.pdf"
    assert expected_file_path.exists()
    assert expected_file_path.read_bytes() == b"Hello, Antigravity!"

    # Verify temporary file was deleted/renamed
    assert not (attachments_path / "DOCKET-1" / "comment_1" / "attach_1_pdf.pdf.part").exists()

    # Read back DeltaTable rows
    dt = DeltaTable(str(table_path))
    records = dt.to_pyarrow_table().to_pylist()
    assert len(records) == 1
    r = records[0]
    assert r["download_status"] == "downloaded"
    assert r["local_path"] == str(expected_file_path.as_posix())
    assert r["size_bytes_actual"] == 19
    assert r["checksum_sha256"] == hashlib.sha256(b"Hello, Antigravity!").hexdigest()
    assert r["download_error"] is None
    assert r["downloaded_at"] is not None


def test_max_downloads_safety_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that max_downloads cap stops execution and leaves remaining rows pending."""
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    now = datetime.now(timezone.utc)
    mock_rows = [
        CommentAttachment(
            attachment_id=f"attach_{i}_pdf",
            comment_id=f"comment_{i}",
            docket_id="DOCKET-1",
            file_name=f"test_{i}.pdf",
            file_url=f"https://example.com/test_{i}.pdf",
            format="pdf",
            size_bytes=10,
            detected_at=now,
            download_status="pending",
        )
        for i in range(3)
    ]
    merge_comment_attachments(table_path, _to_attachments_arrow(mock_rows))

    # Mock client returning successful stream
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "5"}
    mock_response.iter_bytes.return_value = [b"chunk"]

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.return_value.__enter__.return_value = mock_response

    # Run with max_downloads=2
    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
        max_downloads=2,
    )
    output = agent.run(inputs)

    assert output.downloaded_count == 2
    assert output.skipped_count == 0
    assert output.failed_count == 0

    # Read back Delta table rows
    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()

    # Exact count assertions because Delta table read order is arbitrary
    statuses = [r["download_status"] for r in records]
    assert statuses.count("downloaded") == 2
    assert statuses.count("pending") == 1


def test_max_file_mb_skips_oversized_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that oversized files are skipped, both via Content-Length and progressive streaming counts."""
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    now = datetime.now(timezone.utc)
    mock_rows = [
        # 1. Oversized via Content-Length header
        CommentAttachment(
            attachment_id="attach_cl_pdf",
            comment_id="comment_1",
            docket_id="DOCKET-1",
            file_name="large_cl.pdf",
            file_url="https://example.com/large_cl.pdf",
            format="pdf",
            size_bytes=100000000,
            detected_at=now,
            download_status="pending",
        ),
        # 2. Oversized mid-stream (omitted Content-Length)
        CommentAttachment(
            attachment_id="attach_stream_pdf",
            comment_id="comment_2",
            docket_id="DOCKET-1",
            file_name="large_stream.pdf",
            file_url="https://example.com/large_stream.pdf",
            format="pdf",
            size_bytes=0,
            detected_at=now,
            download_status="pending",
        ),
    ]
    merge_comment_attachments(table_path, _to_attachments_arrow(mock_rows))

    # Mock responses:
    # First response (cl): Content-Length header set to 30 MB (exceeds limit of 2 MB)
    mock_response_cl = MagicMock()
    mock_response_cl.status_code = 200
    mock_response_cl.headers = {"content-length": str(30 * 1024 * 1024)}
    mock_response_cl.iter_bytes.return_value = []

    # Second response (stream): Content-Length omitted, streams chunks that exceed 2 MB
    mock_response_stream = MagicMock()
    mock_response_stream.status_code = 200
    mock_response_stream.headers = {}
    mock_response_stream.iter_bytes.return_value = [b"A" * 1024 * 1024] * 3  # 3 MB total

    # Use a URL-dependent stream context side-effect to avoid ordering issues
    def dynamic_stream(method: str, url: str, **kwargs: Any) -> MagicMock:
        mock_ctx = MagicMock()
        if "large_cl.pdf" in url:
            mock_ctx.__enter__.return_value = mock_response_cl
        else:
            mock_ctx.__enter__.return_value = mock_response_stream
        return mock_ctx

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.side_effect = dynamic_stream

    # Run downloader with limit of 2 MB
    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
        max_downloads=5,
        max_file_mb=2,
    )
    output = agent.run(inputs)

    # 1 skipped via header, 1 failed mid-stream due to chunk check limit exception
    assert output.downloaded_count == 0
    assert output.skipped_count == 1
    assert output.failed_count == 1

    # Read back Delta table rows
    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()
    
    # Assert by finding the exact records by attachment_id
    cl_record = next(r for r in records if r["attachment_id"] == "attach_cl_pdf")
    stream_record = next(r for r in records if r["attachment_id"] == "attach_stream_pdf")

    # Content-Length check skips cleanly
    assert cl_record["download_status"] == "skipped"
    assert "exceeds limit" in cl_record["download_error"]

    # Progressive check catches and sets status to failed (mid-stream exception)
    assert stream_record["download_status"] == "failed"
    assert "limit of 2 MB" in stream_record["download_error"]

    # Verify no files remain on disk (cleanup worked)
    part_file = attachments_path / "DOCKET-1" / "comment_2" / "attach_stream_pdf.pdf.part"
    final_file = attachments_path / "DOCKET-1" / "comment_2" / "attach_stream_pdf.pdf"
    assert not part_file.exists()
    assert not final_file.exists()


def test_unsupported_extension_skipped(tmp_path: Path) -> None:
    """Verifies that files with unsupported extensions are skipped immediately without network request."""
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    now = datetime.now(timezone.utc)
    mock_row = CommentAttachment(
        attachment_id="attach_exe",
        comment_id="comment_1",
        docket_id="DOCKET-1",
        file_name="malicious.exe",
        file_url="https://example.com/malicious.exe",
        format="exe",
        size_bytes=100,
        detected_at=now,
        download_status="pending",
    )
    merge_comment_attachments(table_path, _to_attachments_arrow([mock_row]))

    # Mock client that raises an exception if stream() is called (to verify no network requests are made)
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.side_effect = AssertionError("Should not make network requests for unsupported formats")

    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
    )
    output = agent.run(inputs)

    assert output.downloaded_count == 0
    assert output.skipped_count == 1
    assert output.failed_count == 0

    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()
    assert records[0]["download_status"] == "skipped"
    assert "allowed extensions" in records[0]["download_error"]


def test_failed_http_marks_failed_without_crashing(tmp_path: Path) -> None:
    """Verifies that HTTP failures (e.g. 404, 500, timeouts) mark the file failed but allow the run to continue."""
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    now = datetime.now(timezone.utc)
    mock_rows = [
        CommentAttachment(
            attachment_id="attach_404_pdf",
            comment_id="comment_1",
            docket_id="DOCKET-1",
            file_name="not_found.pdf",
            file_url="https://example.com/not_found.pdf",
            format="pdf",
            size_bytes=100,
            detected_at=now,
            download_status="pending",
        ),
        CommentAttachment(
            attachment_id="attach_ok_pdf",
            comment_id="comment_2",
            docket_id="DOCKET-1",
            file_name="success.pdf",
            file_url="https://example.com/success.pdf",
            format="pdf",
            size_bytes=100,
            detected_at=now,
            download_status="pending",
        ),
    ]
    merge_comment_attachments(table_path, _to_attachments_arrow(mock_rows))

    # Mock response 1 raises 404 error, response 2 succeeds
    mock_response_404 = MagicMock()
    mock_response_404.status_code = 404
    mock_response_404.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=mock_response_404
    )

    mock_response_ok = MagicMock()
    mock_response_ok.status_code = 200
    mock_response_ok.headers = {"content-length": "5"}
    mock_response_ok.iter_bytes.return_value = [b"hello"]

    # Use a URL-dependent stream context side-effect to avoid ordering issues
    def dynamic_stream(method: str, url: str, **kwargs: Any) -> MagicMock:
        mock_ctx = MagicMock()
        if "not_found.pdf" in url:
            mock_ctx.__enter__.return_value = mock_response_404
        else:
            mock_ctx.__enter__.return_value = mock_response_ok
        return mock_ctx

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.side_effect = dynamic_stream

    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
        max_downloads=5,
    )
    output = agent.run(inputs)

    assert output.downloaded_count == 1
    assert output.failed_count == 1
    assert output.skipped_count == 0

    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()
    
    # Assert by finding the exact records by attachment_id
    r_404 = next(r for r in records if r["attachment_id"] == "attach_404_pdf")
    r_ok = next(r for r in records if r["attachment_id"] == "attach_ok_pdf")

    # 404 file should be failed
    assert r_404["download_status"] == "failed"
    assert "HTTPStatusError" in r_404["download_error"]

    # OK file should be downloaded
    assert r_ok["download_status"] == "downloaded"
    assert r_ok["download_error"] is None


def test_existing_downloaded_file_skipped_unless_forced(tmp_path: Path) -> None:
    """Verifies that an existing local file cache triggers a direct DB update skipping the network call, unless force_download=True."""
    table_path = tmp_path / "silver" / "comment_attachments"
    attachments_path = tmp_path / "data" / "attachments"

    # Pre-populate dummy cached file on disk
    dest_dir = attachments_path / "DOCKET-1" / "comment_1"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_file = dest_dir / "attach_cached_pdf.pdf"
    content = b"Pre-cached local content"
    final_file.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    now = datetime.now(timezone.utc)
    mock_rows = [
        CommentAttachment(
            attachment_id="attach_cached_pdf",
            comment_id="comment_1",
            docket_id="DOCKET-1",
            file_name="cached.pdf",
            file_url="https://example.com/cached.pdf",
            format="pdf",
            size_bytes=len(content),
            detected_at=now,
            download_status="pending",
        )
    ]
    merge_comment_attachments(table_path, _to_attachments_arrow(mock_rows))

    # Mock client to verify no network call is made by default
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.stream.side_effect = AssertionError("Should not make network requests if cache file is present!")

    # 1. Run without force_download
    agent = AttachmentDownloaderAgent(http_client=mock_client)
    inputs = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
    )
    output = agent.run(inputs)

    # Note: Cache skips return success count in DB but don't count towards newly downloaded_count
    assert output.downloaded_count == 0
    assert output.skipped_count == 0
    assert output.failed_count == 0

    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()
    assert records[0]["download_status"] == "downloaded"
    assert records[0]["local_path"] == str(final_file)
    assert records[0]["checksum_sha256"] == expected_hash
    assert records[0]["size_bytes_actual"] == len(content)

    # 2. Reset status back to pending in Delta table
    mock_rows[0].download_status = "pending"
    merge_comment_attachments(table_path, _to_attachments_arrow(mock_rows))

    # 3. Setup mock client for force-download (network call is expected now)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "12"}
    mock_response.iter_bytes.return_value = [b"new content!"]
    
    mock_client_force = MagicMock(spec=httpx.Client)
    mock_client_force.stream.return_value.__enter__.return_value = mock_response

    inputs_force = DownloaderInput(
        docket_id="DOCKET-1",
        attachments_path=str(attachments_path),
        attachments_table_path=str(table_path),
        force_download=True,
    )
    agent_force = AttachmentDownloaderAgent(http_client=mock_client_force)
    output_force = agent_force.run(inputs_force)

    assert output_force.downloaded_count == 1

    # Check that disk contents are overwritten with the new downloaded content
    assert final_file.read_bytes() == b"new content!"
    
    records = DeltaTable(str(table_path)).to_pyarrow_table().to_pylist()
    assert records[0]["download_status"] == "downloaded"
    assert records[0]["size_bytes_actual"] == 12
    assert records[0]["checksum_sha256"] == hashlib.sha256(b"new content!").hexdigest()
