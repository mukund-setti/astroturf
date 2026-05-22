#!/usr/bin/env python3
"""CLI wrapper around ClusteringAgent."""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.clustering.agent import (
    DEFAULT_CLUSTERS_PATH,
    DEFAULT_CLUSTERING_VERSION,
    DEFAULT_EMBEDDINGS_PATH,
    DEFAULT_MEMBERSHIPS_PATH,
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_SIMILARITY_THRESHOLD,
    ClusteringAgent,
    ClusteringInput,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cluster one docket/model slice from silver.comment_embeddings."
    )
    parser.add_argument("--docket", required=True, help="Regulations.gov docket ID")
    parser.add_argument(
        "--embedding-model",
        required=True,
        help="Embedding model slice to cluster",
    )
    parser.add_argument("--embeddings-path", default=DEFAULT_EMBEDDINGS_PATH)
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--clustering-version", default=DEFAULT_CLUSTERING_VERSION)
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help="Cosine similarity threshold for connected-component edges",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=DEFAULT_MIN_CLUSTER_SIZE,
    )
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        help="Allow embeddings whose backend is 'mock' (tests/debugging only).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    agent = ClusteringAgent()
    inputs = ClusteringInput(
        docket_id=args.docket,
        embedding_model=args.embedding_model,
        embeddings_path=args.embeddings_path,
        clusters_path=args.clusters_path,
        memberships_path=args.memberships_path,
        clustering_version=args.clustering_version,
        similarity_threshold=args.threshold,
        min_cluster_size=args.min_cluster_size,
        max_rows=args.max_rows,
        allow_mock=args.allow_mock,
    )

    try:
        output = agent.run(inputs)
    except Exception as exc:
        print(f"\nERROR: Clustering failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("CLUSTERING SUMMARY")
    print("=" * 50)
    print(f"Docket ID:              {output.docket_id}")
    print(f"Embedding Model:        {output.metadata.get('embedding_model', '')}")
    print(f"Embedding Backend:      {output.metadata.get('embedding_backend', '')}")
    print(f"Clustering Version:     {output.metadata.get('clustering_version', '')}")
    print(f"Threshold:              {output.metadata.get('similarity_threshold', 0.0)}")
    print(f"Candidates Total:       {output.metadata.get('candidates_total', 0)}")
    print(
        "After Mock Filter:      "
        f"{output.metadata.get('candidates_after_mock_filter', 0)}"
    )
    print(f"Rows Clustered:         {output.metadata.get('rows_clustered', 0)}")
    print(f"Pairs Evaluated:        {output.metadata.get('pair_count_evaluated', 0)}")
    print(
        f"Edges Above Threshold:  {output.metadata.get('edge_count_above_threshold', 0)}"
    )
    print(f"Clusters Written:       {output.metadata.get('clusters_written', 0)}")
    print(f"Memberships Written:    {output.metadata.get('memberships_written', 0)}")
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
