"""ClusteringAgent - silver.comment_embeddings -> gold cluster tables.

Local v1 clusters a single docket/model slice by computing all pairwise cosine
similarities, adding an undirected edge for pairs above the threshold, and
writing connected components to gold tables.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mlflow
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable

from shared.delta_utils.silver import load_delta_as_pyarrow
from shared.delta_utils.gold import (
    delete_clustering_scope,
    merge_comment_cluster_memberships,
    merge_comment_clusters,
)
from shared.schemas.comment_clusters import (
    CommentCluster,
    CommentClusterMembership,
    comment_cluster_arrow_schema,
    comment_cluster_membership_arrow_schema,
)

log = logging.getLogger(__name__)

DEFAULT_EMBEDDINGS_PATH = "./data/silver/comment_embeddings"
DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_CLUSTERING_VERSION = "v1_connected_components_cosine"
DEFAULT_SIMILARITY_THRESHOLD = 0.92
DEFAULT_MIN_CLUSTER_SIZE = 2


@dataclass
class ClusteringInput:
    docket_id: str
    embedding_model: str
    embeddings_path: str = DEFAULT_EMBEDDINGS_PATH
    clusters_path: str = DEFAULT_CLUSTERS_PATH
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH
    clustering_version: str = DEFAULT_CLUSTERING_VERSION
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE
    max_rows: int | None = None
    allow_mock: bool = False
    clustering_mode: str = "local"
    vector_index_name: str | None = None
    vector_endpoint_name: str = "astroturf-vs-endpoint"
    vector_search_limit: int = 100
    vector_search_client: Any | None = None


@dataclass
class ClusteringOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class ClusteringAgent:
    """Detect near-duplicate embedding clusters for one docket/model slice."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def run(self, inputs: ClusteringInput) -> ClusteringOutput:
        start_time = time.monotonic()
        self._validate_inputs(inputs)

        log.info(
            "Starting ClusteringAgent for docket=%s, model=%s, threshold=%.4f",
            inputs.docket_id,
            inputs.embedding_model,
            inputs.similarity_threshold,
        )

        candidates_total = 0
        candidates_after_mock_filter = 0
        rows_clustered = 0
        pair_count_evaluated = 0
        edge_count = 0
        deleted_clusters = 0
        deleted_memberships = 0
        rows_written = 0
        clusters: list[CommentCluster] = []
        memberships: list[CommentClusterMembership] = []
        embedding_backend = ""
        clustering_run_id = ""

        mode = "local"
        try:
            candidates, candidates_total, candidates_after_mock_filter = (
                self._load_candidates(inputs)
            )
            rows_clustered = len(candidates)
            embedding_backend = self._resolve_embedding_backend(candidates)
            clustering_run_id = _clustering_run_id(inputs, candidates)

            components: list[list[int]] = []
            if inputs.clustering_mode == "vector_search":
                mode = "vector_search"
                if rows_clustered:
                    vsc = inputs.vector_search_client
                    if vsc is None:
                        from databricks.vector_search.client import VectorSearchClient

                        vsc = VectorSearchClient()

                    index_name = inputs.vector_index_name
                    if not index_name:
                        raise ValueError(
                            "vector_index_name is required when "
                            "clustering_mode='vector_search'"
                        )
                    log.info(
                        "Querying Vector Search index=%s endpoint=%s",
                        index_name,
                        inputs.vector_endpoint_name,
                    )
                    index = vsc.get_index(
                        endpoint_name=inputs.vector_endpoint_name,
                        index_name=index_name,
                    )

                    id_to_idx = {
                        row["comment_id"]: i for i, row in enumerate(candidates)
                    }
                    edges: list[tuple[int, int]] = []
                    sparse_similarities: dict[tuple[int, int], float] = {}

                    for i, row in enumerate(candidates):
                        query_vector = row["embedding_vector"]
                        results_payload = index.similarity_search(
                            query_vector=query_vector,
                            columns=["comment_id"],
                            num_results=inputs.vector_search_limit,
                        )

                        data = (results_payload.get("result") or {}).get(
                            "data_array"
                        ) or []
                        manifest = results_payload.get("manifest") or {}
                        cols = [c["name"] for c in manifest.get("columns", [])]

                        try:
                            cid_col_idx = cols.index("comment_id")
                            score_col_idx = cols.index("score")
                        except ValueError:
                            cid_col_idx = 0
                            score_col_idx = 1 if len(cols) > 1 else -1

                        for neighbor_row in data:
                            if not neighbor_row:
                                continue
                            neighbor_id = str(neighbor_row[cid_col_idx])
                            score = (
                                float(neighbor_row[score_col_idx])
                                if score_col_idx != -1
                                else 1.0
                            )

                            if neighbor_id in id_to_idx:
                                j = id_to_idx[neighbor_id]
                                if i == j:
                                    continue
                                if score >= inputs.similarity_threshold:
                                    u, v_node = min(i, j), max(i, j)
                                    pair_key = (u, v_node)
                                    if pair_key not in sparse_similarities:
                                        sparse_similarities[pair_key] = score
                                        edges.append(pair_key)

                    edge_count = len(edges)
                    components = [
                        component
                        for component in _connected_components(rows_clustered, edges)
                        if len(component) >= inputs.min_cluster_size
                    ]

                    def get_similarity(x: int, y: int) -> float:
                        if x == y:
                            return 1.0
                        key = (min(x, y), max(x, y))
                        return sparse_similarities.get(key, 0.0)

                    clusters, memberships = self._build_sparse_output_rows(
                        inputs=inputs,
                        candidates=candidates,
                        get_similarity=get_similarity,
                        components=components,
                        embedding_backend=embedding_backend,
                        clustering_run_id=clustering_run_id,
                    )
            else:
                vectors = _normalized_matrix(candidates)
                if rows_clustered:
                    similarities = vectors @ vectors.T
                    pair_count_evaluated = rows_clustered * (rows_clustered - 1) // 2
                    edges = _edges_at_threshold(
                        similarities, inputs.similarity_threshold
                    )
                    edge_count = len(edges)
                    components = [
                        component
                        for component in _connected_components(rows_clustered, edges)
                        if len(component) >= inputs.min_cluster_size
                    ]
                    clusters, memberships = self._build_output_rows(
                        inputs=inputs,
                        candidates=candidates,
                        similarities=similarities,
                        components=components,
                        embedding_backend=embedding_backend,
                        clustering_run_id=clustering_run_id,
                    )

            deleted_clusters = delete_clustering_scope(
                inputs.clusters_path,
                comment_cluster_arrow_schema(),
                docket_id=inputs.docket_id,
                embedding_model=inputs.embedding_model,
                clustering_version=inputs.clustering_version,
                similarity_threshold=inputs.similarity_threshold,
            )
            deleted_memberships = delete_clustering_scope(
                inputs.memberships_path,
                comment_cluster_membership_arrow_schema(),
                docket_id=inputs.docket_id,
                embedding_model=inputs.embedding_model,
                clustering_version=inputs.clustering_version,
                similarity_threshold=inputs.similarity_threshold,
            )

            if clusters:
                cluster_metrics = merge_comment_clusters(
                    inputs.clusters_path, _clusters_to_arrow(clusters)
                )
                membership_metrics = merge_comment_cluster_memberships(
                    inputs.memberships_path,
                    _memberships_to_arrow(memberships),
                )
                rows_written = (
                    cluster_metrics["inserted"]
                    + cluster_metrics["updated"]
                    + membership_metrics["inserted"]
                    + membership_metrics["updated"]
                )
        finally:
            duration = time.monotonic() - start_time
            largest_cluster_size = max(
                (cluster.cluster_size for cluster in clusters), default=0
            )
            mean_cluster_size = (
                float(np.mean([cluster.cluster_size for cluster in clusters]))
                if clusters
                else 0.0
            )
            metadata = {
                "candidates_total": candidates_total,
                "candidates_after_mock_filter": candidates_after_mock_filter,
                "rows_clustered": rows_clustered,
                "pair_count_evaluated": pair_count_evaluated,
                "edge_count_above_threshold": edge_count,
                "clusters_written": len(clusters),
                "memberships_written": len(memberships),
                "deleted_clusters": deleted_clusters,
                "deleted_memberships": deleted_memberships,
                "largest_cluster_size": largest_cluster_size,
                "mean_cluster_size": mean_cluster_size,
                "duration_seconds": duration,
                "runtime_seconds": duration,
                "embedding_model": inputs.embedding_model,
                "embedding_backend": embedding_backend,
                "clustering_version": inputs.clustering_version,
                "similarity_threshold": inputs.similarity_threshold,
                "clustering_run_id": clustering_run_id,
                "mode": mode,
                "vector_index_name": inputs.vector_index_name or "",
                "threshold": inputs.similarity_threshold,
                "comments_considered": rows_clustered,
                "clusters_found": len(clusters),
                "coverage": (
                    len(memberships) / rows_clustered if rows_clustered else 0.0
                ),
            }
            _log_mlflow(inputs, metadata)

        log.info(
            "ClusteringAgent complete. Candidates=%d, Edges=%d, Clusters=%d, "
            "Memberships=%d, Written=%d, Duration=%.2fs",
            rows_clustered,
            edge_count,
            len(clusters),
            len(memberships),
            rows_written,
            duration,
        )

        return ClusteringOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata=metadata,
        )

    def _validate_inputs(self, inputs: ClusteringInput) -> None:
        if not 0.0 <= inputs.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0.0 and 1.0")
        if inputs.min_cluster_size < 2:
            raise ValueError("min_cluster_size must be at least 2")
        if inputs.max_rows is not None and inputs.max_rows < 1:
            raise ValueError("max_rows must be positive when provided")
        if inputs.clustering_mode not in {"local", "vector_search"}:
            raise ValueError("clustering_mode must be 'local' or 'vector_search'")
        if inputs.clustering_mode == "vector_search" and not inputs.vector_index_name:
            raise ValueError(
                "vector_index_name is required when clustering_mode='vector_search'"
            )
        if inputs.vector_search_limit < 2:
            raise ValueError("vector_search_limit must be at least 2")
        if not DeltaTable.is_deltatable(inputs.embeddings_path):
            raise FileNotFoundError(
                f"Embeddings Delta table not found at {inputs.embeddings_path}. "
                "Run the embedding agent first."
            )

    def _load_candidates(
        self, inputs: ClusteringInput
    ) -> tuple[list[dict[str, Any]], int, int]:
        table = load_delta_as_pyarrow(inputs.embeddings_path)
        filtered = table.filter(
            (pc.field("docket_id") == inputs.docket_id)
            & (pc.field("embedding_model") == inputs.embedding_model)
        )
        candidates_total = filtered.num_rows
        if not inputs.allow_mock:
            filtered = filtered.filter(pc.field("backend") != "mock")
        candidates_after_mock_filter = filtered.num_rows

        selected = filtered.select(
            [
                "comment_id",
                "docket_id",
                "embedding_model",
                "embedding_dim",
                "text_hash",
                "text_source",
                "embedding_vector",
                "backend",
            ]
        ).to_pylist()
        selected = sorted(selected, key=lambda row: row["comment_id"])
        if inputs.max_rows is not None:
            selected = selected[: inputs.max_rows]
        return selected, candidates_total, candidates_after_mock_filter

    def _resolve_embedding_backend(self, candidates: list[dict[str, Any]]) -> str:
        backends = sorted({row["backend"] for row in candidates})
        if len(backends) > 1:
            raise ValueError(
                "ClusteringAgent requires a single embedding backend per run; "
                f"found {backends}"
            )
        return backends[0] if backends else ""

    def _build_output_rows(
        self,
        *,
        inputs: ClusteringInput,
        candidates: list[dict[str, Any]],
        similarities: np.ndarray,
        components: list[list[int]],
        embedding_backend: str,
        clustering_run_id: str,
    ) -> tuple[list[CommentCluster], list[CommentClusterMembership]]:
        now = datetime.now(timezone.utc)
        clusters: list[CommentCluster] = []
        memberships: list[CommentClusterMembership] = []
        candidate_count = len(candidates)

        for component in components:
            component = sorted(component, key=lambda idx: candidates[idx]["comment_id"])
            representative_idx = _medoid_index(similarities, component)
            representative = candidates[representative_idx]
            member_similarities = [
                float(similarities[representative_idx, idx]) for idx in component
            ]
            cluster_id = _cluster_id(inputs, [candidates[idx] for idx in component])

            clusters.append(
                CommentCluster(
                    cluster_id=cluster_id,
                    clustering_run_id=clustering_run_id,
                    docket_id=inputs.docket_id,
                    embedding_model=inputs.embedding_model,
                    embedding_backend=embedding_backend,
                    clustering_version=inputs.clustering_version,
                    similarity_threshold=inputs.similarity_threshold,
                    candidate_count=candidate_count,
                    cluster_size=len(component),
                    representative_comment_id=representative["comment_id"],
                    representative_text_hash=representative["text_hash"],
                    mean_similarity=float(np.mean(member_similarities)),
                    min_similarity=float(np.min(member_similarities)),
                    max_similarity=float(np.max(member_similarities)),
                    created_at=now,
                    updated_at=now,
                )
            )

            ranked = sorted(
                (
                    (idx, float(similarities[representative_idx, idx]))
                    for idx in component
                ),
                key=lambda item: (-item[1], candidates[item[0]]["comment_id"]),
            )
            for rank, (idx, sim) in enumerate(ranked, start=1):
                row = candidates[idx]
                memberships.append(
                    CommentClusterMembership(
                        cluster_id=cluster_id,
                        comment_id=row["comment_id"],
                        clustering_run_id=clustering_run_id,
                        docket_id=inputs.docket_id,
                        embedding_model=inputs.embedding_model,
                        embedding_backend=embedding_backend,
                        clustering_version=inputs.clustering_version,
                        similarity_threshold=inputs.similarity_threshold,
                        text_hash=row["text_hash"],
                        text_source=row["text_source"],
                        similarity_to_representative=sim,
                        membership_rank=rank,
                        created_at=now,
                        updated_at=now,
                    )
                )

        clusters.sort(key=lambda cluster: cluster.cluster_id)
        memberships.sort(key=lambda row: (row.cluster_id, row.membership_rank))
        return clusters, memberships

    def _build_sparse_output_rows(
        self,
        *,
        inputs: ClusteringInput,
        candidates: list[dict[str, Any]],
        get_similarity: Any,
        components: list[list[int]],
        embedding_backend: str,
        clustering_run_id: str,
    ) -> tuple[list[CommentCluster], list[CommentClusterMembership]]:
        now = datetime.now(timezone.utc)
        clusters: list[CommentCluster] = []
        memberships: list[CommentClusterMembership] = []
        candidate_count = len(candidates)

        for component in components:
            component = sorted(component, key=lambda idx: candidates[idx]["comment_id"])
            representative_idx = _sparse_medoid_index(get_similarity, component)
            representative = candidates[representative_idx]
            member_similarities = [
                float(get_similarity(representative_idx, idx)) for idx in component
            ]
            cluster_id = _cluster_id(inputs, [candidates[idx] for idx in component])

            clusters.append(
                CommentCluster(
                    cluster_id=cluster_id,
                    clustering_run_id=clustering_run_id,
                    docket_id=inputs.docket_id,
                    embedding_model=inputs.embedding_model,
                    embedding_backend=embedding_backend,
                    clustering_version=inputs.clustering_version,
                    similarity_threshold=inputs.similarity_threshold,
                    candidate_count=candidate_count,
                    cluster_size=len(component),
                    representative_comment_id=representative["comment_id"],
                    representative_text_hash=representative["text_hash"],
                    mean_similarity=float(np.mean(member_similarities)),
                    min_similarity=float(np.min(member_similarities)),
                    max_similarity=float(np.max(member_similarities)),
                    created_at=now,
                    updated_at=now,
                )
            )

            ranked = sorted(
                (
                    (idx, float(get_similarity(representative_idx, idx)))
                    for idx in component
                ),
                key=lambda item: (-item[1], candidates[item[0]]["comment_id"]),
            )
            for rank, (idx, sim) in enumerate(ranked, start=1):
                row = candidates[idx]
                memberships.append(
                    CommentClusterMembership(
                        cluster_id=cluster_id,
                        comment_id=row["comment_id"],
                        clustering_run_id=clustering_run_id,
                        docket_id=inputs.docket_id,
                        embedding_model=inputs.embedding_model,
                        embedding_backend=embedding_backend,
                        clustering_version=inputs.clustering_version,
                        similarity_threshold=inputs.similarity_threshold,
                        text_hash=row["text_hash"],
                        text_source=row["text_source"],
                        similarity_to_representative=sim,
                        membership_rank=rank,
                        created_at=now,
                        updated_at=now,
                    )
                )

        clusters.sort(key=lambda cluster: cluster.cluster_id)
        memberships.sort(key=lambda row: (row.cluster_id, row.membership_rank))
        return clusters, memberships


