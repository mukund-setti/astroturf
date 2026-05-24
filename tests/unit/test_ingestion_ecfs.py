"""Unit tests for the ECFS source: client + filing mapper + ingestion loop."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable

import pytest
from deltalake import DeltaTable
from tenacity import wait_none

from agents.ingestion.sources.ecfs import (
    ECFSClient,
    ECFSClientConfig,
    ECFSOffsetCeilingError,
    ECFSRetryableError,
    filing_to_raw_comment,
    run_ecfs_ingestion,
)


# ---------- fixtures ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity wait zero so retry tests are fast."""
    monkeypatch.setattr(ECFSClient._fetch_page.retry, "wait", wait_none())


# ---------- fake HTTP --------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_body: Any = None,
        *,
        text: str = "",
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeECFSHttp:
    def __init__(
        self, responder: Callable[[str, dict[str, Any]], _FakeResponse]
    ) -> None:
        self._responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        return self._responder(url, params)


# ---------- helpers ----------------------------------------------------------


def _filing(
    *,
    id_sub: str,
    docket_name: str = "17-108",
    text: str | None = "I oppose this proposal.",
    express: int = 1,
    proceedings_extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    proceedings = [
        {
            "id_proceeding": "301759",
            "name": docket_name,
            "bureau_code": "WC",
            "description": "Restoring Internet Freedom",
        }
    ]
    if proceedings_extra:
        proceedings.extend(proceedings_extra)
    return {
        "id_submission": id_sub,
        "submissiontype": {
            "description": "COMMENT",
            "short": "COMMENT",
            "id": 7,
            "abbreviation": "CO",
        },
        "express_comment": express,
        "exparte_or_late_filed": "N",
        "date_received": "2017-08-28T13:00:06.000Z",
        "date_submission": "2017-08-27T00:58:00.364Z",
        "date_disseminated": "2017-08-28T15:00:02.000Z",
        "proceedings": proceedings,
        "filers": [{"name": "Test Filer"}],
        "authors": [],
        "lawfirms": [],
        "documents": [],
        "attachments": [],
        "text_data": text,
        "_index": "filings.2017.8",
        "@timestamp": "2021-12-17T23:03:36.456Z",
        "@version": "1",
    }


def _delta_rows(path: str) -> list[dict[str, Any]]:
    return DeltaTable(path).to_pyarrow_table().to_pylist()


# ---------- mapper -----------------------------------------------------------


class TestFilingToRawComment:
    def test_basic_mapping_sets_source_and_ecfs_fields(self) -> None:
        filing = _filing(id_sub="ABC123")
        now = datetime.now(timezone.utc)
        row = filing_to_raw_comment(filing, docket_id="17-108", now=now)

        assert row.comment_id == "ABC123"
        assert row.docket_id == "17-108"
        assert row.source == "ecfs"
        assert row.agency_id == "FCC"
        assert row.document_type == "COMMENT"
        assert row.comment_text == "I oppose this proposal."
        assert row.submitter_name == "Test Filer"
        assert row.ecfs_proceeding_id == "301759"
        assert row.ecfs_submission_type_id == 7
        assert row.ecfs_express_comment is True
        assert row.has_attachments is False
        # Title is not carried for ECFS rows
        assert row.title is None

    def test_multi_filer_join_semicolon(self) -> None:
        filing = _filing(id_sub="X")
        filing["filers"] = [
            {"name": "Alice"},
            {"name": ""},
            {"name": "Bob"},
            {"foo": "no name key"},
            {"name": None},
        ]
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.submitter_name == "Alice; Bob"

    def test_empty_filers_yields_none_submitter(self) -> None:
        filing = _filing(id_sub="X")
        filing["filers"] = []
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.submitter_name is None

    def test_attributes_json_strips_es_metadata(self) -> None:
        filing = _filing(id_sub="X")
        now = datetime.now(timezone.utc)
        row = filing_to_raw_comment(filing, docket_id="17-108", now=now)
        import json

        attrs = json.loads(row.attributes_json)
        assert "_index" not in attrs
        assert "@timestamp" not in attrs
        assert "@version" not in attrs
        # Real fields survive
        assert attrs["id_submission"] == "X"
        assert attrs["text_data"] == "I oppose this proposal."

    def test_docket_id_pinned_to_queried_not_first(self) -> None:
        filing = _filing(
            id_sub="X",
            proceedings_extra=[
                {"id_proceeding": "999", "name": "23-456", "bureau_code": "CG"},
            ],
        )
        # Query the secondary proceeding
        row = filing_to_raw_comment(
            filing, docket_id="23-456", now=datetime.now(timezone.utc)
        )
        assert row.docket_id == "23-456"
        assert row.ecfs_proceeding_id == "999"

    def test_express_comment_false_when_zero(self) -> None:
        filing = _filing(id_sub="X", express=0)
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.ecfs_express_comment is False

    def test_has_attachments_true_when_documents_present(self) -> None:
        filing = _filing(id_sub="X")
        filing["documents"] = [{"filename": "a.pdf", "src": "http://x"}]
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.has_attachments is True

    def test_handles_eastern_offset_date(self) -> None:
        filing = _filing(id_sub="X")
        filing["date_received"] = "2017-05-12T04:00:00.000-04:00"
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.received_date is not None
        # 04:00-04:00 == 08:00Z
        assert row.received_date.tzinfo is not None
        assert row.received_date.astimezone(timezone.utc).hour == 8

    def test_handles_seconds_only_date(self) -> None:
        filing = _filing(id_sub="X")
        filing["date_received"] = "2017-04-27T13:20:07"
        row = filing_to_raw_comment(
            filing, docket_id="17-108", now=datetime.now(timezone.utc)
        )
        assert row.received_date is not None
        assert row.received_date.tzinfo == timezone.utc


# ---------- client -----------------------------------------------------------


class TestECFSClientFetchFilings:
    def _make_client(self, responder) -> tuple[ECFSClient, FakeECFSHttp]:
        http = FakeECFSHttp(responder)
        client = ECFSClient(
            ECFSClientConfig(api_key="test-key", page_size=3, rate_limit_qps=0),
            http_client=http,
        )
        return client, http

    def test_passes_api_key_and_docket(self) -> None:
        def responder(url, params):
            assert url == "/filings"
            assert params["api_key"] == "test-key"
            assert params["proceedings.name"] == "17-108"
            assert params["limit"] == 3
            assert params["offset"] == 0
            return _FakeResponse(200, {"filing": []})

        client, http = self._make_client(responder)
        list(client.fetch_filings(docket="17-108"))
        assert len(http.calls) == 1

    def test_date_filter_becomes_lucene_q(self) -> None:
        def responder(url, params):
            assert "q" in params
            assert "date_received:[" in params["q"]
            assert "2017-08-28" in params["q"]
            assert "2017-08-30" in params["q"]
            return _FakeResponse(200, {"filing": []})

        client, _ = self._make_client(responder)
        list(
            client.fetch_filings(
                docket="17-108",
                start_date=date(2017, 8, 28),
                end_date=date(2017, 8, 30),
            )
        )

    def test_paginates_until_short_page(self) -> None:
        pages = [
            {"filing": [_filing(id_sub=f"a{i}") for i in range(3)]},
            {"filing": [_filing(id_sub=f"b{i}") for i in range(3)]},
            {"filing": [_filing(id_sub="c0")]},  # short page -> stop
        ]
        call_idx = {"n": 0}

        def responder(url, params):
            idx = call_idx["n"]
            call_idx["n"] += 1
            assert params["offset"] == idx * 3
            return _FakeResponse(200, pages[idx])

        client, _ = self._make_client(responder)
        filings = list(client.fetch_filings(docket="17-108"))
        assert len(filings) == 7

    def test_retries_429_then_succeeds(self) -> None:
        counter = {"n": 0}

        def responder(url, params):
            counter["n"] += 1
            if counter["n"] == 1:
                return _FakeResponse(429)
            return _FakeResponse(200, {"filing": []})

        client, _ = self._make_client(responder)
        list(client.fetch_filings(docket="17-108"))
        assert counter["n"] == 2

    def test_raises_on_persistent_5xx(self) -> None:
        def responder(url, params):
            return _FakeResponse(503)

        client, _ = self._make_client(responder)
        with pytest.raises(ECFSRetryableError):
            list(client.fetch_filings(docket="17-108"))

    def test_offset_ceiling_raises_on_text_body(self) -> None:
        """Simulate the 200-with-error-string body that signals the 9999 ceiling."""

        def responder(url, params):
            return _FakeResponse(
                200,
                json_body=None,
                text="Parameters incorrectly formatted...",
                content_type="text/plain; charset=utf-8",
            )

        client, _ = self._make_client(responder)
        with pytest.raises(ECFSOffsetCeilingError):
            list(client.fetch_filings(docket="17-108"))

    def test_offset_ceiling_pre_check_blocks_walk(self) -> None:
        """Once offset would exceed MAX_SAFE_OFFSET, raise before the next call."""
        # 4000 records per page, 3 pages would hit offset 12000
        big_page = {"filing": [_filing(id_sub=f"x{i}") for i in range(4000)]}

        def responder(url, params):
            return _FakeResponse(200, big_page)

        http = FakeECFSHttp(responder)
        client = ECFSClient(
            ECFSClientConfig(api_key="k", page_size=4000, rate_limit_qps=0),
            http_client=http,
        )
        with pytest.raises(ECFSOffsetCeilingError):
            list(client.fetch_filings(docket="17-108"))

    def test_max_pages_stops_walk(self) -> None:
        page = {"filing": [_filing(id_sub=f"x{i}") for i in range(3)]}

        def responder(url, params):
            return _FakeResponse(200, page)

        client, http = self._make_client(responder)
        list(client.fetch_filings(docket="17-108", max_pages=2))
        assert len(http.calls) == 2


# ---------- ingestion loop ---------------------------------------------------


class TestRunECFSIngestion:
    def test_writes_rows_with_source_ecfs(self, tmp_path) -> None:
        page1 = {"filing": [_filing(id_sub=f"f{i}") for i in range(3)]}
        page2 = {"filing": [_filing(id_sub=f"g{i}") for i in range(1)]}
        pages = iter([page1, page2])

        def responder(url, params):
            return _FakeResponse(200, next(pages))

        http = FakeECFSHttp(responder)
        client = ECFSClient(
            ECFSClientConfig(api_key="k", page_size=3, rate_limit_qps=0),
            http_client=http,
        )
        bronze = str(tmp_path / "raw_comments")

        metrics = run_ecfs_ingestion(
            docket_id="17-108", bronze_path=bronze, client=client, batch_size=2
        )
        rows = _delta_rows(bronze)
        assert metrics["comments_fetched"] == 4
        assert metrics["comments_written"] == 4
        assert len(rows) == 4
        assert {r["source"] for r in rows} == {"ecfs"}
        assert {r["docket_id"] for r in rows} == {"17-108"}
        assert {r["agency_id"] for r in rows} == {"FCC"}

    def test_idempotent_rerun_yields_zero_new_rows(self, tmp_path) -> None:
        page = {"filing": [_filing(id_sub=f"f{i}") for i in range(3)]}

        def responder(url, params):
            return _FakeResponse(200, page)

        def fresh_client():
            http = FakeECFSHttp(lambda u, p: _FakeResponse(200, page))
            return ECFSClient(
                ECFSClientConfig(api_key="k", page_size=100, rate_limit_qps=0),
                http_client=http,
            )

        bronze = str(tmp_path / "raw_comments")
        run_ecfs_ingestion(
            docket_id="17-108",
            bronze_path=bronze,
            client=fresh_client(),
            max_comments=3,
        )
        run_ecfs_ingestion(
            docket_id="17-108",
            bronze_path=bronze,
            client=fresh_client(),
            max_comments=3,
        )
        rows = _delta_rows(bronze)
        assert len(rows) == 3

    def test_max_comments_stops_early(self, tmp_path) -> None:
        page = {"filing": [_filing(id_sub=f"f{i}") for i in range(10)]}

        def responder(url, params):
            return _FakeResponse(200, page)

        http = FakeECFSHttp(responder)
        client = ECFSClient(
            ECFSClientConfig(api_key="k", page_size=10, rate_limit_qps=0),
            http_client=http,
        )
        bronze = str(tmp_path / "raw_comments")
        metrics = run_ecfs_ingestion(
            docket_id="17-108",
            bronze_path=bronze,
            client=client,
            max_comments=4,
            batch_size=2,
        )
        assert metrics["comments_fetched"] == 4
        assert len(_delta_rows(bronze)) == 4


# ---------- IngestionAgent dispatch ------------------------------------------


class TestIngestionAgentSourceRouting:
    def test_source_ecfs_routes_to_ecfs_client(self, tmp_path) -> None:
        """IngestionInput(source='ecfs') uses the injected ECFSClient, not the regulations.gov HTTP path."""
        from agents.ingestion.agent import IngestionAgent, IngestionInput

        page = {"filing": [_filing(id_sub="X1"), _filing(id_sub="X2")]}

        def responder(url, params):
            return _FakeResponse(200, page)

        http = FakeECFSHttp(responder)
        client = ECFSClient(
            ECFSClientConfig(api_key="k", page_size=10, rate_limit_qps=0),
            http_client=http,
        )

        bronze = str(tmp_path / "raw_comments")
        agent = IngestionAgent(config={"bronze_path": bronze, "ecfs_client": client})
        out = agent.run(
            IngestionInput(docket_id="17-108", source="ecfs", max_comments=2)
        )

        assert out.rows_written == 2
        rows = _delta_rows(bronze)
        assert {r["source"] for r in rows} == {"ecfs"}
        assert len(http.calls) == 1  # single page request

    def test_default_source_is_regulations_gov(self) -> None:
        from agents.ingestion.agent import IngestionInput

        inputs = IngestionInput(docket_id="EPA-X")
        assert inputs.source == "regulations_gov"
