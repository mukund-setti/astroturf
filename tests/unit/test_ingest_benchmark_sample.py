"""Unit tests for ingest_benchmark_sample.py."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from deltalake import DeltaTable

from agents.ingestion.sources.ecfs import ECFSClient, ECFSClientConfig
from scripts.ingest_benchmark_sample import ingest_stratified_sample
from tests.unit.test_ingestion_ecfs import (
    _FakeResponse,
    FakeECFSHttp,
    _filing,
    _delta_rows,
)


def test_ingest_stratified_sample_manifest_and_data(tmp_path) -> None:
    """Test that ingest_stratified_sample successfully paginates per stratum, writes to bronze, and saves manifest."""
    docket_id = "17-108"
    bronze = str(tmp_path / "raw_comments")
    manifest_file = str(tmp_path / "manifest.json")

    # Mock ECFS response for August 21 and August 22 (2 days)
    # August 21 returns 3 filings, August 22 returns 2 filings
    filings_by_day = {
        "2017-08-21": [_filing(id_sub=f"f{i}") for i in range(3)],
        "2017-08-22": [_filing(id_sub=f"g{i}") for i in range(2)],
    }

    def responder(url: str, params: dict[str, Any]) -> _FakeResponse:
        assert url == "/filings"
        q = params.get("q", "")
        # Find which day this query is for
        current_day = None
        for day in filings_by_day:
            if day in q:
                current_day = day
                break

        assert current_day is not None
        filings = filings_by_day[current_day]
        return _FakeResponse(200, {"filing": filings})

    http = FakeECFSHttp(responder)
    client = ECFSClient(
        ECFSClientConfig(api_key="k", page_size=10, rate_limit_qps=0),
        http_client=http,
    )

    start_date = date(2017, 8, 21)
    end_date = date(2017, 8, 22)

    manifest = ingest_stratified_sample(
        docket_id=docket_id,
        bronze_path=bronze,
        start_date=start_date,
        end_date=end_date,
        max_comments_per_day=10,
        manifest_path=manifest_file,
        client=client,
    )

    # Verify return value
    assert manifest["docket_id"] == docket_id
    assert manifest["total_comments_fetched"] == 5
    assert manifest["total_comments_written"] == 5
    assert manifest["max_comments_per_day"] == 10
    assert manifest["start_date"] == "2017-08-21"
    assert manifest["end_date"] == "2017-08-22"
    assert len(manifest["strata"]) == 2

    # Check manifest file content
    assert Path(manifest_file).exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["total_comments_fetched"] == 5
    assert loaded["strata"][0]["comments_fetched"] == 3
    assert loaded["strata"][1]["comments_fetched"] == 2

    # Check that rows were written to Delta table
    assert DeltaTable.is_deltatable(bronze)
    rows = _delta_rows(bronze)
    assert len(rows) == 5
    assert {r["comment_id"] for r in rows} == {"f0", "f1", "f2", "g0", "g1"}
    assert {r["source"] for r in rows} == {"ecfs"}
