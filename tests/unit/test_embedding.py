"""Unit tests for EmbeddingAgent — real delta-rs writes, MockBackend only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest
from deltalake import DeltaTable

from agents.embedding.agent import (
    EmbeddingAgent,
    EmbeddingInput,
    MockBackend,
)
from shared.delta_utils.silver import merge_parsed_comments
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
)


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Direct MLflow writes to a tmp dir so tests don't litter ./mlruns."""
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-embedding")


def _parsed_rows_to_arrow(rows: list[ParsedComment]) -> pa.Table:
    schema = parsed_comment_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _make_parsed(
    *,
    comment_id: str,
    docket_id: str = "DOCKET-EMB",
    text_source: str = "detail_comment_text",
    parse_status: str = "parsed",
    raw_text: str | None = "The rule will harm small businesses.",
    normalized_text_hash: str | None = "hash-1",
    char_count: int = 40,
) -> ParsedComment:
    now = datetime.now(timezone.utc)
    return ParsedComment(
        comment_id=comment_id,
        docket_id=docket_id,
        title="Mock title",
        posted_date=now,
        last_modified_date=now,
        received_date=now,
        source_system_version="regulations.gov_v4",
        parser_version="v2A",
        text_source=text_source,
        raw_text=raw_text,
        normalized_text=raw_text.lower() if raw_text else None,
        normalized_text_hash=normalized_text_hash,
        token_estimate=max(1, char_count // 4),
        char_count=char_count,
        has_attachments=False,
        attachment_count=0,
        parse_status=parse_status,
        parse_error=None,
        parsed_at=now,
    )


def _seed_parsed(path: Path, rows: list[ParsedComment]) -> None:
    merge_parsed_comments(path, _parsed_rows_to_arrow(rows))


def _read_embeddings(path: Path) -> list[dict[str, Any]]:
    if not DeltaTable.is_deltatable(str(path)):
        return []
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def test_filter_selects_only_substantive_text_sources(tmp_path: Path) -> None:
    """All 5 text_source values seeded; only detail_comment_text + comment_text get embedded."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    rows = [
        _make_parsed(
            comment_id="c-detail",
            text_source="detail_comment_text",
            normalized_text_hash="h-detail",
        ),
        _make_parsed(
            comment_id="c-bronze",
            text_source="comment_text",
            normalized_text_hash="h-bronze",
        ),
        _make_parsed(
            comment_id="c-cover",
            text_source="detail_cover_note",
            normalized_text_hash="h-cover",
            raw_text="see attached",
            char_count=12,
        ),
        _make_parsed(
            comment_id="c-title",
            text_source="title_only",
            parse_status="title_only",
            normalized_text_hash="h-title",
            raw_text="A title",
            char_count=7,
        ),
        _make_parsed(
            comment_id="c-missing",
            text_source="missing",
            parse_status="missing_text",
            normalized_text_hash=None,
            raw_text=None,
            char_count=0,
        ),
    ]
    _seed_parsed(parsed_path, rows)

    agent = EmbeddingAgent(backend=MockBackend(dimension=8))
    output = agent.run(
        EmbeddingInput(
            docket_id="DOCKET-EMB",
            parsed_path=str(parsed_path),
            embeddings_path=str(embeddings_path),
        )
    )

    assert output.metadata["candidates_total"] == 2
    assert output.metadata["embedded_count"] == 2
    assert output.rows_written == 2

    embedded_ids = sorted(r["comment_id"] for r in _read_embeddings(embeddings_path))
    assert embedded_ids == ["c-bronze", "c-detail"]


def test_first_run_embeds_all_candidates(tmp_path: Path) -> None:
    """Empty embeddings table -> all candidates embedded with unit-norm vectors."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    rows = [
        _make_parsed(
            comment_id=f"c-{i}",
            raw_text=f"Comment number {i}",
            normalized_text_hash=f"h-{i}",
        )
        for i in range(5)
    ]
    _seed_parsed(parsed_path, rows)

    agent = EmbeddingAgent(backend=MockBackend(dimension=16))
    output = agent.run(
        EmbeddingInput(
            docket_id="DOCKET-EMB",
            parsed_path=str(parsed_path),
            embeddings_path=str(embeddings_path),
            batch_size=2,
        )
    )

    assert output.metadata["embedded_count"] == 5
    assert output.metadata["new_count"] == 5
    assert output.metadata["stale_reembedded_count"] == 0
    assert output.rows_written == 5

    embedded = _read_embeddings(embeddings_path)
    assert len(embedded) == 5
    for row in embedded:
        assert len(row["embedding_vector"]) == 16
        assert row["embedding_dim"] == 16
        assert row["backend"] == "mock"
        assert row["embedding_model"] == "mock-bge-large"
        norm = float(
            np.linalg.norm(np.array(row["embedding_vector"], dtype=np.float32))
        )
        assert abs(norm - 1.0) < 1e-5


