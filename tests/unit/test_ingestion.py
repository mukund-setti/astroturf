"""Unit tests for IngestionAgent — HTTP layer faked, real delta-rs writes to tmp_path."""
from __future__ import annotations

from typing import Any, Callable

import pytest
from deltalake import DeltaTable
from tenacity import wait_none

from agents.ingestion import agent as ingestion_agent
from agents.ingestion.agent import (
    MAX_PAGES_PER_REQUEST,
    CursorStalledError,
    IngestionAgent,
    IngestionInput,
    _RetryableHTTPError,
)


# ---------- fixtures ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity wait zero so retry tests are fast."""
    monkeypatch.setattr(ingestion_agent._fetch_page.retry, "wait", wait_none())


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Direct MLflow writes to a tmp dir so tests don't litter ./mlruns."""
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests")


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGULATIONS_GOV_API_KEY", "test-key")


# ---------- fake HTTP ---------------------------------------------------------


class _ScriptedResponse:
    def __init__(self, status_code: int, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_body or {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(self.status_code),
            )


class FakeHttpClient:
    """Records calls and dispatches to a responder ``(url, params) -> _ScriptedResponse``."""

    def __init__(self, responder: Callable[[str, dict[str, Any]], _ScriptedResponse]) -> None:
        self._responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> _ScriptedResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        return self._responder(url, params)


# ---------- helpers -----------------------------------------------------------


def _comment(idx: int, docket_id: str, lmd: str) -> dict[str, Any]:
    return {
        "id": f"{docket_id}-c{idx:06d}",
        "type": "comments",
        "attributes": {
            "title": f"Comment {idx}",
            "documentType": "PublicSubmission",
            "lastModifiedDate": lmd,
            "postedDate": lmd,
            "receivedDate": lmd,
            "comment": f"Body of comment {idx}.",
            "agencyId": "EPA",
            "hasAttachments": False,
        },
    }


def _page(records: list[dict[str, Any]], has_next: bool) -> dict[str, Any]:
    links = (
        {"next": "https://api.regulations.gov/v4/comments?page%5Bnumber%5D=N+1"}
        if has_next
        else {}
    )
    return {"data": records, "links": links, "meta": {"totalElements": len(records)}}


def _delta_rows(path: str) -> list[dict[str, Any]]:
    return DeltaTable(path).to_pyarrow_table().to_pylist()


# ---------- tests -------------------------------------------------------------


def test_pagination_follows_links_next(tmp_path, api_key):
    docket = "EPA-A"
    page1 = _page([_comment(i, docket, "2024-01-01T00:00:00Z") for i in range(4)], has_next=True)
    page2 = _page([_comment(i, docket, "2024-01-02T00:00:00Z") for i in range(4, 7)], has_next=False)

    def responder(url, params):
        assert url == "/comments"
        assert params["filter[docketId]"] == docket
        assert params["page[size]"] == 250
        assert "filter[lastModifiedDate][ge]" not in params
        return _ScriptedResponse(200, page1 if params["page[number]"] == 1 else page2)

    client = FakeHttpClient(responder)
    agent = IngestionAgent(
        config={"bronze_path": str(tmp_path / "raw_comments")}, http_client=client
    )
    out = agent.run(IngestionInput(docket_id=docket))

    assert len(client.calls) == 2
    assert out.metadata["api_calls_made"] == 2
    assert out.rows_written == 7
    assert len(_delta_rows(str(tmp_path / "raw_comments"))) == 7


def test_retry_on_429_then_success(tmp_path, api_key):
    docket = "EPA-RETRY"
    page = _page([_comment(0, docket, "2024-01-01T00:00:00Z")], has_next=False)
    counter = {"n": 0}

    def responder(url, params):
        counter["n"] += 1
        if counter["n"] == 1:
            return _ScriptedResponse(429)
        return _ScriptedResponse(200, page)

    client = FakeHttpClient(responder)
    agent = IngestionAgent(
        config={"bronze_path": str(tmp_path / "raw_comments")}, http_client=client
    )
    out = agent.run(IngestionInput(docket_id=docket))

    assert counter["n"] == 2
    assert out.rows_written == 1


def test_raises_on_persistent_5xx(tmp_path, api_key):
    docket = "EPA-500"

    def responder(url, params):
        return _ScriptedResponse(503)

    client = FakeHttpClient(responder)
    agent = IngestionAgent(
        config={"bronze_path": str(tmp_path / "raw_comments")}, http_client=client
    )

    with pytest.raises(_RetryableHTTPError):
        agent.run(IngestionInput(docket_id=docket))
    # 5 attempts per tenacity config.
    assert len(client.calls) == 5


def test_idempotent_merge(tmp_path, api_key):
    docket = "EPA-IDEM"
    page = _page([_comment(i, docket, "2024-01-01T00:00:00Z") for i in range(3)], has_next=False)

    def responder(url, params):
        return _ScriptedResponse(200, page)

    path = str(tmp_path / "raw_comments")
    IngestionAgent(config={"bronze_path": path}, http_client=FakeHttpClient(responder)).run(
        IngestionInput(docket_id=docket)
    )
    IngestionAgent(config={"bronze_path": path}, http_client=FakeHttpClient(responder)).run(
        IngestionInput(docket_id=docket)
    )

    rows = _delta_rows(path)
    assert len(rows) == 3
    assert len({r["comment_id"] for r in rows}) == 3


def test_date_window_splitting_recovers_all_rows_above_5000(tmp_path, api_key):
    """Docket of 5500 comments forces a second cursor advance past the 5000 cap."""
    docket = "EPA-BIG"

    # Batch 1: 5000 comments, spread one page (250) per lastModifiedDate so cursor can advance.
    # Pages 1..20, lastModifiedDate 2024-01-01..2024-01-20.
    batch1_pages: list[dict[str, Any]] = []
    for page_idx in range(MAX_PAGES_PER_REQUEST):
        lmd = f"2024-01-{page_idx + 1:02d}T00:00:00Z"
        records = [_comment(page_idx * 250 + j, docket, lmd) for j in range(250)]
        # Every page in batch 1 has links.next — the API would still report more on page 20.
        batch1_pages.append(_page(records, has_next=True))
    cursor_after_batch1 = f"2024-01-{MAX_PAGES_PER_REQUEST:02d}T00:00:00Z"

    # Batch 2: 500 more comments past the cursor, across 2 pages.
    batch2_p1 = _page(
        [_comment(5000 + i, docket, "2024-02-01T00:00:00Z") for i in range(250)],
        has_next=True,
    )
    batch2_p2 = _page(
        [_comment(5250 + i, docket, "2024-02-01T00:00:00Z") for i in range(250)],
        has_next=False,
    )

    def responder(url, params):
        page_num = params["page[number]"]
        cursor = params.get("filter[lastModifiedDate][ge]")
        if cursor is None:
            assert 1 <= page_num <= MAX_PAGES_PER_REQUEST
            return _ScriptedResponse(200, batch1_pages[page_num - 1])
        assert cursor == cursor_after_batch1, f"unexpected cursor {cursor!r}"
        if page_num == 1:
            return _ScriptedResponse(200, batch2_p1)
        if page_num == 2:
            return _ScriptedResponse(200, batch2_p2)
        raise AssertionError(f"unexpected page {page_num}")

    path = str(tmp_path / "raw_comments")
    client = FakeHttpClient(responder)
    out = IngestionAgent(config={"bronze_path": path}, http_client=client).run(
        IngestionInput(docket_id=docket)
    )

    rows = _delta_rows(path)
    unique_ids = {r["comment_id"] for r in rows}
    assert len(unique_ids) == 5500
    assert len(rows) == 5500  # no duplicates at the cursor boundary
    assert out.metadata["api_calls_made"] == MAX_PAGES_PER_REQUEST + 2  # 20 + 2 = 22


def test_cursor_stalled_raises_with_actionable_message(tmp_path, api_key):
    """All 5000 records share one lastModifiedDate — cursor can't advance, agent must raise."""
    docket = "EPA-STALL"
    stuck_lmd = "2024-03-15T12:00:00Z"
    pages = [
        _page(
            [_comment(page_idx * 250 + j, docket, stuck_lmd) for j in range(250)],
            has_next=True,
        )
        for page_idx in range(MAX_PAGES_PER_REQUEST)
    ]

    def responder(url, params):
        return _ScriptedResponse(200, pages[params["page[number]"] - 1])

    client = FakeHttpClient(responder)
    agent = IngestionAgent(
        config={"bronze_path": str(tmp_path / "raw_comments")}, http_client=client
    )

    with pytest.raises(CursorStalledError) as exc_info:
        agent.run(IngestionInput(docket_id=docket))

    msg = str(exc_info.value)
    assert docket in msg
    assert stuck_lmd in msg
    assert "5000" in msg  # records seen so far
    assert "documentId" in msg or "narrow" in msg  # resolution hint
