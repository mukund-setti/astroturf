#!/usr/bin/env python3
"""ingest_benchmark_sample.py — Ingest a reproducible 100K stratified sample from FCC 17-108.

Iterates day-by-day through a target date range and pulls a fixed limit of comments per day.
This stays safely under the ECFS 9,999 offset limit and guarantees perfect determinism.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.ingestion.sources.ecfs import (
    ECFSClient,
    ECFSClientConfig,
    run_ecfs_ingestion,
)
from shared.api_keys import resolve_data_gov_api_key

log = logging.getLogger(__name__)

DEFAULT_BRONZE_PATH = "./data/bronze/raw_comments"
DEFAULT_MANIFEST_PATH = "./data/benchmark_sample_manifest.json"
DEFAULT_DOCKET = "17-108"
DEFAULT_START_DATE = "2017-08-21"
DEFAULT_END_DATE = "2017-08-30"  # 10 days inclusive
DEFAULT_MAX_COMMENTS_PER_DAY = 10000


def load_simple_env() -> None:
    """Load environment variables from a local .env file using simple rules."""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val


def get_dates_range(start_date: date, end_date: date) -> list[date]:
    """Return a list of inclusive dates between start_date and end_date."""
    dates = []
    curr = start_date
    while curr <= end_date:
        dates.append(curr)
        curr += timedelta(days=1)
    return dates


def ingest_stratified_sample(
    *,
    docket_id: str,
    bronze_path: str,
    start_date: date,
    end_date: date,
    max_comments_per_day: int,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
    client: ECFSClient | None = None,
) -> dict[str, Any]:
    """Run ingestion stratum-by-stratum (day-by-day) and write manifest."""
    load_simple_env()

    if client is None:
        api_key = resolve_data_gov_api_key(required=True)
        # Use a safe rate limit for the API.
        client = ECFSClient(
            ECFSClientConfig(
                api_key=api_key,
                page_size=100,
                rate_limit_qps=1.5,
            )
        )

    dates = get_dates_range(start_date, end_date)
    log.info(
        "Starting stratified sample ingestion for docket=%s across %d daily strata: %s to %s",
        docket_id,
        len(dates),
        start_date,
        end_date,
    )

    manifest_entries = []
    total_fetched = 0
    total_written = 0
    total_duration = 0.0

    for d in dates:
        log.info("--- Ingesting Stratum (Date: %s) ---", d)
        try:
            metrics = run_ecfs_ingestion(
                docket_id=docket_id,
                bronze_path=bronze_path,
                client=client,
                start_date=d,
                end_date=d,
                max_comments=max_comments_per_day,
            )
            fetched = metrics.get("comments_fetched", 0)
            written = metrics.get("comments_written", 0)
            duration = metrics.get("duration_seconds", 0.0)

            total_fetched += fetched
            total_written += written
            total_duration += duration

            manifest_entries.append(
                {
                    "stratum_date": d.isoformat(),
                    "comments_fetched": fetched,
                    "comments_written": written,
                    "duration_seconds": duration,
                }
            )
            log.info(
                "Stratum %s complete: fetched=%d, written=%d in %.2fs",
                d,
                fetched,
                written,
                duration,
            )
        except Exception as e:
            log.error("Failed to ingest stratum for date %s: %s", d, e)
            manifest_entries.append(
                {
                    "stratum_date": d.isoformat(),
                    "comments_fetched": 0,
                    "comments_written": 0,
                    "error": str(e),
                }
            )

    manifest = {
        "docket_id": docket_id,
        "total_comments_fetched": total_fetched,
        "total_comments_written": total_written,
        "max_comments_per_day": max_comments_per_day,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "strata": manifest_entries,
    }

    # Write manifest file
    out_manifest = Path(manifest_path)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    log.info("Stratified Ingestion Complete! Manifest saved to %s", out_manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a deterministic 100K stratified sample from FCC 17-108."
    )
    parser.add_argument(
        "--docket",
        default=DEFAULT_DOCKET,
        help="FCC Proceeding name",
    )
    parser.add_argument(
        "--bronze-path",
        default=DEFAULT_BRONZE_PATH,
        help="Path to bronze Delta table",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help="Lower bound date YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help="Upper bound date YYYY-MM-DD",
    )
    parser.add_argument(
        "--max-comments-per-day",
        type=int,
        default=DEFAULT_MAX_COMMENTS_PER_DAY,
        help="Maximum comments to fetch per day (stratum cap)",
    )
    parser.add_argument(
        "--manifest-path",
        default=DEFAULT_MANIFEST_PATH,
        help="Path to save the manifest JSON file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)

    try:
        manifest = ingest_stratified_sample(
            docket_id=args.docket,
            bronze_path=args.bronze_path,
            start_date=start_date,
            end_date=end_date,
            max_comments_per_day=args.max_comments_per_day,
            manifest_path=args.manifest_path,
        )
        print("\n" + "=" * 50)
        print("STRATIFIED INGESTION COMPLETE")
        print("=" * 50)
        print(f"Docket ID:             {manifest['docket_id']}")
        print(f"Total Fetched:         {manifest['total_comments_fetched']}")
        print(f"Total Written:         {manifest['total_comments_written']}")
        print(f"Start Date:            {manifest['start_date']}")
        print(f"End Date:              {manifest['end_date']}")
        print(f"Manifest Path:         {args.manifest_path}")
        print("=" * 50)
    except Exception as e:
        print(f"\nERROR: Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
