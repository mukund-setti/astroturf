#!/usr/bin/env python3
"""Export lightweight Markdown evidence for comment clusters."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_TOP_N_CLUSTERS = 5
DEFAULT_SAMPLE_MEMBERS = 20


def load_delta_frame(
    path: str,
    *,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    """Load a Delta table into pandas, using filters when delta-rs supports them."""
    if not DeltaTable.is_deltatable(path):
        raise FileNotFoundError(f"Delta table not found at {path}")

    table = DeltaTable(path)
    try:
        return table.to_pandas(columns=columns, filters=filters)
    except Exception:
        if not filters:
            raise
        df = table.to_pandas(columns=columns)
        return apply_filters(df, filters)


def apply_filters(
    df: pd.DataFrame, filters: list[tuple[str, str, Any]]
) -> pd.DataFrame:
    """Apply a small subset of Delta-style filters for older delta-rs versions."""
    filtered = df
    for column, operator, value in filters:
        if column not in filtered.columns:
            return filtered.iloc[0:0].copy()
        if operator != "=":
            raise ValueError(f"Unsupported filter operator: {operator}")
        if isinstance(value, float):
            filtered = filtered[(filtered[column].astype(float) - value).abs() <= 1e-9]
        else:
            filtered = filtered[filtered[column] == value]
    return filtered.copy()


def filter_run_scope(
    df: pd.DataFrame,
    *,
    docket_id: str,
    embedding_model: str,
    threshold: float,
) -> pd.DataFrame:
    """Filter cluster or membership rows to one bounded run scope."""
    return apply_filters(
        df,
        [
            ("docket_id", "=", docket_id),
            ("embedding_model", "=", embedding_model),
            ("similarity_threshold", "=", threshold),
        ],
    )


def select_clusters(
    clusters: pd.DataFrame,
    *,
    cluster_id: str | None,
    top_n_clusters: int,
) -> pd.DataFrame:
    """Select one explicit cluster or the largest N clusters deterministically."""
    if clusters.empty:
        return clusters.copy()

    sorted_clusters = clusters.sort_values(
        by=["cluster_size", "cluster_id"],
        ascending=[False, True],
        kind="mergesort",
    )
    if cluster_id:
        return sorted_clusters[
            sorted_clusters["cluster_id"].astype(str) == cluster_id
        ].copy()
    return sorted_clusters.head(top_n_clusters).copy()


def cluster_duplicate_stats(members: pd.DataFrame) -> dict[str, int]:
    """Summarize exact normalized-text-hash duplicates inside a cluster."""
    hash_column = (
        "normalized_text_hash"
        if "normalized_text_hash" in members.columns
        else "text_hash"
    )
    if members.empty or hash_column not in members.columns:
        return {
            "unique_hash_count": 0,
            "exact_duplicate_groups": 0,
            "exact_duplicate_members": 0,
            "largest_exact_duplicate_group": 0,
        }

    hashes = members[hash_column].dropna().astype(str).str.strip()
    hashes = hashes[hashes != ""]
    counts = hashes.value_counts()
    duplicates = counts[counts > 1]
    return {
        "unique_hash_count": int(hashes.nunique()),
        "exact_duplicate_groups": int(len(duplicates)),
        "exact_duplicate_members": int(duplicates.sum()) if not duplicates.empty else 0,
        "largest_exact_duplicate_group": int(counts.max()) if not counts.empty else 0,
    }


def classify_cluster(
    *,
    cluster_size: int,
    unique_hash_count: int,
    largest_exact_duplicate_group: int,
) -> str:
    """Classify whether a cluster is paraphrase-, duplicate-, or mixed-driven."""
    if cluster_size <= 1:
        return "mixed"
    if unique_hash_count >= cluster_size * 0.8:
        return "embedding/paraphrase-driven"
    if largest_exact_duplicate_group >= cluster_size * 0.6:
        return "exact-duplicate-driven"
    return "mixed"


def text_preview(value: Any, *, limit: int = 300) -> str:
    """Return a single-line deterministic text preview."""
    if value is None or pd.isna(value):
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def markdown_escape(value: Any) -> str:
    """Escape Markdown table control characters."""
    text = text_preview(value, limit=500)
    return text.replace("|", "\\|")


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    """Render a small pandas frame as a plain Markdown table."""
    available = [column for column in columns if column in df.columns]
    if not available:
        return "_No rows._"

    rows = ["| " + " | ".join(available) + " |"]
    rows.append("| " + " | ".join("---" for _ in available) + " |")
    for _, row in df[available].iterrows():
        rows.append(
            "| "
            + " | ".join(markdown_escape(row[column]) for column in available)
            + " |"
        )
    return "\n".join(rows)


def attach_parsed_fields(
    members: pd.DataFrame, parsed_comments: pd.DataFrame
) -> pd.DataFrame:
    """Join selected parsed comment fields onto membership rows."""
    if members.empty or parsed_comments.empty:
        return members.copy()

    parsed_columns = [
        column
        for column in [
            "comment_id",
            "title",
            "raw_text",
            "normalized_text",
            "normalized_text_hash",
        ]
        if column in parsed_comments.columns
    ]
    if "comment_id" not in parsed_columns:
        return members.copy()

    joined = members.merge(
        parsed_comments[parsed_columns],
        on="comment_id",
        how="left",
    )
    if "normalized_text_hash" not in joined.columns and "text_hash" in joined.columns:
        joined["normalized_text_hash"] = joined["text_hash"]
    joined["text_preview"] = joined.apply(
        lambda row: text_preview(row.get("raw_text") or row.get("normalized_text")),
        axis=1,
    )
    return joined


def build_report(
    *,
    docket_id: str,
    embedding_model: str,
    threshold: float,
    clusters: pd.DataFrame,
    memberships: pd.DataFrame,
    parsed_comments: pd.DataFrame,
    selected_clusters: pd.DataFrame,
    sample_members: int = DEFAULT_SAMPLE_MEMBERS,
) -> str:
    """Build the Markdown evidence report."""
    lines = [
        f"# Cluster Evidence Export: {docket_id}",
        "",
        "## Run Scope",
        "",
        f"- Docket ID: `{docket_id}`",
        f"- Embedding model: `{embedding_model}`",
        f"- Similarity threshold: `{threshold}`",
        f"- Total clusters: `{len(clusters)}`",
        f"- Total memberships: `{len(memberships)}`",
        "",
        "## Top Clusters By Size",
        "",
        markdown_table(
            clusters.sort_values(
                by=["cluster_size", "cluster_id"],
                ascending=[False, True],
                kind="mergesort",
            ).head(DEFAULT_TOP_N_CLUSTERS),
            [
                "cluster_id",
                "cluster_size",
                "representative_comment_id",
                "mean_similarity",
                "min_similarity",
                "max_similarity",
            ],
        ),
        "",
        "## Selected Cluster Evidence",
        "",
    ]

    if selected_clusters.empty:
        lines.append("_No clusters matched the requested filters._")
        return "\n".join(lines).rstrip() + "\n"

    for _, cluster in selected_clusters.iterrows():
        cluster_id = str(cluster["cluster_id"])
        selected_members = memberships[
            memberships["cluster_id"].astype(str) == cluster_id
        ].copy()
        if "membership_rank" in selected_members.columns:
            selected_members = selected_members.sort_values(
                by=["membership_rank", "comment_id"], kind="mergesort"
            )
        joined_members = attach_parsed_fields(selected_members, parsed_comments)
        stats = cluster_duplicate_stats(joined_members)
        cluster_size = int(cluster.get("cluster_size", len(selected_members)))
        classification = classify_cluster(
            cluster_size=cluster_size,
            unique_hash_count=stats["unique_hash_count"],
            largest_exact_duplicate_group=stats["largest_exact_duplicate_group"],
        )
        representative_id = cluster.get("representative_comment_id", "")
        representative_rows = joined_members[
            joined_members["comment_id"].astype(str) == str(representative_id)
        ]
        representative_preview = ""
        if not representative_rows.empty:
            representative_preview = str(representative_rows.iloc[0]["text_preview"])

        member_sample = joined_members.head(sample_members).copy()
        if "similarity_to_representative" in member_sample.columns:
            member_sample["similarity_to_representative"] = member_sample[
                "similarity_to_representative"
            ].map(lambda value: f"{float(value):.6f}")

        lines.extend(
            [
                f"### Cluster `{cluster_id}`",
                "",
                f"- Cluster size: `{cluster_size}`",
                f"- Representative comment ID: `{representative_id}`",
                f"- Unique normalized_text_hash count: `{stats['unique_hash_count']}`",
                f"- Exact duplicate groups inside cluster: `{stats['exact_duplicate_groups']}`",
                f"- Exact duplicate members inside cluster: `{stats['exact_duplicate_members']}`",
                f"- Classification: `{classification}`",
                "",
                "**Representative Text Preview**",
                "",
                f"> {representative_preview or 'N/A'}",
                "",
                "**Sample Members**",
                "",
                markdown_table(
                    member_sample,
                    [
                        "comment_id",
                        "similarity_to_representative",
                        "title",
                        "text_preview",
                    ],
                ),
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def output_path_for(docket_id: str, requested_output: str | None) -> Path:
    """Resolve the output path, using the default export location when omitted."""
    if requested_output:
        return Path(requested_output)
    return Path(f"./data/exports/cluster_evidence_{docket_id}.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Markdown evidence for one bounded cluster run scope."
    )
    parser.add_argument("--docket", required=True, help="Regulations.gov docket ID")
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--cluster-id", default=None)
    parser.add_argument(
        "--top-n-clusters",
        type=int,
        default=DEFAULT_TOP_N_CLUSTERS,
        help="Number of largest clusters to include when --cluster-id is omitted",
    )
    parser.add_argument(
        "--sample-members",
        type=int,
        default=DEFAULT_SAMPLE_MEMBERS,
        help="Maximum member rows shown per selected cluster",
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_n_clusters < 1:
        raise ValueError("--top-n-clusters must be at least 1")
    if args.sample_members < 1:
        raise ValueError("--sample-members must be at least 1")

    scope_filters = [
        ("docket_id", "=", args.docket),
        ("embedding_model", "=", args.embedding_model),
        ("similarity_threshold", "=", args.threshold),
    ]
    clusters = load_delta_frame(args.clusters_path, filters=scope_filters)
    memberships = load_delta_frame(args.memberships_path, filters=scope_filters)
    parsed_comments = load_delta_frame(
        args.parsed_comments_path,
        filters=[("docket_id", "=", args.docket)],
        columns=[
            "comment_id",
            "docket_id",
            "title",
            "raw_text",
            "normalized_text",
            "normalized_text_hash",
        ],
    )

    clusters = filter_run_scope(
        clusters,
        docket_id=args.docket,
        embedding_model=args.embedding_model,
        threshold=args.threshold,
    )
    memberships = filter_run_scope(
        memberships,
        docket_id=args.docket,
        embedding_model=args.embedding_model,
        threshold=args.threshold,
    )
    selected_clusters = select_clusters(
        clusters,
        cluster_id=args.cluster_id,
        top_n_clusters=args.top_n_clusters,
    )
    report = build_report(
        docket_id=args.docket,
        embedding_model=args.embedding_model,
        threshold=args.threshold,
        clusters=clusters,
        memberships=memberships,
        parsed_comments=parsed_comments,
        selected_clusters=selected_clusters,
        sample_members=args.sample_members,
    )

    output_path = output_path_for(args.docket, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote cluster evidence report to {output_path}")


if __name__ == "__main__":
    main()
