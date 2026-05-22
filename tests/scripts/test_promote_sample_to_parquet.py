"""Tests for ``scripts/promote_sample_to_parquet.py``.

A tiny fixture lakehouse is built with delta-rs and the exporter is run against
it. The test asserts:

- Per-table Parquet files exist under the output directory.
- Per-table Parquet schemas match the canonical Pydantic-derived Arrow schemas.
- Docket and embedding-model filters are applied.
- The default refuses to overwrite an existing export; ``--overwrite`` replaces.
- ``--include-cfpb-sample`` pulls in CFPB rows when set, and excludes them by
  default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import write_deltalake

from scripts.promote_sample_to_parquet import (
    CFPB_DOCKET,
    DATABRICKS_EMBEDDING_MODEL,
    EPA_DOCKET,
    TABLE_EXPORTS,
    coerce_to_schema,
    export_one,
    load_cfpb_comment_id_slice,
    output_path_for,
)
from shared.schemas.comment_attachments import comment_attachment_arrow_schema
from shared.schemas.comment_clusters import (
    comment_cluster_arrow_schema,
    comment_cluster_membership_arrow_schema,
)
from shared.schemas.comment_details import comment_detail_arrow_schema
from shared.schemas.comment_embeddings import comment_embedding_arrow_schema
from shared.schemas.comments import raw_comment_arrow_schema
from shared.schemas.parsed_comments import parsed_comment_arrow_schema


NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
OTHER_MODEL = "BAAI/bge-large-en-v1.5"


def _write_delta(path: Path, table: pa.Table) -> None:
    write_deltalake(str(path), table, mode="overwrite")


def _bronze_rows() -> pa.Table:
    schema = raw_comment_arrow_schema()
    rows = [
        {
            "comment_id": "EPA-1",
            "docket_id": EPA_DOCKET,
            "ingested_at": NOW,
            "has_attachments": False,
            "attributes_json": "{}",
        },
        {
            "comment_id": "EPA-2",
            "docket_id": EPA_DOCKET,
            "ingested_at": NOW,
            "has_attachments": False,
            "attributes_json": "{}",
        },
        # CFPB-1 is in the curated parsed slice; CFPB-UNPARSED is bronze-only
        # and should be excluded from the CFPB slice export.
        {
            "comment_id": "CFPB-1",
            "docket_id": CFPB_DOCKET,
            "ingested_at": NOW,
            "has_attachments": False,
            "attributes_json": "{}",
        },
        {
            "comment_id": "CFPB-UNPARSED",
            "docket_id": CFPB_DOCKET,
            "ingested_at": NOW,
            "has_attachments": False,
            "attributes_json": "{}",
        },
        {
            "comment_id": "OTHER-1",
            "docket_id": "OTHER-DOCKET-1",
            "ingested_at": NOW,
            "has_attachments": False,
            "attributes_json": "{}",
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _parsed_rows() -> pa.Table:
    schema = parsed_comment_arrow_schema()
    rows = [
        {
            "comment_id": "EPA-1",
            "docket_id": EPA_DOCKET,
            "source_system_version": "v4",
            "parser_version": "v1",
            "text_source": "comment_text",
            "token_estimate": 5,
            "char_count": 50,
            "parse_status": "ok",
            "parsed_at": NOW,
        },
        {
            "comment_id": "CFPB-1",
            "docket_id": CFPB_DOCKET,
            "source_system_version": "v4",
            "parser_version": "v1",
            "text_source": "comment_text",
            "token_estimate": 7,
            "char_count": 70,
            "parse_status": "ok",
            "parsed_at": NOW,
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _details_rows() -> pa.Table:
    schema = comment_detail_arrow_schema()
    rows = [
        {
            "comment_id": "EPA-1",
            "docket_id": EPA_DOCKET,
            "enrichment_status": "ok",
            "extracted_at": NOW,
            "api_version": "regulations.gov_v4",
            "has_substantive_comment": True,
            "is_cover_note": False,
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _attachments_rows() -> pa.Table:
    schema = comment_attachment_arrow_schema()
    rows = [
        {
            "attachment_id": "EPA-1_pdf",
            "comment_id": "EPA-1",
            "docket_id": EPA_DOCKET,
            "file_url": "https://example.com/x.pdf",
            "format": "pdf",
            "detected_at": NOW,
            "download_status": "pending",
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _embeddings_rows() -> pa.Table:
    schema = comment_embedding_arrow_schema()
    rows = [
        {
            "comment_id": "EPA-1",
            "docket_id": EPA_DOCKET,
            "embedding_model": DATABRICKS_EMBEDDING_MODEL,
            "embedding_dim": 4,
            "text_hash": "abc",
            "text_source": "comment_text",
            "embedding_vector": [0.1, 0.2, 0.3, 0.4],
            "embedded_at": NOW,
            "backend": "databricks_foundation_model",
        },
        {
            "comment_id": "EPA-2",
            "docket_id": EPA_DOCKET,
            "embedding_model": OTHER_MODEL,
            "embedding_dim": 4,
            "text_hash": "def",
            "text_source": "comment_text",
            "embedding_vector": [0.5, 0.6, 0.7, 0.8],
            "embedded_at": NOW,
            "backend": "local_sentence_transformer",
        },
        {
            "comment_id": "CFPB-1",
            "docket_id": CFPB_DOCKET,
            "embedding_model": DATABRICKS_EMBEDDING_MODEL,
            "embedding_dim": 4,
            "text_hash": "ghi",
            "text_source": "comment_text",
            "embedding_vector": [0.9, 0.1, 0.1, 0.1],
            "embedded_at": NOW,
            "backend": "databricks_foundation_model",
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _clusters_rows() -> pa.Table:
    schema = comment_cluster_arrow_schema()
    rows = [
        {
            "cluster_id": "epa-cluster-1",
            "clustering_run_id": "run-1",
            "docket_id": EPA_DOCKET,
            "embedding_model": DATABRICKS_EMBEDDING_MODEL,
            "embedding_backend": "databricks_foundation_model",
            "clustering_version": "v1",
            "similarity_threshold": 0.92,
            "candidate_count": 2,
            "cluster_size": 2,
            "representative_comment_id": "EPA-1",
            "representative_text_hash": "abc",
            "mean_similarity": 0.97,
            "min_similarity": 0.95,
            "max_similarity": 1.0,
            "created_at": NOW,
            "updated_at": NOW,
        },
        {
            "cluster_id": "epa-cluster-other-model",
            "clustering_run_id": "run-2",
            "docket_id": EPA_DOCKET,
            "embedding_model": OTHER_MODEL,
            "embedding_backend": "local_sentence_transformer",
            "clustering_version": "v1",
            "similarity_threshold": 0.92,
            "candidate_count": 1,
            "cluster_size": 1,
            "representative_comment_id": "EPA-2",
            "representative_text_hash": "def",
            "mean_similarity": 1.0,
            "min_similarity": 1.0,
            "max_similarity": 1.0,
            "created_at": NOW,
            "updated_at": NOW,
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


def _memberships_rows() -> pa.Table:
    schema = comment_cluster_membership_arrow_schema()
    rows = [
        {
            "cluster_id": "epa-cluster-1",
            "comment_id": "EPA-1",
            "clustering_run_id": "run-1",
            "docket_id": EPA_DOCKET,
            "embedding_model": DATABRICKS_EMBEDDING_MODEL,
            "embedding_backend": "databricks_foundation_model",
            "clustering_version": "v1",
            "similarity_threshold": 0.92,
            "text_hash": "abc",
            "text_source": "comment_text",
            "similarity_to_representative": 1.0,
            "membership_rank": 1,
            "created_at": NOW,
            "updated_at": NOW,
        },
        {
            "cluster_id": "epa-cluster-other-model",
            "comment_id": "EPA-2",
            "clustering_run_id": "run-2",
            "docket_id": EPA_DOCKET,
            "embedding_model": OTHER_MODEL,
            "embedding_backend": "local_sentence_transformer",
            "clustering_version": "v1",
            "similarity_threshold": 0.92,
            "text_hash": "def",
            "text_source": "comment_text",
            "similarity_to_representative": 1.0,
            "membership_rank": 1,
            "created_at": NOW,
            "updated_at": NOW,
        },
    ]
    return coerce_to_schema(pa.Table.from_pylist(rows), schema)


@pytest.fixture
def lakehouse(tmp_path: Path) -> Path:
    """Build a tiny delta-rs lakehouse rooted at ``tmp_path``."""
    data_dir = tmp_path / "data"
    (data_dir / "bronze").mkdir(parents=True)
    (data_dir / "silver").mkdir(parents=True)
    (data_dir / "gold").mkdir(parents=True)

    _write_delta(data_dir / "bronze" / "raw_comments", _bronze_rows())
    _write_delta(data_dir / "silver" / "parsed_comments", _parsed_rows())
    _write_delta(data_dir / "silver" / "comment_details", _details_rows())
    _write_delta(data_dir / "silver" / "comment_attachments", _attachments_rows())
    _write_delta(data_dir / "silver" / "comment_embeddings", _embeddings_rows())
    _write_delta(data_dir / "gold" / "comment_clusters", _clusters_rows())
    _write_delta(data_dir / "gold" / "comment_cluster_memberships", _memberships_rows())
    return data_dir


def _run_all_exports(
    data_dir: Path,
    output_dir: Path,
    *,
    include_cfpb: bool,
    overwrite: bool = False,
) -> dict[str, dict]:
    dockets = [EPA_DOCKET] + ([CFPB_DOCKET] if include_cfpb else [])
    docket_comment_ids: dict[str, list[str]] = {}
    if include_cfpb:
        docket_comment_ids[CFPB_DOCKET] = load_cfpb_comment_id_slice(
            str(data_dir), docket=CFPB_DOCKET
        )
    summaries: dict[str, dict] = {}
    for export in TABLE_EXPORTS:
        summary = export_one(
            export,
            data_dir=str(data_dir),
            output_dir=str(output_dir),
            dockets=dockets,
            embedding_model=DATABRICKS_EMBEDDING_MODEL,
            overwrite=overwrite,
            docket_comment_ids=docket_comment_ids or None,
        )
        summaries[export.name] = summary
    return summaries


def test_export_writes_parquet_per_table_with_canonical_schema(
    tmp_path: Path, lakehouse: Path
) -> None:
    output_dir = tmp_path / "out"

    summaries = _run_all_exports(lakehouse, output_dir, include_cfpb=False)

    for export in TABLE_EXPORTS:
        out_path = (
            Path(output_path_for(str(output_dir), export.name)) / "part-000.parquet"
        )
        assert out_path.exists(), f"{export.name} parquet missing"
        parquet_schema = pq.read_schema(out_path)
        expected = export.schema_fn()
        # Field order and types must match the canonical Arrow schema.
        assert parquet_schema.names == expected.names
        for field in expected:
            assert parquet_schema.field(field.name).type == field.type, field.name
        assert summaries[export.name]["source_exists"] is True


def test_epa_only_default_filters_out_cfpb_and_wrong_model(
    tmp_path: Path, lakehouse: Path
) -> None:
    output_dir = tmp_path / "out"

    summaries = _run_all_exports(lakehouse, output_dir, include_cfpb=False)

    # bronze: 2 EPA rows only
    assert summaries["bronze.raw_comments"]["row_count"] == 2
    # parsed: 1 EPA row only
    assert summaries["silver.parsed_comments"]["row_count"] == 1
    # embeddings: only the Databricks-model EPA row
    embeddings_path = (
        Path(output_path_for(str(output_dir), "silver.comment_embeddings"))
        / "part-000.parquet"
    )
    embeddings = pq.read_table(embeddings_path).to_pylist()
    assert len(embeddings) == 1
    assert embeddings[0]["comment_id"] == "EPA-1"
    assert embeddings[0]["embedding_model"] == DATABRICKS_EMBEDDING_MODEL
    # clusters/memberships filter by docket + model
    assert summaries["gold.comment_clusters"]["row_count"] == 1
    assert summaries["gold.comment_cluster_memberships"]["row_count"] == 1


def test_include_cfpb_sample_restricts_to_parsed_slice(
    tmp_path: Path, lakehouse: Path
) -> None:
    output_dir = tmp_path / "out"

    summaries = _run_all_exports(lakehouse, output_dir, include_cfpb=True)

    # bronze: 2 EPA + 1 CFPB (CFPB-UNPARSED excluded because it isn't in the
    # silver.parsed_comments curated slice).
    bronze_path = (
        Path(output_path_for(str(output_dir), "bronze.raw_comments"))
        / "part-000.parquet"
    )
    bronze_ids = sorted(
        row["comment_id"] for row in pq.read_table(bronze_path).to_pylist()
    )
    assert bronze_ids == ["CFPB-1", "EPA-1", "EPA-2"]
    assert summaries["bronze.raw_comments"]["row_count"] == 3
    assert summaries["silver.parsed_comments"]["row_count"] == 2
    # embeddings: EPA-1 (databricks) + CFPB-1 (databricks)
    assert summaries["silver.comment_embeddings"]["row_count"] == 2


def test_default_refuses_to_overwrite_existing_export(
    tmp_path: Path, lakehouse: Path
) -> None:
    output_dir = tmp_path / "out"
    _run_all_exports(lakehouse, output_dir, include_cfpb=False)

    with pytest.raises(FileExistsError):
        _run_all_exports(lakehouse, output_dir, include_cfpb=False)


def test_overwrite_replaces_existing_export(tmp_path: Path, lakehouse: Path) -> None:
    output_dir = tmp_path / "out"
    _run_all_exports(lakehouse, output_dir, include_cfpb=False)
    bronze_dir = Path(output_path_for(str(output_dir), "bronze.raw_comments"))
    stale = bronze_dir / "stale.txt"
    stale.write_text("stale", encoding="utf-8")

    _run_all_exports(lakehouse, output_dir, include_cfpb=False, overwrite=True)

    assert not stale.exists()
    assert (bronze_dir / "part-000.parquet").exists()


def test_missing_source_table_produces_empty_parquet_with_schema(
    tmp_path: Path,
) -> None:
    # Empty lakehouse: no delta tables at all.
    empty_data = tmp_path / "data"
    (empty_data / "bronze").mkdir(parents=True)
    output_dir = tmp_path / "out"

    summaries = _run_all_exports(empty_data, output_dir, include_cfpb=False)

    for export in TABLE_EXPORTS:
        assert summaries[export.name]["source_exists"] is False
        assert summaries[export.name]["row_count"] == 0
        out_path = (
            Path(output_path_for(str(output_dir), export.name)) / "part-000.parquet"
        )
        parquet_schema = pq.read_schema(out_path)
        expected = export.schema_fn()
        assert parquet_schema.names == expected.names


def test_coerce_to_schema_fills_missing_columns_with_nulls() -> None:
    schema = pa.schema(
        [
            pa.field("a", pa.string(), nullable=True),
            pa.field("b", pa.int64(), nullable=True),
            pa.field("c", pa.bool_(), nullable=True),
        ]
    )
    table = pa.Table.from_pylist([{"a": "x"}, {"a": "y"}])

    coerced = coerce_to_schema(table, schema)

    assert coerced.schema == schema
    assert coerced["a"].to_pylist() == ["x", "y"]
    assert coerced["b"].to_pylist() == [None, None]
    assert coerced["c"].to_pylist() == [None, None]
