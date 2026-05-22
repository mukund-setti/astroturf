#!/usr/bin/env python3
"""Exact normalized-text-hash baseline clustering for one docket."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mlflow
import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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

DEFAULT_PARSED_PATH = "./data/silver/parsed_comments"
DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_MIN_CLUSTER_SIZE = 2
DEFAULT_TEXT_SOURCE = "detail_comment_text"
EXACT_HASH_EMBEDDING_MODEL = "normalized_text_hash"
EXACT_HASH_EMBEDDING_BACKEND = "exact_hash"
EXACT_HASH_CLUSTERING_VERSION = "v1_exact_hash"
EXACT_HASH_SIMILARITY_THRESHOLD = 1.0


@dataclass
class ExactHashBaselineInput:
    docket_id: str
    parsed_path: str = DEFAULT_PARSED_PATH
    clusters_path: str = DEFAULT_CLUSTERS_PATH
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE
    text_source: str = DEFAULT_TEXT_SOURCE


@dataclass
class ExactHashBaselineOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class ExactHashBaselineAgent:
    """Cluster literal duplicate comments by normalized_text_hash."""

    def run(self, inputs: ExactHashBaselineInput) -> ExactHashBaselineOutput:
        start_time = time.monotonic()
        _validate_inputs(inputs)

        rows_total = 0
        candidates: list[dict[str, Any]] = []
        groups: list[list[dict[str, Any]]] = []
        clusters: list[CommentCluster] = []
        memberships: list[CommentClusterMembership] = []
        rows_missing_hash = 0
        deleted_clusters = 0
        deleted_memberships = 0
        rows_written = 0
        clustering_run_id = ""

        try:
            rows_total, candidates, rows_missing_hash = _load_candidates(inputs)
            groups = _duplicate_groups(candidates, inputs.min_cluster_size)
            clustering_run_id = _clustering_run_id(inputs, candidates)
            clusters, memberships = _build_output_rows(
                inputs=inputs,
                groups=groups,
                candidate_count=len(candidates),
                clustering_run_id=clustering_run_id,
            )

            deleted_clusters = delete_clustering_scope(
                inputs.clusters_path,
                comment_cluster_arrow_schema(),
                docket_id=inputs.docket_id,
                embedding_model=EXACT_HASH_EMBEDDING_MODEL,
                clustering_version=EXACT_HASH_CLUSTERING_VERSION,
                similarity_threshold=EXACT_HASH_SIMILARITY_THRESHOLD,
            )
            deleted_memberships = delete_clustering_scope(
                inputs.memberships_path,
                comment_cluster_membership_arrow_schema(),
                docket_id=inputs.docket_id,
                embedding_model=EXACT_HASH_EMBEDDING_MODEL,
                clustering_version=EXACT_HASH_CLUSTERING_VERSION,
                similarity_threshold=EXACT_HASH_SIMILARITY_THRESHOLD,
            )

            if clusters:
                cluster_metrics = merge_comment_clusters(
                    inputs.clusters_path, _clusters_to_arrow(clusters)
                )
                membership_metrics = merge_comment_cluster_memberships(
                    inputs.memberships_path, _memberships_to_arrow(memberships)
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
            metadata = {
                "rows_total_for_docket_source": rows_total,
                "rows_missing_normalized_text_hash": rows_missing_hash,
                "candidate_count": len(candidates),
                "clusters_written": len(clusters),
                "memberships_written": len(memberships),
                "deleted_clusters": deleted_clusters,
                "deleted_memberships": deleted_memberships,
                "largest_cluster_size": largest_cluster_size,
                "duration_seconds": duration,
                "embedding_model": EXACT_HASH_EMBEDDING_MODEL,
                "embedding_backend": EXACT_HASH_EMBEDDING_BACKEND,
                "clustering_version": EXACT_HASH_CLUSTERING_VERSION,
                "similarity_threshold": EXACT_HASH_SIMILARITY_THRESHOLD,
                "clustering_run_id": clustering_run_id,
            }
            _log_mlflow(inputs, metadata)

        return ExactHashBaselineOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata=metadata,
        )


def _validate_inputs(inputs: ExactHashBaselineInput) -> None:
    if inputs.min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least 2")
    if not DeltaTable.is_deltatable(inputs.parsed_path):
        raise FileNotFoundError(
            f"Parsed comments Delta table not found at {inputs.parsed_path}. "
            "Run the parser first."
        )


def _load_candidates(
    inputs: ExactHashBaselineInput,
) -> tuple[int, list[dict[str, Any]], int]:
    table = DeltaTable(inputs.parsed_path).to_pyarrow_table()
    filtered = table.filter(
        (pc.field("docket_id") == inputs.docket_id)
        & (pc.field("text_source") == inputs.text_source)
    )
    rows_total = filtered.num_rows
    selected = filtered.select(
        [
            "comment_id",
            "docket_id",
            "text_source",
            "normalized_text",
            "normalized_text_hash",
        ]
    ).to_pylist()

    candidates: list[dict[str, Any]] = []
    rows_missing_hash = 0
    for row in selected:
        text_hash = row.get("normalized_text_hash")
        if not text_hash:
            rows_missing_hash += 1
            continue
        candidates.append(row)

    candidates.sort(key=lambda row: row["comment_id"])
    return rows_total, candidates, rows_missing_hash


def _duplicate_groups(
    candidates: list[dict[str, Any]], min_cluster_size: int
) -> list[list[dict[str, Any]]]:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_hash.setdefault(row["normalized_text_hash"], []).append(row)

    groups = [
        sorted(rows, key=lambda row: row["comment_id"])
        for _, rows in sorted(by_hash.items())
        if len(rows) >= min_cluster_size
    ]
    return sorted(
        groups,
        key=lambda rows: (rows[0]["normalized_text_hash"], rows[0]["comment_id"]),
    )


def _build_output_rows(
    *,
    inputs: ExactHashBaselineInput,
    groups: list[list[dict[str, Any]]],
    candidate_count: int,
    clustering_run_id: str,
) -> tuple[list[CommentCluster], list[CommentClusterMembership]]:
    now = datetime.now(timezone.utc)
    clusters: list[CommentCluster] = []
    memberships: list[CommentClusterMembership] = []

    for group in groups:
        text_hash = group[0]["normalized_text_hash"]
        comment_ids = [row["comment_id"] for row in group]
        representative = sorted(
            group,
            key=lambda row: (
                -len(row.get("normalized_text") or ""),
                row["comment_id"],
            ),
        )[0]
        cluster_id = _cluster_id(inputs.docket_id, text_hash, comment_ids)

        clusters.append(
            CommentCluster(
                cluster_id=cluster_id,
                clustering_run_id=clustering_run_id,
                docket_id=inputs.docket_id,
                embedding_model=EXACT_HASH_EMBEDDING_MODEL,
                embedding_backend=EXACT_HASH_EMBEDDING_BACKEND,
                clustering_version=EXACT_HASH_CLUSTERING_VERSION,
                similarity_threshold=EXACT_HASH_SIMILARITY_THRESHOLD,
                candidate_count=candidate_count,
                cluster_size=len(group),
                representative_comment_id=representative["comment_id"],
                representative_text_hash=text_hash,
                mean_similarity=1.0,
                min_similarity=1.0,
                max_similarity=1.0,
                created_at=now,
                updated_at=now,
            )
        )

        ranked = sorted(
            group,
            key=lambda row: (
                row["comment_id"] != representative["comment_id"],
                row["comment_id"],
            ),
        )
        for rank, row in enumerate(ranked, start=1):
            memberships.append(
                CommentClusterMembership(
                    cluster_id=cluster_id,
                    comment_id=row["comment_id"],
                    clustering_run_id=clustering_run_id,
                    docket_id=inputs.docket_id,
                    embedding_model=EXACT_HASH_EMBEDDING_MODEL,
                    embedding_backend=EXACT_HASH_EMBEDDING_BACKEND,
                    clustering_version=EXACT_HASH_CLUSTERING_VERSION,
                    similarity_threshold=EXACT_HASH_SIMILARITY_THRESHOLD,
                    text_hash=text_hash,
                    text_source=inputs.text_source,
                    similarity_to_representative=1.0,
                    membership_rank=rank,
                    created_at=now,
                    updated_at=now,
                )
            )

    clusters.sort(key=lambda row: row.cluster_id)
    memberships.sort(key=lambda row: (row.cluster_id, row.membership_rank))
    return clusters, memberships


def _clustering_run_id(
    inputs: ExactHashBaselineInput, candidates: list[dict[str, Any]]
) -> str:
    h = hashlib.sha256()
    for part in (EXACT_HASH_CLUSTERING_VERSION, inputs.docket_id, inputs.text_source):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    for row in candidates:
        h.update(str(row["comment_id"]).encode("utf-8"))
        h.update(b"\0")
        h.update(str(row["normalized_text_hash"]).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _cluster_id(docket_id: str, text_hash: str, comment_ids: list[str]) -> str:
    payload = f"v1_exact_hash|{docket_id}|{text_hash}|{sorted(comment_ids)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clusters_to_arrow(rows: list[CommentCluster]) -> pa.Table:
    schema = comment_cluster_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _memberships_to_arrow(rows: list[CommentClusterMembership]) -> pa.Table:
    schema = comment_cluster_membership_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _log_mlflow(inputs: ExactHashBaselineInput, metadata: dict[str, Any]) -> None:
    with mlflow.start_run(run_name=f"exact-hash-baseline-{inputs.docket_id}"):
        mlflow.log_param("docket_id", inputs.docket_id)
        mlflow.log_param("parsed_path", inputs.parsed_path)
        mlflow.log_param("clusters_path", inputs.clusters_path)
        mlflow.log_param("memberships_path", inputs.memberships_path)
        mlflow.log_param("min_cluster_size", inputs.min_cluster_size)
        mlflow.log_param("text_source", inputs.text_source)
        mlflow.log_param("embedding_model", EXACT_HASH_EMBEDDING_MODEL)
        mlflow.log_param("embedding_backend", EXACT_HASH_EMBEDDING_BACKEND)
        mlflow.log_param("clustering_version", EXACT_HASH_CLUSTERING_VERSION)
        mlflow.log_param("similarity_threshold", EXACT_HASH_SIMILARITY_THRESHOLD)
        if metadata.get("clustering_run_id"):
            mlflow.log_param("clustering_run_id", metadata["clustering_run_id"])

        for key in (
            "rows_total_for_docket_source",
            "rows_missing_normalized_text_hash",
            "candidate_count",
            "clusters_written",
            "memberships_written",
            "deleted_clusters",
            "deleted_memberships",
            "largest_cluster_size",
            "duration_seconds",
        ):
            mlflow.log_metric(key, metadata[key])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cluster exact duplicate comments by normalized_text_hash."
    )
    parser.add_argument("--docket", required=True, help="Regulations.gov docket ID")
    parser.add_argument("--parsed-path", default=DEFAULT_PARSED_PATH)
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument(
        "--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE
    )
    parser.add_argument("--text-source", default=DEFAULT_TEXT_SOURCE)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    inputs = ExactHashBaselineInput(
        docket_id=args.docket,
        parsed_path=args.parsed_path,
        clusters_path=args.clusters_path,
        memberships_path=args.memberships_path,
        min_cluster_size=args.min_cluster_size,
        text_source=args.text_source,
    )

    try:
        output = ExactHashBaselineAgent().run(inputs)
    except Exception as exc:
        print(f"\nERROR: Exact hash baseline failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("EXACT HASH BASELINE SUMMARY")
    print("=" * 50)
    print(f"Docket ID:              {output.docket_id}")
    print(f"Text Source:            {args.text_source}")
    print(f"Embedding Model:        {output.metadata.get('embedding_model', '')}")
    print(f"Embedding Backend:      {output.metadata.get('embedding_backend', '')}")
    print(f"Clustering Version:     {output.metadata.get('clustering_version', '')}")
    print(f"Threshold:              {output.metadata.get('similarity_threshold', 0.0)}")
    print(
        "Rows For Docket/Source: "
        f"{output.metadata.get('rows_total_for_docket_source', 0)}"
    )
    print(f"Candidate Count:        {output.metadata.get('candidate_count', 0)}")
    print(
        "Missing Hash Rows:      "
        f"{output.metadata.get('rows_missing_normalized_text_hash', 0)}"
    )
    print(f"Clusters Written:       {output.metadata.get('clusters_written', 0)}")
    print(f"Memberships Written:    {output.metadata.get('memberships_written', 0)}")
    print(f"Largest Cluster Size:   {output.metadata.get('largest_cluster_size', 0)}")
    print(f"Deleted Clusters:       {output.metadata.get('deleted_clusters', 0)}")
    print(f"Deleted Memberships:    {output.metadata.get('deleted_memberships', 0)}")
    print(f"Rows Written:           {output.rows_written}")
    print(
        f"Duration:               {output.metadata.get('duration_seconds', 0.0):.2f}s"
    )
    print(f"Clustering Run ID:      {output.metadata.get('clustering_run_id', '')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
