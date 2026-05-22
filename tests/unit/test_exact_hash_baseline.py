"""Unit tests for the exact normalized-text-hash baseline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable

from scripts.run_exact_hash_baseline import (
    EXACT_HASH_CLUSTERING_VERSION,
    EXACT_HASH_EMBEDDING_MODEL,
    ExactHashBaselineAgent,
    ExactHashBaselineInput,
    _cluster_id,
)
from shared.delta_utils.silver import merge_parsed_comments
from shared.schemas.parsed_comments import ParsedComment, parsed_comment_arrow_schema


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-exact-hash-baseline")


def _parsed_to_arrow(rows: list[ParsedComment]) -> pa.Table:
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
    text_hash: str | None,
    docket_id: str = "DOCKET-HASH",
    text_source: str = "detail_comment_text",
    normalized_text: str | None = None,
) -> ParsedComment:
    return ParsedComment(
        comment_id=comment_id,
        docket_id=docket_id,
        title=None,
        posted_date=None,
        last_modified_date=None,
        received_date=None,
        source_system_version="test",
        parser_version="test",
        text_source=text_source,
        raw_text=normalized_text,
        normalized_text=normalized_text,
        normalized_text_hash=text_hash,
        token_estimate=0,
        char_count=len(normalized_text or ""),
        has_attachments=False,
        attachment_count=0,
        parse_status="parsed",
        parse_error=None,
        parsed_at=datetime.now(timezone.utc),
    )


def _seed_parsed(path: Path, rows: list[ParsedComment]) -> None:
    merge_parsed_comments(path, _parsed_to_arrow(rows))


def _read(path: Path) -> list[dict[str, Any]]:
    if not DeltaTable.is_deltatable(str(path)):
        return []
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def _run(
    tmp_path: Path,
    *,
    docket_id: str = "DOCKET-HASH",
    min_cluster_size: int = 2,
) -> tuple[Any, Path, Path]:
    parsed_path = tmp_path / "parsed"
    clusters_path = tmp_path / "clusters"
    memberships_path = tmp_path / "memberships"
    output = ExactHashBaselineAgent().run(
        ExactHashBaselineInput(
            docket_id=docket_id,
            parsed_path=str(parsed_path),
            clusters_path=str(clusters_path),
            memberships_path=str(memberships_path),
            min_cluster_size=min_cluster_size,
        )
    )
    return output, clusters_path, memberships_path


def test_groups_exact_duplicates_into_clusters(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
            _make_parsed(comment_id="b1", text_hash="hash-b"),
            _make_parsed(comment_id="b2", text_hash="hash-b"),
            _make_parsed(comment_id="b3", text_hash="hash-b"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path)

    clusters = sorted(_read(clusters_path), key=lambda row: row["cluster_size"])
    memberships = _read(memberships_path)
    assert output.metadata["clusters_written"] == 2
    assert output.metadata["memberships_written"] == 5
    assert [row["cluster_size"] for row in clusters] == [2, 3]
    assert {row["embedding_model"] for row in clusters} == {EXACT_HASH_EMBEDDING_MODEL}
    assert {row["clustering_version"] for row in clusters} == {
        EXACT_HASH_CLUSTERING_VERSION
    }
    assert {row["similarity_to_representative"] for row in memberships} == {1.0}


def test_ignores_singleton_hashes(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
            _make_parsed(comment_id="solo", text_hash="hash-solo"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path)

    assert output.metadata["candidate_count"] == 3
    assert output.metadata["clusters_written"] == 1
    assert sorted(row["comment_id"] for row in _read(memberships_path)) == ["a1", "a2"]
    assert _read(clusters_path)[0]["candidate_count"] == 3


def test_respects_docket_filter(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
            _make_parsed(
                comment_id="other1", docket_id="OTHER-DOCKET", text_hash="hash-a"
            ),
            _make_parsed(
                comment_id="other2", docket_id="OTHER-DOCKET", text_hash="hash-a"
            ),
        ],
    )

    output, _, memberships_path = _run(tmp_path)

    assert output.metadata["candidate_count"] == 2
    assert sorted(row["comment_id"] for row in _read(memberships_path)) == ["a1", "a2"]


def test_respects_min_cluster_size(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
            _make_parsed(comment_id="b1", text_hash="hash-b"),
            _make_parsed(comment_id="b2", text_hash="hash-b"),
            _make_parsed(comment_id="b3", text_hash="hash-b"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path, min_cluster_size=3)

    assert output.metadata["clusters_written"] == 1
    assert _read(clusters_path)[0]["cluster_size"] == 3
    assert sorted(row["comment_id"] for row in _read(memberships_path)) == [
        "b1",
        "b2",
        "b3",
    ]


def test_idempotent_rerun_does_not_duplicate_rows(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
        ],
    )

    first, clusters_path, memberships_path = _run(tmp_path)
    second, _, _ = _run(tmp_path)

    assert first.metadata["clusters_written"] == 1
    assert second.metadata["deleted_clusters"] == 1
    assert second.metadata["deleted_memberships"] == 2
    assert len(_read(clusters_path)) == 1
    assert len(_read(memberships_path)) == 2


def test_produces_deterministic_cluster_ids(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="b", text_hash="hash-a"),
            _make_parsed(comment_id="a", text_hash="hash-a"),
        ],
    )

    _, clusters_path, _ = _run(tmp_path)

    expected = _cluster_id("DOCKET-HASH", "hash-a", ["a", "b"])
    assert _read(clusters_path)[0]["cluster_id"] == expected


def test_handles_missing_normalized_text_hash_gracefully(tmp_path: Path) -> None:
    parsed_path = tmp_path / "parsed"
    _seed_parsed(
        parsed_path,
        [
            _make_parsed(comment_id="missing", text_hash=None),
            _make_parsed(comment_id="empty", text_hash=""),
            _make_parsed(comment_id="a1", text_hash="hash-a"),
            _make_parsed(comment_id="a2", text_hash="hash-a"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path)

    assert output.metadata["rows_total_for_docket_source"] == 4
    assert output.metadata["rows_missing_normalized_text_hash"] == 2
    assert output.metadata["candidate_count"] == 2
    assert len(_read(clusters_path)) == 1
    assert sorted(row["comment_id"] for row in _read(memberships_path)) == ["a1", "a2"]
