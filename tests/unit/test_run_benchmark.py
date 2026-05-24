"""Unit tests for scripts/run_benchmark.py."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


from scripts.run_benchmark import run_benchmark_pipeline
from agents.ingestion.sources.ecfs import ECFSClient, ECFSClientConfig
from scripts.ingest_benchmark_sample import ingest_stratified_sample
from tests.unit.test_ingestion_ecfs import _FakeResponse, FakeECFSHttp, _filing


def test_run_benchmark_pipeline_end_to_end(tmp_path) -> None:
    """Test that run_benchmark_pipeline executes the full medallion benchmark safely on a mini test dataset."""
    docket_id = "17-108"
    bronze = str(tmp_path / "bronze")
    silver_parsed = str(tmp_path / "silver_parsed")
    details = str(tmp_path / "silver_details")
    attachments = str(tmp_path / "silver_attachments")
    embeddings = str(tmp_path / "silver_embeddings")
    clusters = str(tmp_path / "gold_clusters")
    memberships = str(tmp_path / "gold_memberships")
    report_dir = str(tmp_path / "reports")

    # Ingest 5 filings into bronze (3 identical templates to form a cluster, 2 unique text)
    filings = [
        _filing(
            id_sub="f0",
            text="The Obama regulations smothers innovation and damages economy.",
        ),
        _filing(
            id_sub="f1",
            text="The Obama regulations smothers innovation and damages economy.",
        ),
        _filing(
            id_sub="f2",
            text="The Obama regulations smothers innovation and damages economy.",
        ),
        _filing(id_sub="f3", text="I support net neutrality rules! Keep title II!"),
        _filing(
            id_sub="f4", text="Net neutrality protects small businesses from ISP greed."
        ),
    ]

    def responder(url: str, params: dict[str, Any]) -> _FakeResponse:
        return _FakeResponse(200, {"filing": filings})

    http = FakeECFSHttp(responder)
    client = ECFSClient(
        ECFSClientConfig(api_key="k", page_size=10, rate_limit_qps=0),
        http_client=http,
    )

    # Ingest mock bronze data
    ingest_stratified_sample(
        docket_id=docket_id,
        bronze_path=bronze,
        start_date=date(2017, 8, 28),
        end_date=date(2017, 8, 28),
        max_comments_per_day=10,
        manifest_path=str(tmp_path / "manifest.json"),
        client=client,
    )

    # Run the comparative benchmark pipeline
    metrics = run_benchmark_pipeline(
        docket_id=docket_id,
        bronze_path=bronze,
        silver_path=silver_parsed,
        details_path=details,
        attachments_path=attachments,
        embeddings_path=embeddings,
        clusters_path=clusters,
        memberships_path=memberships,
        local_clustering_cap=10,
        report_dir=report_dir,
        use_sentence_transformers=False,  # Use mock backend for unit test speed
    )

    # Verify return values
    assert metrics["docket_id"] == docket_id
    assert metrics["sample_size"] == 5
    assert (
        metrics["exact_hash_covered_comments"] == 3
    )  # The 3 identical comments form an exact hash cluster
    assert metrics["exact_hash_clusters"] == 1
    assert (
        metrics["semantic_covered_comments"] == 3
    )  # They also form a semantic cluster
    assert metrics["semantic_clusters"] == 1
    assert metrics["lift_ratio"] == 1.0

    # Verify generated report documents
    assert Path(report_dir).exists()
    json_rep = Path(report_dir) / "benchmark_metrics.json"
    md_rep = Path(report_dir) / "benchmark_report.md"
    assert json_rep.exists()
    assert md_rep.exists()

    # Load JSON and verify keys
    with open(json_rep, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["exact_hash_covered_comments"] == 3
    assert loaded["sample_size"] == 5

    # Check Markdown content contains claims and calculations
    md_text = md_rep.read_text(encoding="utf-8")
    assert (
        "Obama regulations smothers" not in md_text
    )  # Check that text is clean of raw code leaks
    assert "Exact duplicate analysis stumbles on comments" in md_text
    assert "connected-components FAILURE SIMULATION" in md_text
    assert "Why Databricks Matters" in md_text
