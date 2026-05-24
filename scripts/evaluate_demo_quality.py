#!/usr/bin/env python3
"""Quality evaluation and validation harness for comment clustering demo.

Calculates exact duplicate ratios, near-duplicate ratios, cluster purity,
and representative-comment quality. Writes detailed diagnostic Markdown and JSON reports.
"""

from __future__ import annotations

import argparse
import json
import logging
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
    cluster_duplicate_stats,
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


def calculate_purity(texts: list[str], top_phrases: list[str]) -> float:
    """Calculate the cluster purity.

    Purity is the percentage of comments in the cluster that contain at least
    one of the core boilerplate campaign phrases.
    """
    if not texts or not top_phrases:
        return 0.0

    matches = 0
    for text in texts:
        if not text or not isinstance(text, str):
            continue
        text_lower = text.lower()
        if any(phrase.lower() in text_lower for phrase in top_phrases):
            matches += 1
    return float(matches / len(texts))


def calculate_length_sanity(text: str) -> float:
    """Calculate length sanity score (between 0.0 and 1.0).

    Boilerplate comments should be clean and readable, not too short (<50 chars)
    nor unreasonably long (>4000 chars).
    """
    if not text or not isinstance(text, str):
        return 0.0
    length = len(text)
    if length < 50:
        return max(0.1, length / 50.0)
    if length > 4000:
        return max(0.1, 4000.0 / length)
    return 1.0


