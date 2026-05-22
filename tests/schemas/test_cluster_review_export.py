"""Tests for the demo.cluster_review_export schema and export script."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import write_deltalake

from scripts.export_cluster_review_dataset import (
    build_export_rows,
    classify_source,
    export_cluster_review_dataset,
    rows_to_arrow,
    truncate_text,
)
from shared.schemas.cluster_review_export import (
    EXACT_HASH_BACKEND,
    SOURCE_EXACT_HASH,
    SOURCE_SEMANTIC,
    TEXT_PREVIEW_CHAR_LIMIT,
    ClusterReviewExportRow,
    cluster_review_export_arrow_schema,
    cluster_review_export_struct,
)


def test_schema_sync_across_pydantic_arrow_and_spark() -> None:
    pydantic_fields = list(ClusterReviewExportRow.model_fields.keys())
    arrow_fields = cluster_review_export_arrow_schema().names
    spark_fields = [f.name for f in cluster_review_export_struct().fields]

    assert arrow_fields == pydantic_fields
    assert spark_fields == pydantic_fields


def test_schema_has_required_review_ux_fields() -> None:
    fields = set(ClusterReviewExportRow.model_fields)
    expected = {
        "cluster_id",
        "docket_id",
        "embedding_model",
        "similarity_threshold",
        "cluster_size",
        "representative_comment_id",
        "comment_id",
        "is_representative",
        "text_source",
        "text_preview",
        "submitter_name",
        "posted_date",
        "source",
    }
    assert expected.issubset(fields)


def test_row_round_trips_through_arrow_schema() -> None:
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    posted = datetime(2024, 1, 2, tzinfo=timezone.utc)
    row = ClusterReviewExportRow(
        cluster_id="cluster-1",
        docket_id="DOCKET-A",
        embedding_model="databricks-bge-large-en",
        similarity_threshold=0.92,
        cluster_size=3,
        representative_comment_id="c-rep",
        comment_id="c-rep",
        is_representative=True,
        text_source="detail_comment_text",
        text_preview="Hello world",
        submitter_name="Jane Doe",
        posted_date=posted,
        source=SOURCE_SEMANTIC,
        exported_at=now,
    )

    table = rows_to_arrow([row])

    assert table.schema == cluster_review_export_arrow_schema()
    assert table.num_rows == 1
    record = table.to_pylist()[0]
    assert record["cluster_id"] == "cluster-1"
    assert record["is_representative"] is True
    assert record["similarity_threshold"] == pytest.approx(0.92)
    assert record["submitter_name"] == "Jane Doe"
    assert record["source"] == SOURCE_SEMANTIC
    assert record["posted_date"] == posted


def test_truncate_text_collapses_whitespace_and_truncates() -> None:
    assert truncate_text(" alpha\n  beta\tgamma ") == "alpha beta gamma"
    assert truncate_text(None) is None
    assert truncate_text("") is None

    long_text = "x" * (TEXT_PREVIEW_CHAR_LIMIT + 50)
    truncated = truncate_text(long_text)
    assert truncated is not None
    assert len(truncated) == TEXT_PREVIEW_CHAR_LIMIT
    assert truncated.endswith("...")


def test_classify_source_maps_exact_hash_backend() -> None:
    assert classify_source(EXACT_HASH_BACKEND) == SOURCE_EXACT_HASH
    assert classify_source("sentence_transformers") == SOURCE_SEMANTIC
    assert classify_source("databricks_foundation_model") == SOURCE_SEMANTIC
    assert classify_source(None) == SOURCE_SEMANTIC


def _make_clusters_table() -> pa.Table:
    return pa.table(
        {
            "cluster_id": ["cluster-1"],
            "docket_id": ["DOCKET-A"],
            "embedding_model": ["databricks-bge-large-en"],
            "similarity_threshold": [0.92],
            "cluster_size": [2],
            "representative_comment_id": ["c-rep"],
            "embedding_backend": ["databricks_foundation_model"],
        }
    )


def _make_memberships_table() -> pa.Table:
    return pa.table(
        {
            "cluster_id": ["cluster-1", "cluster-1"],
            "comment_id": ["c-rep", "c-other"],
            "docket_id": ["DOCKET-A", "DOCKET-A"],
            "embedding_model": [
                "databricks-bge-large-en",
                "databricks-bge-large-en",
            ],
            "similarity_threshold": [0.92, 0.92],
            "text_source": ["detail_comment_text", "detail_comment_text"],
        }
    )


def _make_parsed_table() -> pa.Table:
    posted = datetime(2024, 5, 1, tzinfo=timezone.utc)
    return pa.table(
        {
            "comment_id": ["c-rep", "c-other"],
            "docket_id": ["DOCKET-A", "DOCKET-A"],
            "raw_text": ["Representative comment body", "Other body"],
            "normalized_text": [
                "representative comment body",
                "other body",
            ],
            "posted_date": pa.array(
                [posted, posted], type=pa.timestamp("us", tz="UTC")
            ),
        }
    )


def _make_raw_comments_table() -> pa.Table:
    return pa.table(
        {
            "comment_id": ["c-rep", "c-other"],
            "docket_id": ["DOCKET-A", "DOCKET-A"],
            "submitter_name": ["Alice", "Bob"],
        }
    )


def test_build_export_rows_marks_representative_and_truncates_preview() -> None:
    long_body = "lorem ipsum " * 100
    parsed = pa.table(
        {
            "comment_id": ["c-rep"],
            "docket_id": ["DOCKET-A"],
            "raw_text": [long_body],
            "normalized_text": [long_body],
            "posted_date": pa.array(
                [datetime(2024, 1, 1, tzinfo=timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            ),
        }
    )

    rows = build_export_rows(
        clusters=_make_clusters_table().to_pandas(),
        memberships=_make_memberships_table().to_pandas(),
        parsed_comments=parsed.to_pandas(),
        raw_comments=None,
        exported_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    by_id = {row.comment_id: row for row in rows}
    assert by_id["c-rep"].is_representative is True
    assert by_id["c-other"].is_representative is False
    assert by_id["c-rep"].text_preview is not None
    assert len(by_id["c-rep"].text_preview) <= TEXT_PREVIEW_CHAR_LIMIT
    assert by_id["c-other"].text_preview is None
    assert by_id["c-rep"].source == SOURCE_SEMANTIC


def _write_delta(path: Path, table: pa.Table) -> None:
    write_deltalake(str(path), table, mode="overwrite")


def _seed_fixtures(tmp_path: Path) -> dict[str, Any]:
    clusters_path = tmp_path / "gold" / "comment_clusters"
    memberships_path = tmp_path / "gold" / "comment_cluster_memberships"
    parsed_path = tmp_path / "silver" / "parsed_comments"
    raw_path = tmp_path / "bronze" / "raw_comments"

    _write_delta(clusters_path, _make_clusters_table())
    _write_delta(memberships_path, _make_memberships_table())
    _write_delta(parsed_path, _make_parsed_table())
    _write_delta(raw_path, _make_raw_comments_table())

    return {
        "clusters_path": str(clusters_path),
        "memberships_path": str(memberships_path),
        "parsed_comments_path": str(parsed_path),
        "raw_comments_path": str(raw_path),
    }


def test_export_script_writes_parquet_and_is_idempotent(tmp_path: Path) -> None:
    paths = _seed_fixtures(tmp_path)
    output_dir = tmp_path / "exports" / "cluster_review_export"

    summary = export_cluster_review_dataset(
        docket_id="DOCKET-A",
        embedding_model="databricks-bge-large-en",
        similarity_threshold=0.92,
        output_dir=str(output_dir),
        **paths,
    )

    assert summary["rows_written"] == 2
    assert summary["clusters_in_scope"] == 1
    assert summary["memberships_in_scope"] == 2

    written = pq.read_table(summary["output_file"])
    assert written.schema == cluster_review_export_arrow_schema()
    records = written.to_pylist()
    assert {r["comment_id"] for r in records} == {"c-rep", "c-other"}
    assert {r["submitter_name"] for r in records} == {"Alice", "Bob"}
    assert {r["source"] for r in records} == {SOURCE_SEMANTIC}
    rep = next(r for r in records if r["comment_id"] == "c-rep")
    assert rep["is_representative"] is True
    assert rep["text_preview"] == "Representative comment body"

    # Idempotency: refuses to overwrite by default.
    with pytest.raises(FileExistsError):
        export_cluster_review_dataset(
            docket_id="DOCKET-A",
            embedding_model="databricks-bge-large-en",
            similarity_threshold=0.92,
            output_dir=str(output_dir),
            **paths,
        )

    # With --overwrite, it replaces the dataset cleanly.
    rerun = export_cluster_review_dataset(
        docket_id="DOCKET-A",
        embedding_model="databricks-bge-large-en",
        similarity_threshold=0.92,
        output_dir=str(output_dir),
        overwrite=True,
        **paths,
    )
    assert rerun["rows_written"] == 2
    assert pq.read_table(rerun["output_file"]).num_rows == 2


def test_export_script_labels_exact_hash_runs(tmp_path: Path) -> None:
    clusters = pa.table(
        {
            "cluster_id": ["cluster-x"],
            "docket_id": ["DOCKET-A"],
            "embedding_model": ["normalized_text_hash"],
            "similarity_threshold": [1.0],
            "cluster_size": [2],
            "representative_comment_id": ["c-rep"],
            "embedding_backend": [EXACT_HASH_BACKEND],
        }
    )
    memberships = pa.table(
        {
            "cluster_id": ["cluster-x", "cluster-x"],
            "comment_id": ["c-rep", "c-other"],
            "docket_id": ["DOCKET-A", "DOCKET-A"],
            "embedding_model": ["normalized_text_hash", "normalized_text_hash"],
            "similarity_threshold": [1.0, 1.0],
            "text_source": ["detail_comment_text", "detail_comment_text"],
        }
    )

    clusters_path = tmp_path / "gold" / "comment_clusters"
    memberships_path = tmp_path / "gold" / "comment_cluster_memberships"
    parsed_path = tmp_path / "silver" / "parsed_comments"
    _write_delta(clusters_path, clusters)
    _write_delta(memberships_path, memberships)
    _write_delta(parsed_path, _make_parsed_table())

    output_dir = tmp_path / "exports" / "cluster_review_export"
    summary = export_cluster_review_dataset(
        docket_id="DOCKET-A",
        embedding_model="normalized_text_hash",
        similarity_threshold=1.0,
        clusters_path=str(clusters_path),
        memberships_path=str(memberships_path),
        parsed_comments_path=str(parsed_path),
        raw_comments_path=None,
        output_dir=str(output_dir),
    )

    records = pq.read_table(summary["output_file"]).to_pylist()
    assert {r["source"] for r in records} == {SOURCE_EXACT_HASH}