def _normalized_matrix(candidates: list[dict[str, Any]]) -> np.ndarray:
    if not candidates:
        return np.empty((0, 0), dtype=np.float32)

    dimensions = {int(row["embedding_dim"]) for row in candidates}
    if len(dimensions) != 1:
        raise ValueError(f"Mixed embedding dimensions found: {sorted(dimensions)}")

    vectors = np.array(
        [row["embedding_vector"] for row in candidates],
        dtype=np.float32,
    )
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0.0):
        bad_ids = [
            row["comment_id"]
            for row, norm in zip(candidates, norms)
            if float(norm) == 0.0
        ]
        raise ValueError(f"Zero-norm embedding vectors found: {bad_ids}")
    return vectors / norms[:, None]


def _edges_at_threshold(
    similarities: np.ndarray, threshold: float
) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    for i in range(similarities.shape[0]):
        for j in range(i + 1, similarities.shape[0]):
            if float(similarities[i, j]) >= threshold:
                edges.append((i, j))
    return edges


def _connected_components(
    node_count: int, edges: list[tuple[int, int]]
) -> list[list[int]]:
    parent = list(range(node_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i, j in edges:
        union(i, j)

    components_by_root: dict[int, list[int]] = {}
    for idx in range(node_count):
        components_by_root.setdefault(find(idx), []).append(idx)
    return list(components_by_root.values())


def _medoid_index(similarities: np.ndarray, component: list[int]) -> int:
    best_idx = component[0]
    best_mean = -1.0
    for idx in component:
        mean_similarity = float(
            np.mean([similarities[idx, other] for other in component])
        )
        if mean_similarity > best_mean:
            best_mean = mean_similarity
            best_idx = idx
    return best_idx


def _clustering_run_id(
    inputs: ClusteringInput, candidates: list[dict[str, Any]]
) -> str:
    h = hashlib.sha256()
    for part in (
        inputs.docket_id,
        inputs.embedding_model,
        inputs.clustering_version,
        _threshold_key(inputs.similarity_threshold),
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    for comment_id in sorted(str(row["comment_id"]) for row in candidates):
        h.update(comment_id.encode("utf-8"))
        h.update(b"\0")
    for text_hash in sorted(str(row["text_hash"]) for row in candidates):
        h.update(text_hash.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _cluster_id(inputs: ClusteringInput, members: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for part in (
        "cluster",
        inputs.docket_id,
        inputs.embedding_model,
        inputs.clustering_version,
        _threshold_key(inputs.similarity_threshold),
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    for comment_id in sorted(str(row["comment_id"]) for row in members):
        h.update(comment_id.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _threshold_key(threshold: float) -> str:
    return f"{threshold:.8f}"


def _clusters_to_arrow(rows: list[CommentCluster]) -> pa.Table:
    schema = comment_cluster_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _memberships_to_arrow(rows: list[CommentClusterMembership]) -> pa.Table:
    schema = comment_cluster_membership_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump() if hasattr(row, "model_dump") else row.dict()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _log_mlflow(inputs: ClusteringInput, metadata: dict[str, Any]) -> None:
    with mlflow.start_run(run_name=f"clustering-{inputs.docket_id}"):
        mlflow.log_param("docket_id", inputs.docket_id)
        mlflow.log_param("embedding_model", inputs.embedding_model)
        mlflow.log_param("embeddings_path", inputs.embeddings_path)
        mlflow.log_param("clusters_path", inputs.clusters_path)
        mlflow.log_param("memberships_path", inputs.memberships_path)
        mlflow.log_param("clustering_version", inputs.clustering_version)
        mlflow.log_param("similarity_threshold", inputs.similarity_threshold)
        mlflow.log_param("min_cluster_size", inputs.min_cluster_size)
        mlflow.log_param("max_rows", inputs.max_rows)
        mlflow.log_param("allow_mock", inputs.allow_mock)
        mlflow.log_param("mode", metadata.get("mode", "local"))
        mlflow.log_param("clustering_mode", inputs.clustering_mode)
        if metadata.get("mode") == "vector_search":
            mlflow.log_param("vector_index_name", metadata["vector_index_name"])
            mlflow.log_param("vector_endpoint_name", inputs.vector_endpoint_name)
            mlflow.log_param("vector_search_limit", inputs.vector_search_limit)
        if metadata.get("embedding_backend"):
            mlflow.log_param("embedding_backend", metadata["embedding_backend"])
        if metadata.get("clustering_run_id"):
            mlflow.log_param("clustering_run_id", metadata["clustering_run_id"])

        for key in (
            "candidates_total",
            "candidates_after_mock_filter",
            "rows_clustered",
            "pair_count_evaluated",
            "edge_count_above_threshold",
            "clusters_written",
            "memberships_written",
            "deleted_clusters",
            "deleted_memberships",
            "largest_cluster_size",
            "mean_cluster_size",
            "coverage",
            "duration_seconds",
            "runtime_seconds",
        ):
            mlflow.log_metric(key, metadata[key])
        mlflow.log_metric("threshold", metadata["threshold"])
        mlflow.log_metric("comments_considered", metadata["comments_considered"])
        mlflow.log_metric("clusters_found", metadata["clusters_found"])


def _sparse_medoid_index(get_similarity: Any, component: list[int]) -> int:
    best_idx = component[0]
    best_mean = -1.0
    for idx in component:
        mean_similarity = float(
            np.mean([get_similarity(idx, other) for other in component])
        )
        if mean_similarity > best_mean:
            best_mean = mean_similarity
            best_idx = idx
    return best_idx
