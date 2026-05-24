#!/usr/bin/env python3
"""Export reproducible campaign cluster evidence for the reviewer demo path.

This script produces highly detailed Markdown and CSV artifacts for the top N largest clusters,
including timestamp distributions, semantic similarity statistics, and exact-match ratios.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.export_cluster_evidence import (
    classify_cluster,
    cluster_duplicate_stats,
    text_preview,
    select_clusters,
)

log = logging.getLogger(__name__)

DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_OUTPUT_DIR = "./artifacts/demo"


def load_and_filter_delta(
    path: str,
    *,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    """Load a Delta table and apply filters safely in Pandas to avoid delta-rs silent drop bugs."""
    if not DeltaTable.is_deltatable(path):
        raise FileNotFoundError(f"Delta table not found at {path}")

    dt = DeltaTable(path)
    df = dt.to_pandas()

    if filters:
        for col, op, val in filters:
            if col not in df.columns:
                continue
            if op == "=":
                if isinstance(val, float):
                    df = df[(df[col].astype(float) - val).abs() <= 1e-9]
                else:
                    df = df[df[col].astype(str) == str(val)]

    if columns is not None:
        subset_cols = [c for c in columns if c in df.columns]
        df = df[subset_cols]

    return df.copy()


def calculate_timestamp_distributions(
    members_df: pd.DataFrame,
) -> dict[str, Any]:
    """Calculate the earliest, latest, and peak hour filing timestamps from member comments."""
    date_col = "posted_date" if "posted_date" in members_df.columns else "received_date"
    if members_df.empty or date_col not in members_df.columns:
        return {
            "earliest_timestamp": "N/A",
            "latest_timestamp": "N/A",
            "peak_hour": "N/A",
        }

    dates = pd.to_datetime(members_df[date_col]).dropna()
    if dates.empty:
        return {
            "earliest_timestamp": "N/A",
            "latest_timestamp": "N/A",
            "peak_hour": "N/A",
        }

    earliest = dates.min().strftime("%Y-%m-%d %H:%M:%S UTC")
    latest = dates.max().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Find the hour of day that has the highest count of filings
    hours = dates.dt.hour
    if not hours.empty:
        peak_hour = int(hours.mode().iloc[0])
        peak_hour_str = f"{peak_hour:02d}:00 - {peak_hour:02d}:59"
    else:
        peak_hour_str = "N/A"

    return {
        "earliest_timestamp": earliest,
        "latest_timestamp": latest,
        "peak_hour": peak_hour_str,
    }


def build_manifest_csv(summary_rows: list[dict[str, Any]], output_path: Path) -> None:
    """Save the cluster summary rows as a clean CSV file."""
    df = pd.DataFrame(summary_rows)
    # Drop samples column as it is complex
    if "samples" in df.columns:
        df = df.drop(columns=["samples"])
    df.to_csv(output_path, index=False)
    log.info(f"Wrote CSV manifest to {output_path}")


def build_markdown_report(
    docket_id: str,
    embedding_model: str,
    threshold: float,
    clusters_in_scope: int,
    memberships_in_scope: int,
    selected_summaries: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Build and write the beautiful reviewer-friendly Markdown report."""
    lines = [
        f"# Coordinated Comment Campaign Evidence Report: {docket_id}",
        "",
        "## Reviewer Executive Summary",
        "",
        "This report summarizes the coordinated comment campaigns identified by our multi-agent Medallion Lakehouse.",
        "Unlike naive exact-duplicate keyword detectors, our pipeline leverages deep learning embeddings to group close semantic paraphrases of the same core political template.",
        "",
        "### Run Scope Details",
        f"- **Docket ID**: `{docket_id}`",
        f"- **Embedding Model**: `{embedding_model}`",
        f"- **Similarity Threshold**: `{threshold:.2f}`",
        f"- **Total Surfaced Clusters**: `{clusters_in_scope}`",
        f"- **Total Surfaced Campaign Filings**: `{memberships_in_scope}`",
        "",
        "---",
        "",
        "## Surfaced Campaigns Summary Table",
        "",
        "| Rank | Cluster ID | Size | Classification | Exact-Match % | Mean Similarity | Peak Filing Hour | Earliest Timestamp |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for idx, s in enumerate(selected_summaries, start=1):
        exact_pct = f"{s['exact_match_ratio'] * 100:.1f}%"
        mean_sim = f"{s['mean_similarity']:.4f}"
        lines.append(
            f"| #{idx} | `{s['cluster_id'][:12]}` | **{s['cluster_size']}** | `{s['classification']}` | {exact_pct} | {mean_sim} | `{s['peak_hour']}` | {s['earliest_timestamp'][:10]} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Detailed Campaign Evidentiary Packets",
            "",
        ]
    )

    for idx, s in enumerate(selected_summaries, start=1):
        lines.extend(
            [
                f"### Campaign #{idx}: Cluster `{s['cluster_id']}`",
                "",
                "#### Campaign Profile",
                f"- **Cluster Size**: {s['cluster_size']} comments",
                f"- **Representative Comment ID**: `{s['representative_comment_id']}`",
                f"- **Unique Text Hashes**: {s['unique_hash_count']} (Ratio of unique texts: `{s['unique_hash_count'] / s['cluster_size']:.3f}`)",
                f"- **Exact Match Ratio (Literal Duplicates)**: `{s['exact_match_ratio']:.3f}` (Proportion of members sharing an exact copy-pasted body)",
                f"- **Near-Duplicate Ratio (Paraphrased)**: `{s['near_duplicate_ratio']:.3f}` (Proportion of members who submitted customized or paraphrased text)",
                f"- **Filing Window**: `{s['earliest_timestamp']}` to `{s['latest_timestamp']}`",
                f"- **Peak Hour of Activity**: `{s['peak_hour']}`",
                f"- **Coordinated Style Classification**: `{s['classification']}`",
                "",
                "#### Semantic Similarity Profile",
                f"- **Mean Cosine Similarity to Medoid**: `{s['mean_similarity']:.6f}`",
                f"- **Minimum Cosine Similarity in Cluster**: `{s['min_similarity']:.6f}`",
                f"- **Maximum Cosine Similarity in Cluster**: `{s['max_similarity']:.6f}`",
                "",
                "#### Representative Campaign Template Text (Medoid)",
                "",
                f"> {s['representative_text']}",
                "",
                "#### Sample Campaign Comment Customizations",
                "Below are three sample comments illustrating how different citizens customized the template:",
                "",
            ]
        )

        for s_idx, sample in enumerate(s["samples"], start=1):
            lines.extend(
                [
                    f"**Sample Comment A.{s_idx} (ID: `{sample['comment_id']}` | Similarity: `{sample['similarity']:.4f}`)**",
                    f"> {sample['text']}",
                    "",
                ]
            )

        lines.append("\n---\n")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    log.info(f"Wrote Markdown report to {output_path}")