def test_rerun_is_idempotent_when_text_unchanged(tmp_path: Path) -> None:
    """Second run produces 0 new embeddings — every candidate is a cache hit."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    rows = [
        _make_parsed(comment_id="c-1", normalized_text_hash="h-1"),
        _make_parsed(comment_id="c-2", normalized_text_hash="h-2"),
    ]
    _seed_parsed(parsed_path, rows)

    agent = EmbeddingAgent(backend=MockBackend(dimension=8))
    inputs = EmbeddingInput(
        docket_id="DOCKET-EMB",
        parsed_path=str(parsed_path),
        embeddings_path=str(embeddings_path),
    )

    first = agent.run(inputs)
    assert first.metadata["embedded_count"] == 2

    second = agent.run(inputs)
    assert second.metadata["embedded_count"] == 0
    assert second.metadata["skipped_cache_hit"] == 2
    assert second.rows_written == 0

    assert len(_read_embeddings(embeddings_path)) == 2


def test_rerun_reembeds_when_normalized_text_hash_changes(tmp_path: Path) -> None:
    """Bump hash on one row -> exactly 1 re-embed, MERGE updates in place."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="c-1", normalized_text_hash="h-1"),
            _make_parsed(comment_id="c-2", normalized_text_hash="h-2"),
        ],
    )

    agent = EmbeddingAgent(backend=MockBackend(dimension=8))
    inputs = EmbeddingInput(
        docket_id="DOCKET-EMB",
        parsed_path=str(parsed_path),
        embeddings_path=str(embeddings_path),
    )

    agent.run(inputs)
    assert len(_read_embeddings(embeddings_path)) == 2

    # Update c-1's text + hash; leave c-2 untouched.
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(
                comment_id="c-1",
                raw_text="Different content entirely.",
                normalized_text_hash="h-1-NEW",
            ),
        ],
    )

    second = agent.run(inputs)
    assert second.metadata["embedded_count"] == 1
    assert second.metadata["stale_reembedded_count"] == 1
    assert second.metadata["new_count"] == 0
    assert second.metadata["skipped_cache_hit"] == 1

    rows = _read_embeddings(embeddings_path)
    assert len(rows) == 2  # MERGE updated in place, no new row inserted
    by_id = {r["comment_id"]: r for r in rows}
    assert by_id["c-1"]["text_hash"] == "h-1-NEW"
    assert by_id["c-2"]["text_hash"] == "h-2"


