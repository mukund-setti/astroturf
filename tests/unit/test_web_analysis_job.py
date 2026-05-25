from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from agents.ingestion.agent import IngestionInput
from scripts import smoke_web_analysis_job
from scripts.web_analysis_job_support import (
    build_agent_inputs,
    build_web_analysis_paths,
    parse_web_analysis_params,
)


BASE_PARAMS = {
    "docket_id": "CFPB-2016-0025",
    "source": "regulations_gov",
    "topic_id": "consumer_finance",
    "agency_id": "CFPB",
    "start_date": "",
    "end_date": "",
    "expected_scale": "10",
    "request_id": "manual_smoke_test",
    "catalog": "astroturf",
    "data_root": "/tmp/astroturf-web-job-smoke",
    "repo_path": ".",
    "vector_index_name": "",
    "clustering_mode": "local",
    "similarity_threshold": "0.92",
    "dry_run": "true",
}


def test_web_params_parse_successfully() -> None:
    params = parse_web_analysis_params(BASE_PARAMS)

    assert params.docket_id == "CFPB-2016-0025"
    assert params.source == "regulations_gov"
    assert params.expected_scale == 10
    assert params.clustering_mode == "local"
    assert params.dry_run is True


def test_ingestion_input_construction_matches_schema() -> None:
    params = parse_web_analysis_params(BASE_PARAMS)
    paths = build_web_analysis_paths(params)
    inputs = build_agent_inputs(params, paths)

    ingestion_fields = {field.name for field in fields(IngestionInput)}
    assert {
        "docket_id",
        "source",
        "max_comments",
        "start_date",
        "end_date",
    }.issubset(ingestion_fields)
    assert inputs.ingestion == IngestionInput(
        docket_id="CFPB-2016-0025",
        source="regulations_gov",
        max_comments=10,
        start_date=None,
        end_date=None,
    )


def test_missing_docket_id_fails_clearly() -> None:
    raw = dict(BASE_PARAMS)
    raw["docket_id"] = ""

    with pytest.raises(
        ValueError, match="Missing required Databricks job parameter: docket_id"
    ):
        parse_web_analysis_params(raw)


def test_unsupported_source_fails_clearly() -> None:
    raw = dict(BASE_PARAMS)
    raw["source"] = "not_a_source"

    with pytest.raises(ValueError, match="Unsupported source='not_a_source'"):
        parse_web_analysis_params(raw)


def test_smoke_harness_does_not_log_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", "super-secret-value")
    monkeypatch.setattr("sys.argv", ["smoke_web_analysis_job.py", "--dry-run"])

    smoke_web_analysis_job.main()

    captured = capsys.readouterr()
    assert "super-secret-value" not in captured.out
    assert "super-secret-value" not in captured.err
    assert "web_analysis_job smoke parameters parsed successfully" in captured.out


def test_databricks_notebook_is_self_contained() -> None:
    notebook = Path("notebooks/databricks/web_analysis_job.py").read_text()

    assert "scripts.web_analysis_job_support" not in notebook