def export_demo_evidence(
    *,
    docket_id: str,
    embedding_model: str,
    similarity_threshold: float | None = None,
    limit: int = 5,
    clusters_path: str = DEFAULT_CLUSTERS_PATH,
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH,
    parsed_comments_path: str = DEFAULT_PARSED_COMMENTS_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Run the export process end-to-end and write files to the output directory."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if similarity_threshold is None:
        if embedding_model == "normalized_text_hash":
            similarity_threshold = 1.0
        else:
            similarity_threshold = 0.92

    log.info(
        f"Loading clusters for docket={docket_id}, model={embedding_model}, threshold={similarity_threshold}"
    )

    scope_filters = [
        ("docket_id", "=", docket_id),
        ("embedding_model", "=", embedding_model),
        ("similarity_threshold", "=", similarity_threshold),
    ]

    clusters = load_and_filter_delta(clusters_path, filters=scope_filters)
    memberships = load_and_filter_delta(memberships_path, filters=scope_filters)
    parsed_comments = load_and_filter_delta(
        parsed_comments_path,
        filters=[("docket_id", "=", docket_id)],
        columns=[
            "comment_id",
            "posted_date",
            "received_date",
            "raw_text",
            "normalized_text",
        ],
    )

    if clusters.empty:
        log.warning("No clusters found matching the specified scope.")
        return {"clusters_exported": 0, "rows_written": 0}

    selected_clusters = select_clusters(clusters, cluster_id=None, top_n_clusters=limit)

    summary_rows = []
    for idx, (_, cluster) in enumerate(selected_clusters.iterrows()):
        cluster_id = str(cluster["cluster_id"])
        c_members = memberships[
            memberships["cluster_id"].astype(str) == cluster_id
        ].copy()

        # Merge parsed_comments including raw_text, normalized_text, posted_date, received_date
        joined_members = c_members.merge(parsed_comments, on="comment_id", how="left")
        if (
            "normalized_text_hash" not in joined_members.columns
            and "text_hash" in joined_members.columns
        ):
            joined_members["normalized_text_hash"] = joined_members["text_hash"]
        joined_members["text_preview"] = joined_members.apply(
            lambda row: text_preview(row.get("raw_text") or row.get("normalized_text")),
            axis=1,
        )

        stats = cluster_duplicate_stats(joined_members)
        timestamps = calculate_timestamp_distributions(joined_members)

        cluster_size = int(cluster.get("cluster_size", len(c_members)))
        classification = classify_cluster(
            cluster_size=cluster_size,
            unique_hash_count=stats["unique_hash_count"],
            largest_exact_duplicate_group=stats["largest_exact_duplicate_group"],
        )

        # Retrieve representative text
        rep_id = str(cluster["representative_comment_id"])
        rep_rows = joined_members[joined_members["comment_id"].astype(str) == rep_id]
        rep_text = "N/A"
        if not rep_rows.empty:
            rep_text = (
                rep_rows.iloc[0].get("raw_text")
                or rep_rows.iloc[0].get("normalized_text")
                or "N/A"
            )

        # exact match ratio = duplicate members / cluster_size
        exact_ratio = stats["exact_duplicate_members"] / cluster_size
        near_ratio = 1.0 - exact_ratio

        # Retrieve a few sample members that are not the representative
        samples_df = joined_members[
            joined_members["comment_id"].astype(str) != rep_id
        ].head(3)
        samples = []
        for _, sample_row in samples_df.iterrows():
            samples.append(
                {
                    "comment_id": str(sample_row["comment_id"]),
                    "similarity": float(
                        sample_row.get("similarity_to_representative", 0.0)
                    ),
                    "text": sample_row.get("raw_text")
                    or sample_row.get("normalized_text")
                    or "N/A",
                }
            )

        summary_rows.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": cluster_size,
                "representative_comment_id": rep_id,
                "representative_text": rep_text,
                "unique_hash_count": stats["unique_hash_count"],
                "exact_duplicate_groups": stats["exact_duplicate_groups"],
                "exact_duplicate_members": stats["exact_duplicate_members"],
                "exact_match_ratio": exact_ratio,
                "near_duplicate_ratio": near_ratio,
                "mean_similarity": float(cluster["mean_similarity"]),
                "min_similarity": float(cluster["min_similarity"]),
                "max_similarity": float(cluster["max_similarity"]),
                "earliest_timestamp": timestamps["earliest_timestamp"],
                "latest_timestamp": timestamps["latest_timestamp"],
                "peak_hour": timestamps["peak_hour"],
                "classification": classification,
                "samples": samples,
            }
        )

    csv_path = out_path / f"cluster_evidence_{docket_id}.csv"
    md_path = out_path / f"cluster_evidence_{docket_id}.md"

    # Save outputs
    build_manifest_csv(summary_rows, csv_path)
    build_markdown_report(
        docket_id=docket_id,
        embedding_model=embedding_model,
        threshold=similarity_threshold,
        clusters_in_scope=len(clusters),
        memberships_in_scope=len(memberships),
        selected_summaries=summary_rows,
        output_path=md_path,
    )

    return {
        "docket_id": docket_id,
        "embedding_model": embedding_model,
        "similarity_threshold": similarity_threshold,
        "clusters_exported": len(selected_clusters),
        "csv_manifest": str(csv_path),
        "md_report": str(md_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export detailed Markdown and CSV campaign cluster evidence."
    )
    parser.add_argument("--docket-id", "--docket", required=True, help="docket ID")
    parser.add_argument(
        "--embedding-model",
        required=True,
        help="embedding model (e.g. BAAI/bge-large-en-v1.5 or normalized_text_hash)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="maximum number of top clusters to export",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory to write artifacts into",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="cosine threshold (resolved with defaults if omitted)",
    )
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    try:
        res = export_demo_evidence(
            docket_id=args.docket_id,
            embedding_model=args.embedding_model,
            similarity_threshold=args.threshold,
            limit=args.limit,
            clusters_path=args.clusters_path,
            memberships_path=args.memberships_path,
            parsed_comments_path=args.parsed_comments_path,
            output_dir=args.output_dir,
        )
        print("\n=== EXPORT COMPLETED ===")
        print(f"Docket ID: {res['docket_id']}")
        print(f"Embedding Model: {res['embedding_model']}")
        print(f"Clusters Exported: {res['clusters_exported']}")
        if "csv_manifest" in res:
            print(f"CSV Manifest: {res['csv_manifest']}")
            print(f"MD Report: {res['md_report']}")
        print("=========================")
    except Exception as e:
        print(f"ERROR: Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
