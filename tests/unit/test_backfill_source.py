"""Unit tests for scripts/backfill_source_field.py (local target)."""

from __future__ import annotations

from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.compute as pc
import pytest
from deltalake import DeltaTable, write_deltalake

from scripts.backfill_source_field import backfill_local
from shared.schemas.comments import raw_comment_arrow_schema


def _old_schema_no_source() -> pa.Schema:
    """The bronze schema as it looked before ADR-0012 (no source / ecfs fields)."""
    new_fields = {
        "source",
        "ecfs_proceeding_id",
        "ecfs_submission_type_id",
        "ecfs_express_comment",
    }
    return pa.schema(
        [f for f in raw_comment_arrow_schema() if f.name not in new_fields]
    )


def _make_old_table(path: str, n_rows: int) -> None:
    schema = _old_schema_no_source()
    now = datetime.now(timezone.utc)
    cols: dict[str, list] = {name: [] for name in schema.names}
    for i in range(n_rows):
        d = {
            "comment_id": f"OLD-{i}",
            "docket_id": "EPA-HQ-OAR-2021-0317",
            "document_type": "PublicSubmission",
            "title": f"Title {i}",
            "posted_date": now,
            "received_date": now,
            "last_modified_date": now,
            "comment_text": f"Body {i}",
            "submitter_name": None,
            "first_name": None,
            "last_name": None,
            "organization": None,
            "city": None,
            "state_province_region": None,
            "country": None,
            "agency_id": "EPA",
            "has_attachments": False,
            "attributes_json": "{}",
            "ingested_at": now,
        }
        for k in cols:
            cols[k].append(d[k])
    table = pa.Table.from_pydict(cols, schema=schema)
    write_deltalake(path, table, mode="overwrite")


def test_backfill_adds_source_column_and_populates(tmp_path) -> None:
    bronze = str(tmp_path / "raw_comments")
    _make_old_table(bronze, n_rows=5)

    result = backfill_local(bronze)

    assert result["rows_before"] == 5
    assert result["rows_after"] == 5
    assert result["null_source_before"] == 5
    assert result["null_source_after"] == 0
    assert result["rows_updated"] == 5

    rows = DeltaTable(bronze).to_pyarrow_table()
    assert "source" in rows.column_names
    assert "ecfs_proceeding_id" in rows.column_names
    assert "ecfs_submission_type_id" in rows.column_names
    assert "ecfs_express_comment" in rows.column_names

    sources = rows.column("source").to_pylist()
    assert sources == ["regulations_gov"] * 5

    # The ECFS-only columns should be null for the backfilled regulations.gov rows.
    null_count = int(
        pc.sum(
            pc.cast(pc.is_null(rows.column("ecfs_proceeding_id")), pa.int64())
        ).as_py()
    )
    assert null_count == 5


def test_backfill_idempotent_second_run_is_noop(tmp_path) -> None:
    bronze = str(tmp_path / "raw_comments")
    _make_old_table(bronze, n_rows=3)

    backfill_local(bronze)
    second = backfill_local(bronze)

    assert second["null_source_before"] == 0
    assert second["rows_updated"] == 0


def test_backfill_raises_on_missing_table(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        backfill_local(str(tmp_path / "does_not_exist"))


def test_backfill_preserves_other_columns(tmp_path) -> None:
    bronze = str(tmp_path / "raw_comments")
    _make_old_table(bronze, n_rows=2)
    backfill_local(bronze)

    rows = DeltaTable(bronze).to_pyarrow_table().to_pylist()
    assert rows[0]["comment_id"] == "OLD-0"
    assert rows[1]["comment_id"] == "OLD-1"
    assert rows[0]["docket_id"] == "EPA-HQ-OAR-2021-0317"
    assert rows[0]["agency_id"] == "EPA"
    assert rows[0]["title"] == "Title 0"
    assert rows[0]["comment_text"] == "Body 0"
