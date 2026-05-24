#!/usr/bin/env python3
"""Generate high-fidelity coordinated campaign evidence receipts (markdown and JSON).

This script performs deep statistical and linguistic analysis on detected clusters
to construct a "courtroom-ready" provenance trail of the coordinated astroturf campaign.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.export_cluster_evidence import (
    select_clusters,
)

log = logging.getLogger(__name__)

DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_OUTPUT_DIR = "./artifacts/demo/receipts"


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


def extract_top_repeated_sentences(
    texts: list[str], limit: int = 5
) -> list[tuple[str, int]]:
    """Helper to extract top repeated sentences from the comments inside the cluster.

    Heuristic Rationale: Since coordinated campaigns use a common template, splitting comments
    by sentences and finding the most frequent ones isolates the boilerplate policy arguments
    from custom prefaces/footers.
    """
    sentence_counts = Counter()
    for text in texts:
        if not text or not isinstance(text, str):
            continue
        # Split by typical sentence delimiters
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            # Focus on substantial policy sentences (length > 20, containing spaces)
            if len(s_clean) > 20 and " " in s_clean:
                sentence_counts[s_clean] += 1

    # Keep top limit
    return sentence_counts.most_common(limit)


def calculate_velocity_histogram(dates: pd.Series) -> list[dict[str, Any]]:
    """Group filing timestamps into hourly buckets and return a frequency list."""
    if dates.empty:
        return []

    # Localize/Format datetimes to string hourly buckets
    hourly_counts = dates.dt.strftime("%Y-%m-%d %H:00 UTC").value_counts().sort_index()

    histogram = []
    for bucket, count in hourly_counts.items():
        histogram.append(
            {
                "time_bucket": str(bucket),
                "count": int(count),
            }
        )
    return histogram


def calculate_cluster_confidence(
    mean_similarity: float,
    dates: pd.Series,
) -> tuple[float, float]:
    """Calculate the Coordinated Campaign Confidence Score.

    Formula: Confidence = 0.4 * MeanSimilarity + 0.6 * (1.0 - NormalizedEntropy)

    What it measures: The joint textual coherence and temporal concentration.
    What it does NOT measure: Citizen intent, legality, or final rule impact.
    Known failure modes: Highly viral natural spikes on a very short comment
    might trigger a high temporal score, but will usually have low mean similarity.
    """
    if dates.empty:
        return 0.0, 0.0

    # Bucket into hourly intervals
    buckets = dates.dt.strftime("%Y-%m-%d %H:00").value_counts()
    total = len(dates)

    if len(buckets) <= 1:
        # If all comments fell in a single hour, entropy is 0, coordination is maximum (1.0)
        norm_entropy = 0.0
    else:
        probs = buckets / total
        entropy = -sum(p * math.log2(p) for p in probs)
        max_entropy = math.log2(len(buckets))
        norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    temporal_score = 1.0 - norm_entropy
    confidence = 0.4 * mean_similarity + 0.6 * temporal_score

    # Clamp bounds
    confidence = max(0.0, min(1.0, confidence))
    return confidence, temporal_score


def generate_receipts(
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
    """Generate campaign receipts for the top clusters."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if similarity_threshold is None:
        if embedding_model == "normalized_text_hash":
            similarity_threshold = 1.0
        else:
            similarity_threshold = 0.92

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
        log.warning("No clusters found for receipt generation.")
        return {"receipts_generated": 0}

    selected_clusters = select_clusters(clusters, cluster_id=None, top_n_clusters=limit)

    receipts_written = 0
    for idx, (_, cluster) in enumerate(selected_clusters.iterrows()):
        cluster_id = str(cluster["cluster_id"])
        c_members = memberships[
            memberships["cluster_id"].astype(str) == cluster_id
        ].copy()

        # Merge parsed_comments including raw_text, normalized_text, posted_date, received_date
        joined_members = c_members.merge(parsed_comments, on="comment_id", how="left")

        cluster_size = int(cluster.get("cluster_size", len(c_members)))
        mean_sim = float(cluster["mean_similarity"])

        # Timestamps and velocity
        date_col = (
            "posted_date"
            if "posted_date" in joined_members.columns
            else "received_date"
        )
        joined_members[date_col] = pd.to_datetime(joined_members[date_col])
        valid_dates = joined_members[date_col].dropna()

        histogram = calculate_velocity_histogram(valid_dates)
        confidence, temporal_score = calculate_cluster_confidence(mean_sim, valid_dates)

        # Repeated sentences
        member_texts = (
            joined_members["raw_text"].dropna().tolist()
            or joined_members["normalized_text"].dropna().tolist()
        )
        top_sentences = extract_top_repeated_sentences(member_texts, limit=5)

        # Representative comment text
        rep_id = str(cluster["representative_comment_id"])
        rep_rows = joined_members[joined_members["comment_id"].astype(str) == rep_id]
        rep_text = "N/A"
        if not rep_rows.empty:
            rep_text = (
                rep_rows.iloc[0].get("raw_text")
                or rep_rows.iloc[0].get("normalized_text")
                or "N/A"
            )

        # Build Receipt Data
        receipt_data = {
            "docket_id": docket_id,
            "cluster_id": cluster_id,
            "cluster_size": cluster_size,
            "representative_comment_id": rep_id,
            "representative_comment": rep_text,
            "embedding_model": embedding_model,
            "similarity_threshold": similarity_threshold,
            "confidence_score": confidence,
            "temporal_coordination_score": temporal_score,
            "mean_similarity": mean_sim,
            "min_similarity": float(cluster["min_similarity"]),
            "max_similarity": float(cluster["max_similarity"]),
            "source_metadata": {
                "source": "ECFS",
                "ingested_window_start": valid_dates.min().strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                if not valid_dates.empty
                else "N/A",
                "ingested_window_end": valid_dates.max().strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                if not valid_dates.empty
                else "N/A",
            },
            "top_repeated_phrases": [
                {"phrase": s, "count": count, "percent": float(count / cluster_size)}
                for s, count in top_sentences
            ],
            "filing_velocity_histogram": histogram,
            "generated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),
        }

        # Save JSON
        json_path = out_path / f"cluster_{cluster_id[:12]}_receipt.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f, indent=2, ensure_ascii=False)

        # Save MD
        md_path = out_path / f"cluster_{cluster_id[:12]}_receipt.md"

        md_lines = [
            "# Coordinated Campaign Evidence Receipt",
            f"**Campaign Cluster ID**: `{cluster_id}`",
            "",
            "## 1. Evidentiary Rulings & Scores",
            "",
            f"- **Coordinated Campaign Confidence Score**: `{confidence:.4f}` / `1.0000`",
            f"  - *Textual Density (Mean Cosine Sim)*: `{mean_sim:.4f}` (Weight: 40%)",
            f"  - *Temporal Coordination (Filing Spike)*: `{temporal_score:.4f}` (Weight: 60%)",
            f"- **Campaign Size**: **{cluster_size} filings**",
            f"- **Representative Filer ID**: `{rep_id}`",
            "",
            "> [!NOTE]",
            "> **Confidence Score Rationale**: Highly organized campaign systems submit identical or paraphrased templates",
            "> in narrow time windows. A high temporal spike and high semantic similarity produces a very high confidence score.",
            "",
            "## 2. Campaign Template Language (Medoid)",
            "",
            f"> {rep_text}",
            "",
            "## 3. Top Coordinated Boilerplate Sentences",
            "These sentences appear with the highest frequency across the campaign cluster, defining the core lobbyist boilerplate:",
            "",
        ]

        for s_idx, phrase_info in enumerate(
            receipt_data["top_repeated_phrases"], start=1
        ):
            pct = phrase_info["percent"] * 100
            md_lines.append(
                f"**Boilerplate #{s_idx}** (Count: `{phrase_info['count']}` filings | `{pct:.1f}%` saturation):"
                f'\n> "{phrase_info["phrase"]}"\n'
            )

        md_lines.extend(
            [
                "## 4. Filing Velocity & Temporal Concentration",
                "The table below shows the automated burst of comments grouped by hour:",
                "",
                "| Hour Bucket | Volume | Visual Distribution |",
                "| --- | --- | --- |",
            ]
        )

        max_count = max((h["count"] for h in histogram), default=1)
        for h in histogram:
            bars_len = int((h["count"] / max_count) * 20)
            bars = "█" * bars_len if bars_len > 0 else "░"
            md_lines.append(
                f"| `{h['time_bucket']}` | `{h['count']}` comments | {bars} |"
            )

        md_lines.extend(
            [
                "",
                "## 5. Source Metadata & Lineage",
                f"- **Proceeding/Docket**: `{docket_id}`",
                f"- **Data Source**: `{receipt_data['source_metadata']['source']}`",
                f"- **Time Range**: `{receipt_data['source_metadata']['ingested_window_start']}` to `{receipt_data['source_metadata']['ingested_window_end']}`",
                f"- **Embedding Verification Model**: `{embedding_model}`",
                f"- **Analysis Date**: `{receipt_data['generated_at']}`",
            ]
        )

        md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")
        receipts_written += 1

    return {
        "docket_id": docket_id,
        "embedding_model": embedding_model,
        "receipts_generated": receipts_written,
        "receipts_dir": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate coordinated comment campaign receipts."
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
        help="maximum number of top clusters to process",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory to write receipts into",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="cosine threshold",
    )
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    try:
        res = generate_receipts(
            docket_id=args.docket_id,
            embedding_model=args.embedding_model,
            similarity_threshold=args.threshold,
            limit=args.limit,
            clusters_path=args.clusters_path,
            memberships_path=args.memberships_path,
            parsed_comments_path=args.parsed_comments_path,
            output_dir=args.output_dir,
        )
        print("\n=== RECEIPTS GENERATION COMPLETED ===")
        print(f"Docket ID: {res['docket_id']}")
        print(f"Embedding Model: {res['embedding_model']}")
        print(f"Receipts Generated: {res['receipts_generated']}")
        print(f"Output Directory: {res['receipts_dir']}")
        print("=====================================")
    except Exception as e:
        print(f"ERROR: Receipts generation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
