"""Unit tests for ClusteringAgent."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest
from deltalake import DeltaTable

from agents.clustering.agent import ClusteringAgent, ClusteringInput
from shared.delta_utils.silver import merge_comment_embeddings
from shared.schemas.comment_embeddings import (
    CommentEmbedding,
    comment_embedding_arrow_schema,
)


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-clustering")


def _embeddings_to_arrow(rows: list[CommentEmbedding]) -> pa.Table:
    schema = comment_embedding_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _make_embedding(
    *,
    comment_id: str,
    vector: list[float],
    docket_id: str = "DOCKET-CLUSTER",
    embedding_model: str = "real-model",
    text_hash: str | None = None,
    text_source: str = "detail_comment_text",
    backend: str = "local_sentence_transformer",
) -> CommentEmbedding:
    return CommentEmbedding(
        comment_id=comment_id,
        docket_id=docket_id,
        embedding_model=embedding_model,
        embedding_dim=len(vector),
        text_hash=text_hash or f"hash-{comment_id}",
        text_source=text_source,
        embedding_vector=vector,
        embedded_at=datetime.now(timezone.utc),
        backend=backend,
    )


def _seed_embeddings(path: Path, rows: list[CommentEmbedding]) -> None:
    merge_comment_embeddings(path, _embeddings_to_arrow(rows))


def _read(path: Path) -> list[dict[str, Any]]:
    if not DeltaTable.is_deltatable(str(path)):
        return []
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def _run(
    tmp_path: Path,
    *,
    threshold: float = 0.92,
    max_rows: int | None = None,
    allow_mock: bool = False,
    embedding_model: str = "real-model",
) -> tuple[Any, Path, Path]:
    embeddings_path = tmp_path / "embeddings"
    clusters_path = tmp_path / "clusters"
    memberships_path = tmp_path / "memberships"
    output = ClusteringAgent().run(
        ClusteringInput(
            docket_id="DOCKET-CLUSTER",
            embedding_model=embedding_model,
            embeddings_path=str(embeddings_path),
            clusters_path=str(clusters_path),
            memberships_path=str(memberships_path),
            similarity_threshold=threshold,
            max_rows=max_rows,
            allow_mock=allow_mock,
        )
    )
    return output, clusters_path, memberships_path


def test_rejects_mock_embeddings_by_default(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0], backend="mock"),
            _make_embedding(comment_id="b", vector=[0.99, 0.01], backend="mock"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path)

    assert output.metadata["candidates_total"] == 2
    assert output.metadata["candidates_after_mock_filter"] == 0
    assert output.metadata["clusters_written"] == 0
    assert _read(clusters_path) == []
    assert _read(memberships_path) == []


def test_allows_mock_embeddings_for_debugging(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0], backend="mock"),
            _make_embedding(comment_id="b", vector=[0.99, 0.01], backend="mock"),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path, allow_mock=True)

    assert output.metadata["clusters_written"] == 1
    assert output.metadata["memberships_written"] == 2
    assert _read(clusters_path)[0]["embedding_backend"] == "mock"
    assert len(_read(memberships_path)) == 2


def test_connected_components_and_singletons_are_handled(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a1", vector=[1.0, 0.0]),
            _make_embedding(comment_id="a2", vector=[0.99, 0.01]),
            _make_embedding(comment_id="b1", vector=[0.0, 1.0]),
            _make_embedding(comment_id="b2", vector=[0.01, 0.99]),
            _make_embedding(comment_id="singleton", vector=[-1.0, 0.0]),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path)

    clusters = sorted(_read(clusters_path), key=lambda row: row["cluster_size"])
    memberships = _read(memberships_path)
    assert output.metadata["pair_count_evaluated"] == 10
    assert output.metadata["edge_count_above_threshold"] == 2
    assert [row["cluster_size"] for row in clusters] == [2, 2]
    assert sorted(row["comment_id"] for row in memberships) == [
        "a1",
        "a2",
        "b1",
        "b2",
    ]


def test_medoid_representative_and_membership_ranking(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="left", vector=[1.0, 0.0]),
            _make_embedding(comment_id="center", vector=[0.99, 0.01]),
            _make_embedding(comment_id="right", vector=[0.98, 0.02]),
        ],
    )

    _, clusters_path, memberships_path = _run(tmp_path, threshold=0.99)

    [cluster] = _read(clusters_path)
    memberships = _read(memberships_path)
    assert cluster["representative_comment_id"] == "center"
    rank_by_id = {row["comment_id"]: row["membership_rank"] for row in memberships}
    assert rank_by_id["center"] == 1


def test_max_rows_limits_candidates_deterministically(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0]),
            _make_embedding(comment_id="b", vector=[0.99, 0.01]),
            _make_embedding(comment_id="c", vector=[0.98, 0.02]),
        ],
    )

    output, clusters_path, memberships_path = _run(tmp_path, max_rows=2)

    assert output.metadata["rows_clustered"] == 2
    [cluster] = _read(clusters_path)
    assert cluster["candidate_count"] == 2
    assert sorted(row["comment_id"] for row in _read(memberships_path)) == ["a", "b"]


def test_scoped_replace_removes_stale_rows_on_rerun(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0]),
            _make_embedding(comment_id="b", vector=[0.99, 0.01]),
            _make_embedding(comment_id="c", vector=[0.98, 0.02]),
        ],
    )

    first, clusters_path, memberships_path = _run(tmp_path)
    first_cluster_id = _read(clusters_path)[0]["cluster_id"]
    assert first.metadata["memberships_written"] == 3

    _seed_embeddings(
        embeddings_path,
        [_make_embedding(comment_id="c", vector=[-1.0, 0.0], text_hash="hash-c-new")],
    )
    second, _, _ = _run(tmp_path)

    clusters = _read(clusters_path)
    memberships = _read(memberships_path)
    assert second.metadata["deleted_clusters"] == 1
    assert second.metadata["deleted_memberships"] == 3
    assert len(clusters) == 1
    assert clusters[0]["cluster_size"] == 2
    assert clusters[0]["cluster_id"] != first_cluster_id
    assert sorted(row["comment_id"] for row in memberships) == ["a", "b"]


def test_threshold_change_creates_separate_scope(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0]),
            _make_embedding(comment_id="b", vector=[0.99, 0.01]),
            _make_embedding(comment_id="c", vector=[0.94, 0.34]),
        ],
    )

    _run(tmp_path, threshold=0.99)
    _run(tmp_path, threshold=0.999)

    _, clusters_path, memberships_path = _run(tmp_path, threshold=0.92)
    clusters = _read(clusters_path)
    memberships = _read(memberships_path)
    thresholds = sorted({row["similarity_threshold"] for row in clusters})
    assert thresholds == [0.92, 0.99, 0.999]
    assert len(memberships) == 7


def test_run_id_changes_when_text_hash_changes(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0], text_hash="hash-a"),
            _make_embedding(comment_id="b", vector=[0.99, 0.01], text_hash="hash-b"),
        ],
    )

    first, clusters_path, _ = _run(tmp_path)
    first_run_id = _read(clusters_path)[0]["clustering_run_id"]

    _seed_embeddings(
        embeddings_path,
        [_make_embedding(comment_id="b", vector=[0.99, 0.01], text_hash="hash-b-new")],
    )
    second, _, _ = _run(tmp_path)
    second_run_id = _read(clusters_path)[0]["clustering_run_id"]

    assert first.metadata["clustering_run_id"] == first_run_id
    assert second.metadata["clustering_run_id"] == second_run_id
    assert second_run_id != first_run_id


def test_raises_on_mixed_non_mock_backends(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0], backend="local"),
            _make_embedding(comment_id="b", vector=[0.99, 0.01], backend="databricks"),
        ],
    )

    with pytest.raises(ValueError, match="single embedding backend"):
        _run(tmp_path)


def test_vectors_are_normalized_defensively(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[10.0, 0.0]),
            _make_embedding(comment_id="b", vector=[9.9, 0.1]),
        ],
    )

    output, clusters_path, _ = _run(tmp_path)

    assert output.metadata["clusters_written"] == 1
    [cluster] = _read(clusters_path)
    assert np.isclose(cluster["max_similarity"], 1.0)


def test_vector_search_clustering_path(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    candidates_list = [
        {
            "comment_id": "a",
            "embedding_vector": [1.0, 0.0],
            "docket_id": "DOCKET-CLUSTER",
            "embedding_model": "real-model",
            "embedding_dim": 2,
            "backend": "local_sentence_transformer",
            "text_hash": "hash-a",
            "text_source": "detail_comment_text",
        },
        {
            "comment_id": "b",
            "embedding_vector": [0.99, 0.01],
            "docket_id": "DOCKET-CLUSTER",
            "embedding_model": "real-model",
            "embedding_dim": 2,
            "backend": "local_sentence_transformer",
            "text_hash": "hash-b",
            "text_source": "detail_comment_text",
        },
        {
            "comment_id": "c",
            "embedding_vector": [0.0, 1.0],
            "docket_id": "DOCKET-CLUSTER",
            "embedding_model": "real-model",
            "embedding_dim": 2,
            "backend": "local_sentence_transformer",
            "text_hash": "hash-c",
            "text_source": "detail_comment_text",
        },
    ]
    # Seed embeddings table
    from shared.delta_utils.silver import merge_comment_embeddings

    rows = [
        _make_embedding(comment_id=c["comment_id"], vector=c["embedding_vector"])
        for c in candidates_list
    ]
    merge_comment_embeddings(embeddings_path, _embeddings_to_arrow(rows))

    # Mock Vector Search Client
    class MockIndex:
        def similarity_search(self, query_vector, columns, num_results):
            import numpy as np

            q = np.array(query_vector, dtype=np.float32)
            results = []
            for c in candidates_list:
                v = np.array(c["embedding_vector"], dtype=np.float32)
                sim = float(np.dot(q, v) / (np.linalg.norm(q) * np.linalg.norm(v)))
                results.append((c["comment_id"], sim))
            results.sort(key=lambda x: -x[1])
            return {
                "result": {"data_array": [[r[0], r[1]] for r in results[:num_results]]},
                "manifest": {"columns": [{"name": "comment_id"}, {"name": "score"}]},
            }

    class MockVSC:
        def get_index(self, endpoint_name, index_name):
            return MockIndex()

    # Run clustering agent in vector search mode
    clusters_path = tmp_path / "clusters"
    memberships_path = tmp_path / "memberships"
    output = ClusteringAgent().run(
        ClusteringInput(
            docket_id="DOCKET-CLUSTER",
            embedding_model="real-model",
            embeddings_path=str(embeddings_path),
            clusters_path=str(clusters_path),
            memberships_path=str(memberships_path),
            clustering_version="v1_vector_search_cosine",
            clustering_mode="vector_search",
            vector_index_name="workspace.silver.test_index",
            vector_search_client=MockVSC(),
            similarity_threshold=0.92,
        )
    )

    assert output.metadata["mode"] == "vector_search"
    assert output.metadata["pair_count_evaluated"] == 0
    assert output.metadata["comments_considered"] == 3
    assert output.metadata["clusters_found"] == 1
    assert output.metadata["coverage"] == pytest.approx(2 / 3)
    assert output.metadata["clusters_written"] == 1
    assert output.metadata["memberships_written"] == 2


def test_vector_search_requires_explicit_mode_and_index(tmp_path: Path) -> None:
    embeddings_path = tmp_path / "embeddings"
    _seed_embeddings(
        embeddings_path,
        [
            _make_embedding(comment_id="a", vector=[1.0, 0.0]),
            _make_embedding(comment_id="b", vector=[0.99, 0.01]),
        ],
    )

    with pytest.raises(ValueError, match="vector_index_name is required"):
        ClusteringAgent().run(
            ClusteringInput(
                docket_id="DOCKET-CLUSTER",
                embedding_model="real-model",
                embeddings_path=str(embeddings_path),
                clusters_path=str(tmp_path / "clusters"),
                memberships_path=str(tmp_path / "memberships"),
                clustering_mode="vector_search",
            )
        )
