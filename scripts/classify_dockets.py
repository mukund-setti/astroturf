#!/usr/bin/env python3
"""scripts/classify_dockets.py — Topic classification and prioritization task.

Deterministic rule-based keyword classifier that updates topics,
tags, and priority scores on discovered dockets in the catalog.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.delta_utils.discovery import merge_docket_catalog
from shared.schemas.docket_catalog import DiscoveredDocket, docket_catalog_arrow_schema

log = logging.getLogger("classify_dockets")


def load_watchlist(watchlist_path: str) -> list[dict[str, Any]]:
    """Load active watches to calculate user interest."""
    if not Path(watchlist_path).exists():
        return []
    try:
        with open(watchlist_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("Could not read watchlist file at %s: %s", watchlist_path, e)
        return []


def classify_topic_and_tags(docket: DiscoveredDocket) -> tuple[str, str]:
    """Map title and summary text deterministically to topic domains and return tags."""
    title = docket.title.lower()
    summary = docket.summary.lower()
    text = f"{title} {summary}"

    # Default mappings
    topic_id = docket.topic_id
    tags_list = [t.strip() for t in docket.tags.split(",") if t.strip()]

    # Rules
    if (
        "methane" in text
        or "climate" in text
        or "emissions" in text
        or "greenhouse" in text
    ):
        topic_id = "oil_and_gas"
        tags_list.extend(["Climate", "Environment", "Methane"])
    elif (
        "neutrality" in text
        or "broadband" in text
        or "common carrier" in text
        or "telecom" in text
    ):
        topic_id = "telecom"
        tags_list.extend(["Telecom", "Net Neutrality", "Open Internet"])
    elif (
        "payday" in text
        or "installment" in text
        or "loans" in text
        or "custody" in text
        or "asset" in text
    ):
        topic_id = "finance"
        tags_list.extend(["Finance", "Loans", "Consumer Protection"])
    elif (
        "algorithmic" in text
        or "transparency" in text
        or "software" in text
        or "cybersecurity" in text
        or "automated decision" in text
    ):
        topic_id = "ai_regulation"
        tags_list.extend(["AI", "Software", "Transparency"])
    elif (
        "robocall" in text
        or "spoofing" in text
        or "caller id" in text
        or "privacy" in text
    ):
        topic_id = "privacy"
        tags_list.extend(["Privacy", "Robocalls", "Telemarketing"])
    elif "non-compete" in text or "workplace" in text or "employment" in text:
        topic_id = "labor"
        tags_list.extend(["Labor", "FTC", "Workplace"])
    elif "clinical" in text or "device" in text or "medical" in text or "fda" in text:
        topic_id = "healthcare"
        tags_list.extend(["Healthcare", "FDA", "Devices"])

    # Ensure agency ID is in tags
    if docket.agency_id and docket.agency_id not in tags_list:
        tags_list.append(docket.agency_id)

    # De-duplicate tags
    unique_tags = []
    for tag in tags_list:
        clean_tag = tag.strip()
        if clean_tag and clean_tag.lower() not in [t.lower() for t in unique_tags]:
            unique_tags.append(clean_tag)

    return topic_id, ", ".join(unique_tags)


def calculate_priority_score(
    docket: DiscoveredDocket, watchlist: list[dict[str, Any]]
) -> float:
    """Implement multi-factor priority score calculation.

    Capped at 100.0. Formula:
    Score = Scale_Score (25 max) + Recency_Score (25 max) + Watchlist_Score (45 max) + Agency_Score (5 max)
    """
    now = datetime.now(timezone.utc)

    # 1. Scale Score (25 max)
    # Rewards high estimated comment volume
    scale_score = 25.0 * min(1.0, docket.comment_count_estimate / 50000.0)

    # 2. Recency Score (25 max)
    # Rewards active rulemaking with exponential decay
    recency_score = 0.0
    if docket.last_comment_date:
        try:
            delta_days = (now - docket.last_comment_date).days
            # Half-life of 30 days
            recency_score = 25.0 * math.exp(-max(0, delta_days) / 30.0)
        except Exception:
            recency_score = 15.0  # Default if date conversion fails
    else:
        recency_score = 10.0  # Default fallback if no date exists

    # 3. Watchlist / User Interest Score (45 max)
    # user_requested_count rewards up to 30.
    # Active watchlist hit (keyword / agency / topic match) adds an additional 15.
    user_interest_score = 30.0 * min(1.0, docket.user_requested_count / 10.0)

    watchlist_match = False
    for watch in watchlist:
        if watch.get("status") != "active":
            continue
        kind = watch.get("kind")
        val = str(watch.get("value", "")).lower()

        if kind == "keyword" and (
            val in docket.title.lower() or val in docket.summary.lower()
        ):
            watchlist_match = True
        elif kind == "agency" and val == docket.agency_id.lower():
            watchlist_match = True
        elif kind == "topic" and val == docket.topic_id.lower():
            watchlist_match = True
        elif kind == "docket" and val == docket.docket_id.lower():
            watchlist_match = True

    if watchlist_match:
        user_interest_score += 15.0

    # 4. Agency Priority Bonus (5 max)
    # Monitored agency targets receive a slight boost
    agency_score = 0.0
    if docket.agency_id in {"FCC", "EPA", "CFPB", "FTC"}:
        agency_score = 5.0

    total_score = scale_score + recency_score + user_interest_score + agency_score
    return min(100.0, max(0.0, total_score))


def run_classification(
    *,
    catalog_path: str,
    watchlist_path: str,
    mode: str,
    dry_run: bool,
    catalog: str,
) -> list[DiscoveredDocket]:
    """Classify and prioritize dockets in the catalog."""
    log.info("Starting topic classification and prioritization task...")

    if not Path(catalog_path).exists():
        log.error(
            "Catalog JSON file not found at: %s. Run discovery task first.",
            catalog_path,
        )
        return []

    # Read existing dockets
    with open(catalog_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    dockets = [DiscoveredDocket(**item) for item in raw_list]
    watchlist = load_watchlist(watchlist_path)
    log.info(
        "Loaded %s discovered dockets and %s watchlist rules.",
        len(dockets),
        len(watchlist),
    )

    classified_dockets: list[DiscoveredDocket] = []
    now = datetime.now(timezone.utc)

    for doc in dockets:
        # Classify topic and resolve tags
        topic_id, tags = classify_topic_and_tags(doc)
        doc.topic_id = topic_id
        doc.tags = tags

        # Calculate multi-factor priority score
        score = calculate_priority_score(doc, watchlist)
        doc.priority_score = round(score, 2)
        doc.updated_at = now

        classified_dockets.append(doc)

    if dry_run:
        log.info(
            "[DRY-RUN] Classified and prioritized %s dockets successfully.",
            len(classified_dockets),
        )
        for d in classified_dockets:
            print(
                f"- [DRY-RUN CLASSIFIED] docket_id={d.docket_id} topic_id={d.topic_id} tags=[{d.tags}] score={d.priority_score}"
            )
        return classified_dockets

    # Local file fallback: Write JSON list
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump([d.model_dump(mode="json") for d in classified_dockets], f, indent=2)
    log.info(
        "Wrote classified and prioritized dockets to local catalog file: %s",
        catalog_path,
    )

    # Local/Production Delta Writes
    if mode == "local":
        delta_path = Path(catalog_path).parent / "docket_catalog_delta"
        arrow_schema = docket_catalog_arrow_schema()
        pylist = [d.model_dump() for d in classified_dockets]
        table = pa.Table.from_pylist(pylist, schema=arrow_schema)
        try:
            metrics = merge_docket_catalog(str(delta_path), table)
            log.info("Merged local Delta catalog table successfully: %s", metrics)
        except Exception as e:
            log.error("Failed to write to local Delta catalog table: %s", e)
    elif mode == "databricks":
        table_target = f"{catalog}.discovery.docket_catalog"
        try:
            from pyspark.sql import SparkSession

            spark = SparkSession.getActiveSession()
            if spark:
                pylist = [d.model_dump() for d in classified_dockets]
                from shared.schemas.docket_catalog import docket_catalog_struct

                df = spark.createDataFrame(pylist, schema=docket_catalog_struct())
                df.createOrReplaceTempView("classified_updates")

                # Perform Unity Catalog Delta MERGE statement
                merge_sql = f"""
                    MERGE INTO {table_target} AS target
                    USING classified_updates AS source
                    ON target.docket_id = source.docket_id
                    WHEN MATCHED THEN UPDATE SET *
                    WHEN NOT MATCHED THEN INSERT *
                """
                spark.sql(merge_sql)
                log.info(
                    "Spark Delta MERGE executed successfully on Unity Catalog target: %s",
                    table_target,
                )
        except Exception as e:
            log.error("Failed to execute Databricks UC merge: %s", e)

    return classified_dockets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autopilot topic classification and prioritization task."
    )
    parser.add_argument(
        "--catalog-file",
        default="data/discovery/docket_catalog.json",
        help="Path to local docket catalog JSON",
    )
    parser.add_argument(
        "--watchlist-file",
        default="ui/.data/watchlist.json",
        help="Path to local watchlist JSON",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "databricks"),
        default="local",
        help="Autopilot execution mode",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print step arguments without writing"
    )
    parser.add_argument(
        "--catalog", default="workspace", help="Unity Catalog target catalog name"
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        run_classification(
            catalog_path=args.catalog_file,
            watchlist_path=args.watchlist_file,
            mode=args.mode,
            dry_run=args.dry_run,
            catalog=args.catalog,
        )
    except Exception as e:
        log.exception("Autopilot classification task failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
