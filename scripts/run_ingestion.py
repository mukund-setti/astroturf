#!/usr/bin/env python3
"""run_ingestion.py — CLI wrapper around IngestionAgent.

Default source is ``regulations_gov``; pass ``--source ecfs`` with ``--docket``
plus the optional ``--start-date`` / ``--end-date`` window to ingest from the
FCC ECFS public API instead.
"""

import argparse
import logging
import os
import sys
from datetime import date

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.ingestion.agent import IngestionAgent, IngestionInput
from shared.api_keys import resolve_data_gov_api_key


def load_simple_env():
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


def _iso_date(value: str) -> date:
    return date.fromisoformat(value)


def main():
    parser = argparse.ArgumentParser(
        description="Run the public comments IngestionAgent."
    )
    parser.add_argument(
        "--source",
        choices=("regulations_gov", "ecfs"),
        default="regulations_gov",
        help="Source API. Default regulations_gov.",
    )
    parser.add_argument(
        "--docket",
        required=True,
        help=(
            "Docket ID. For regulations.gov: e.g. EPA-HQ-OAR-2021-0317. "
            "For ECFS: the proceeding name e.g. 17-108."
        ),
    )
    parser.add_argument(
        "--bronze-path",
        default="./data/bronze/raw_comments",
        help="Path to local Delta table",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=None,
        help="Stop after reaching this many comments",
    )
    parser.add_argument(
        "--start-date",
        type=_iso_date,
        default=None,
        help="ECFS-only: lower bound on date_received (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=_iso_date,
        default=None,
        help="ECFS-only: upper bound on date_received (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--ecfs-page-size",
        type=int,
        default=100,
        help="ECFS-only: page size for /filings pagination.",
    )
    parser.add_argument(
        "--ecfs-rate-limit-qps",
        type=float,
        default=1.0,
        help="ECFS-only: client-side rate limit in requests/second.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    load_simple_env()

    # Verify api.data.gov key is resolvable before doing any real work.
    try:
        resolve_data_gov_api_key(required=True)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "Set DATA_GOV_API_KEY in your .env (see docs/ecfs-setup.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Starting {args.source} ingestion for docket {args.docket}...")
    print(f"Target Delta table path: {args.bronze_path}")
    if args.max_comments is not None:
        print(f"Max comments limit: {args.max_comments}")
    if args.source == "ecfs" and (args.start_date or args.end_date):
        print(f"Date window: {args.start_date} .. {args.end_date}")

    agent = IngestionAgent(config={"bronze_path": args.bronze_path})
    inputs = IngestionInput(
        docket_id=args.docket,
        source=args.source,
        max_comments=args.max_comments,
        start_date=args.start_date,
        end_date=args.end_date,
        ecfs_page_size=args.ecfs_page_size,
        ecfs_rate_limit_qps=args.ecfs_rate_limit_qps,
    )

    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("INGESTION SUMMARY")
    print("=" * 50)
    print(f"Source:           {args.source}")
    print(f"Docket ID:        {output.docket_id}")
    print(f"Comments Fetched: {output.metadata.get('comments_fetched', 0)}")
    print(f"Comments Written: {output.rows_written}")
    print(f"API Calls Made:   {output.metadata.get('api_calls_made', 0)}")
    print(
        f"Duration:         {output.metadata.get('duration_seconds', 0.0):.2f} seconds"
    )
    print(f"Bronze Path:      {args.bronze_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