def test_compound_pk_allows_two_models_for_same_comment(tmp_path: Path) -> None:
    """Embedding with model A then model B yields 2 rows per comment, both retained."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    _seed_parsed(
        parsed_path, [_make_parsed(comment_id="c-1", normalized_text_hash="h-1")]
    )

    EmbeddingAgent(backend=MockBackend(model_name="mock-A", dimension=8)).run(
        EmbeddingInput(
            docket_id="DOCKET-EMB",
            parsed_path=str(parsed_path),
            embeddings_path=str(embeddings_path),
        )
    )
    EmbeddingAgent(backend=MockBackend(model_name="mock-B", dimension=16)).run(
        EmbeddingInput(
            docket_id="DOCKET-EMB",
            parsed_path=str(parsed_path),
            embeddings_path=str(embeddings_path),
        )
    )

    rows = _read_embeddings(embeddings_path)
    assert len(rows) == 2
    by_model = {r["embedding_model"]: r for r in rows}
    assert set(by_model) == {"mock-A", "mock-B"}
    assert by_model["mock-A"]["embedding_dim"] == 8
    assert by_model["mock-B"]["embedding_dim"] == 16
    assert len(by_model["mock-A"]["embedding_vector"]) == 8
    assert len(by_model["mock-B"]["embedding_vector"]) == 16


def test_deterministic_mock_is_reproducible() -> None:
    """Same text -> identical vector across two backend instances (ADR-0005)."""
    backend_a = MockBackend(dimension=32)
    backend_b = MockBackend(dimension=32)

    text = "We strongly oppose this rule."
    [vec_a] = backend_a.encode([text])
    [vec_b] = backend_b.encode([text])

    assert vec_a == vec_b
    assert len(vec_a) == 32
    norm = float(np.linalg.norm(np.array(vec_a, dtype=np.float32)))
    assert abs(norm - 1.0) < 1e-5

    [other] = backend_a.encode(["Completely different text."])
    assert other != vec_a


def test_dimension_is_not_hardcoded(tmp_path: Path) -> None:
    """MockBackend(dimension=N) flows through to schema rows; no 1024 leak."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    _seed_parsed(
        parsed_path, [_make_parsed(comment_id="c-1", normalized_text_hash="h-1")]
    )

    agent = EmbeddingAgent(backend=MockBackend(dimension=7))
    agent.run(
        EmbeddingInput(
            docket_id="DOCKET-EMB",
            parsed_path=str(parsed_path),
            embeddings_path=str(embeddings_path),
        )
    )

    rows = _read_embeddings(embeddings_path)
    assert len(rows) == 1
    assert rows[0]["embedding_dim"] == 7
    assert len(rows[0]["embedding_vector"]) == 7


def test_mock_backend_model_name_is_configurable() -> None:
    """The schema's embedding_model field stores whatever backend.model_name returns."""
    backend = MockBackend(model_name="mock-test-v1", dimension=4)
    assert backend.model_name == "mock-test-v1"
    assert backend.backend_name == "mock"
    assert backend.dimension == 4


def test_corrupt_input_skip_and_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """parse_status='parsed' but raw_text=None -> skip, log warning, no crash (ADR-0005)."""
    parsed_path = tmp_path / "parsed"
    embeddings_path = tmp_path / "embeddings"

    rows = [
        _make_parsed(
            comment_id="c-corrupt",
            text_source="detail_comment_text",
            parse_status="parsed",
            raw_text=None,
            normalized_text_hash=None,
            char_count=0,
        ),
        _make_parsed(
            comment_id="c-good",
            text_source="detail_comment_text",
            normalized_text_hash="h-good",
        ),
    ]
    _seed_parsed(parsed_path, rows)

    agent = EmbeddingAgent(backend=MockBackend(dimension=8))
    with caplog.at_level(logging.WARNING, logger="agents.embedding.agent"):
        output = agent.run(
            EmbeddingInput(
                docket_id="DOCKET-EMB",
                parsed_path=str(parsed_path),
                embeddings_path=str(embeddings_path),
            )
        )

    assert output.metadata["candidates_total"] == 2
    assert output.metadata["skipped_corrupt"] == 1
    assert output.metadata["embedded_count"] == 1
    assert output.rows_written == 1

    embedded = _read_embeddings(embeddings_path)
    assert [r["comment_id"] for r in embedded] == ["c-good"]

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("c-corrupt" in m for m in warning_messages), warning_messages
