"""Focused tests for Phase 5 platform scripts."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import write_deltalake

from scripts.check_databricks_ready import build_report, parse_args
from scripts.export_to_demo_table import (
    build_databricks_export_sql,
    export_to_demo_table,
)
from scripts.run_docket_pipeline import (
    build_execution_plan,
    load_dockets_config,
    validate_stages,
)


def test_readiness_checker_is_safe_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DATABRICKS_HTTP_PATH", raising=False)

    report = build_report(parse_args(["--no-env-file", "--timeout", "0.1"]))

    assert report["status"] == "FAILED"
    assert report["steps"]["environment"]["status"] == "FAIL"
    assert report["steps"]["connectivity"]["status"] == "SKIP"
    assert report["steps"]["vector_search"]["status"] == "SKIP"


def test_dockets_yaml_loads_and_validates() -> None:
    dockets = load_dockets_config("configs/dockets.yaml")
    by_id = {d.docket_id: d for d in dockets}

    assert by_id["17-108"].source == "ecfs"
    assert by_id["17-108"].processing_status == "analyzed"
    assert by_id["EPA-HQ-OAR-2021-0317"].processing_status == "baseline_only"
    # CFPB and SEC are registered via /analyze (or directly in dockets.yaml)
    # but have not been run through the pipeline yet — see
    # ALLOWED_PROCESSING_STATUSES in scripts/run_docket_pipeline.py and the
    # status table in docs/product-vision.md.
    assert by_id["CFPB-2016-0025"].processing_status == "configured_awaiting_run"
    assert by_id["SEC-2023-0001"].processing_status == "configured_awaiting_run"


def test_allowed_processing_statuses_documented() -> None:
    """All five tiers documented in docs/product-vision.md must be accepted."""
    from scripts.run_docket_pipeline import ALLOWED_PROCESSING_STATUSES

    assert ALLOWED_PROCESSING_STATUSES == frozenset(
        {
            "configured_awaiting_run",
            "queued",
            "partially_processed",
            "baseline_only",
            "analyzed",
        }
    )


def test_pipeline_dry_run_plan_includes_vector_index() -> None:
    [docket] = [
        d
        for d in load_dockets_config("configs/dockets.yaml")
        if d.docket_id == "17-108"
    ]
    stages = validate_stages(["embed", "cluster", "export"])

    plan = build_execution_plan(
        docket_config=docket,
        mode="databricks",
        stages=stages,
        limit=10,
        resume=True,
        catalog="workspace",
        vector_index_name="workspace.silver.test_index",
    )

    assert [item["stage"] for item in plan] == ["embed", "cluster", "export"]
    cluster_step = next(item for item in plan if item["stage"] == "cluster")
    assert cluster_step["embedding_model"] == "databricks-bge-large-en"
    assert cluster_step["vector_index_name"] == "workspace.silver.test_index"


def test_validate_stages_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="Unknown stage"):
        validate_stages(["embed", "bogus"])


def _write_delta(path: Path, table: pa.Table) -> None:
    write_deltalake(str(path), table, mode="overwrite")


def test_export_to_demo_table_local_writes_ui_required_fields(tmp_path: Path) -> None:
    clusters_path = tmp_path / "gold" / "comment_clusters"
    memberships_path = tmp_path / "gold" / "comment_cluster_memberships"
    parsed_path = tmp_path / "silver" / "parsed_comments"
    raw_path = tmp_path / "bronze" / "raw_comments"
    output_path = tmp_path / "exports" / "cluster_review_export"

    _write_delta(
        clusters_path,
        pa.table(
            {
                "cluster_id": ["cluster-1"],
                "docket_id": ["DOCKET-A"],
                "embedding_model": ["databricks-bge-large-en"],
                "similarity_threshold": [0.92],
                "cluster_size": [2],
                "representative_comment_id": ["c-rep"],
                "embedding_backend": ["databricks_foundation_model"],
                "mean_similarity": [0.96],
                "min_similarity": [0.93],
            }
        ),
    )
    _write_delta(
        memberships_path,
        pa.table(
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
                "text_hash": ["hash-1", "hash-2"],
                "similarity_to_representative": [1.0, 0.94],
            }
        ),
    )
    _write_delta(
        parsed_path,
        pa.table(
            {
                "comment_id": ["c-rep", "c-other"],
                "docket_id": ["DOCKET-A", "DOCKET-A"],
                "raw_text": ["Representative text", "Member text"],
                "normalized_text": ["representative text", "member text"],
                "posted_date": pa.array(
                    [None, None], type=pa.timestamp("us", tz="UTC")
                ),
            }
        ),
    )
    _write_delta(
        raw_path,
        pa.table(
            {
                "comment_id": ["c-rep", "c-other"],
                "docket_id": ["DOCKET-A", "DOCKET-A"],
                "submitter_name": ["Alice", "Bob"],
                "organization": ["Org A", "Org B"],
                "state_province_region": ["CA", "NY"],
                "country": ["US", "US"],
            }
        ),
    )

    export_to_demo_table(
        docket_id="DOCKET-A",
        topic_id="topic-a",
        agency_id="AGENCY",
        embedding_model="databricks-bge-large-en",
        similarity_threshold=0.92,
        clusters_path=str(clusters_path),
        memberships_path=str(memberships_path),
        parsed_comments_path=str(parsed_path),
        raw_comments_path=str(raw_path),
        output_target=str(output_path),
        mode="local",
    )

    records = pq.read_table(output_path / "cluster_review_export.parquet").to_pylist()
    assert len(records) == 2
    rep = next(row for row in records if row["comment_id"] == "c-rep")
    assert rep["topic_id"] == "topic-a"
    assert rep["agency_id"] == "AGENCY"
    assert rep["member_comment_id"] == "c-rep"
    assert rep["representative_text"] == "Representative text"
    assert rep["member_text"] == "Representative text"
    assert rep["similarity"] == pytest.approx(1.0)
    assert rep["exact_match_ratio"] == pytest.approx(0.5)
    assert rep["near_duplicate_ratio"] == pytest.approx(0.5)
    assert rep["purity_score"] == pytest.approx(0.93)
    assert rep["confidence_score"] == pytest.approx(0.96)


def test_databricks_export_sql_dry_run_contains_required_fields() -> None:
    sql = build_databricks_export_sql(
        catalog="workspace",
        output_target="workspace.demo.cluster_review_export",
        docket_id="DOCKET-A",
        topic_id="topic-a",
        agency_id="AGENCY",
        embedding_model="databricks-bge-large-en",
        similarity_threshold=0.92,
    )

    for column in (
        "topic_id",
        "agency_id",
        "representative_text",
        "member_comment_id",
        "member_text",
        "exact_match_ratio",
        "near_duplicate_ratio",
        "purity_score",
        "confidence_score",
    ):
        assert column in sql
