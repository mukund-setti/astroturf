#!/usr/bin/env python3
"""run_ingestion.py — CLI wrapper around IngestionAgent."""

import argparse
import logging
import os
import sys

from agents.ingestion.agent import IngestionAgent, IngestionInput


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


def main():
    parser = argparse.ArgumentParser(
        description="Run the public comments IngestionAgent."
    )
    parser.add_argument(
        "--docket",
        required=True,
        help="Regulations.gov Docket ID (e.g. FDA-2013-S-0610)",
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
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Load environment
    load_simple_env()

    # Verify API key
    if not os.environ.get("REGULATIONS_GOV_API_KEY"):
        print(
            "ERROR: REGULATIONS_GOV_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        print(
            "Please check your .env file or export the variable in your shell.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Starting ingestion for docket {args.docket}...")
    print(f"Target Delta table path: {args.bronze_path}")
    if args.max_comments is not None:
        print(f"Max comments limit: {args.max_comments}")

    agent = IngestionAgent(config={"bronze_path": args.bronze_path})
    inputs = IngestionInput(
        docket_id=args.docket,
        max_comments=args.max_comments,
    )

    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print("\n" + "=" * 50)
    print("INGESTION SUMMARY")
    print("=" * 50)
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