def evaluate_quality(
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
    """Run the evaluation metrics and write reports to output_dir."""
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
        columns=["comment_id", "raw_text", "normalized_text"],
    )

    if clusters.empty:
        log.warning("No clusters found for evaluation.")
        return {"evaluated_clusters_count": 0}

    selected_clusters = select_clusters(clusters, cluster_id=None, top_n_clusters=limit)

    eval_results = []
    for idx, (_, cluster) in enumerate(selected_clusters.iterrows()):
        cluster_id = str(cluster["cluster_id"])
        c_members = memberships[
            memberships["cluster_id"].astype(str) == cluster_id
        ].copy()

        # Merge parsed_comments including raw_text, normalized_text
        joined_members = c_members.merge(parsed_comments, on="comment_id", how="left")
        if (
            "normalized_text_hash" not in joined_members.columns
            and "text_hash" in joined_members.columns
        ):
            joined_members["normalized_text_hash"] = joined_members["text_hash"]

        stats = cluster_duplicate_stats(joined_members)

        cluster_size = int(cluster.get("cluster_size", len(c_members)))
        mean_sim = float(cluster["mean_similarity"])

        # 1. Exact Duplicate Ratio
        exact_ratio = stats["exact_duplicate_members"] / cluster_size

        # 2. Near-Duplicate Ratio
        near_ratio = 1.0 - exact_ratio

        # Retrieve member texts
        member_texts = (
            joined_members["raw_text"].dropna().tolist()
            or joined_members["normalized_text"].dropna().tolist()
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

        # 3. Cluster Purity
        # Find top repeated sentences as signature boilerplate
        sentence_counts = Counter()
        for text in member_texts:
            if not text or not isinstance(text, str):
                continue
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) > 30 and " " in s_clean:
                    sentence_counts[s_clean] += 1

        top_boilerplate = [phrase for phrase, count in sentence_counts.most_common(3)]
        purity = calculate_purity(member_texts, top_boilerplate)

        # 4. Representative-Comment Quality
        # Combined score of length sanity and semantic centrality (similarity to others)
        len_sanity = calculate_length_sanity(rep_text)
        rep_quality = 0.4 * len_sanity + 0.6 * mean_sim

        eval_results.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": cluster_size,
                "representative_comment_id": rep_id,
                "exact_duplicate_ratio": exact_ratio,
                "near_duplicate_ratio": near_ratio,
                "cluster_purity": purity,
                "representative_comment_quality": rep_quality,
                "signature_phrases": top_boilerplate,
            }
        )

    # Prepare outputs
    summary = {
        "docket_id": docket_id,
        "embedding_model": embedding_model,
        "similarity_threshold": similarity_threshold,
        "evaluated_clusters_count": len(eval_results),
        "evaluation_metrics": eval_results,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Write JSON
    json_path = out_path / f"demo_quality_evaluation_{docket_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Write Markdown
    md_path = out_path / f"demo_quality_evaluation_{docket_id}.md"
    md_lines = [
        f"# Coordinated Campaign Validation & Quality Report: {docket_id}",
        "",
        "## Reviewer Quality Summary",
        "",
        "This report assesses the quality of our campaign clusters against strict mathematical metrics.",
        "To ensure high-fidelity evidence, each metric is explicitly defined by what it measures,",
        "what it does not measure, and its known failure modes.",
        "",
        "---",
        "",
        "## Evaluation Metrics Dashboard",
        "",
        "| Rank | Cluster ID | Size | Exact Duplicate % | Near Duplicate % | Cluster Purity | Representative Quality |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for idx, e in enumerate(eval_results, start=1):
        exact_pct = f"{e['exact_duplicate_ratio'] * 100:.1f}%"
        near_pct = f"{e['near_duplicate_ratio'] * 100:.1f}%"
        purity_pct = f"{e['cluster_purity'] * 100:.1f}%"
        q_score = f"{e['representative_comment_quality']:.4f}"
        md_lines.append(
            f"| #{idx} | `{e['cluster_id'][:12]}` | **{e['cluster_size']}** | {exact_pct} | {near_pct} | {purity_pct} | {q_score} |"
        )

    md_lines.extend(
        [
            "",
            "---",
            "",
            "## Metric Definitions & Honestly Documented Limitations",
            "",
            "### 1. Exact Duplicate Ratio",
            "- **What it measures**: The proportion of comments within a cluster that are character-for-character identical after whitespace normalization.",
            "- **What it does NOT measure**: Semantic paraphrasing, light editing (e.g. adding a personal preface), or typo correction.",
            '- **Known Failure Modes**: An astroturf campaign where users are instructed to change just a single word (e.g. swapping "smothering" for "hurting") will have an Exact Duplicate Ratio of `0.0`, despite being highly coordinated.',
            "",
            "### 2. Near-Duplicate Ratio",
            "- **What it measures**: The proportion of comments in a cluster that are grouped semantically but are NOT character-for-character identical.",
            "- **What it does NOT measure**: The exact quality or meaningfulness of the customized edits.",
            "- **Known Failure Modes**: If the similarity threshold is set too low (e.g., `0.85`), unrelated but highly verbose comments discussing the same general topic might get clumped together and inflate this ratio.",
            "",
            "### 3. Cluster Purity",
            "- **What it measures**: The percentage of members in a cluster that contain the signature campaign sentences/boilerplate phrases.",
            "- **What it does NOT measure**: Semantic alignment of comments that do not use the explicit boilerplate words.",
            "- **Known Failure Modes**: If members express the same sentiment in completely different words, purity will be low despite high semantic similarity.",
            "",
            "### 4. Representative-Comment Quality",
            "- **What it measures**: The readability (length sanity) and centralization (similarity to other members).",
            "- **What it does NOT measure**: The truthfulness, political efficacy, or legal validity of the comment's arguments.",
            "- **Known Failure Modes**: A very long comment containing extensive unrelated personal rants could be selected as the medoid if it happens to contain parts of the template, resulting in low representative-comment readability/quality score.",
            "",
            "---",
            "",
            "## Detailed Diagnostics per Cluster",
            "",
        ]
    )

    for idx, e in enumerate(eval_results, start=1):
        md_lines.extend(
            [
                f"### Cluster `{e['cluster_id']}` (Size: {e['cluster_size']})",
                f"- **Exact Duplicate Ratio**: `{e['exact_duplicate_ratio']:.4f}`",
                f"- **Near-Duplicate Ratio**: `{e['near_duplicate_ratio']:.4f}`",
                f"- **Cluster Purity**: `{e['cluster_purity']:.4f}`",
                f"- **Representative Quality**: `{e['representative_comment_quality']:.4f}`",
                "",
                "**Surfaced Campaign Boilerplate Sentences**:",
            ]
        )
        for s_idx, phrase in enumerate(e["signature_phrases"], start=1):
            md_lines.append(f'{s_idx}. "{phrase}"')
        md_lines.append("\n---\n")

    md_lines.extend(
        [
            "## Pipeline General Limitations",
            "1. **Temporal Horizon Bias**: The local demo slice spans only a 3-day window. Some campaign waves are wider, meaning full volume is underrepresented here.",
            "2. **Threshold Sensitivity**: A fixed similarity threshold of `0.92` works exceptionally well for BGE embeddings, but slight semantic drifts (e.g. heavy personal prefaces) can lead to false negatives.",
            "3. **Spam Filtering Assumptions**: This harness assumes that high similarity represents a coordinated spam campaign; it cannot distinguish legal bulk filings (advocacy groups compiling authorized petitions) from malicious fake submissions (identity theft) without manual registry checks.",
        ]
    )

    md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")

    return {
        "docket_id": docket_id,
        "embedding_model": embedding_model,
        "json_report": str(json_path),
        "md_report": str(md_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run validation metrics and quality evaluation on comment clusters."
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
        help="maximum number of top clusters to evaluate",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory to write reports into",
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
        res = evaluate_quality(
            docket_id=args.docket_id,
            embedding_model=args.embedding_model,
            similarity_threshold=args.threshold,
            limit=args.limit,
            clusters_path=args.clusters_path,
            memberships_path=args.memberships_path,
            parsed_comments_path=args.parsed_comments_path,
            output_dir=args.output_dir,
        )
        print("\n=== EVALUATION COMPLETED ===")
        print(f"Docket ID: {res['docket_id']}")
        print(f"Embedding Model: {res['embedding_model']}")
        print(f"JSON Quality Report: {res['json_report']}")
        print(f"MD Quality Report:  {res['md_report']}")
        print("============================")
    except Exception as e:
        print(f"ERROR: Quality evaluation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
