#!/usr/bin/env python3
"""run_parser.py — CLI wrapper around ParserAgent."""

import argparse
import logging
import os
import sys

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.parser.agent import ParserAgent, ParserInput


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
        description="Run the ParserAgent to transform bronze comments into silver comments."
    )
    parser.add_argument(
        "--docket",
        required=True,
        help="Regulations.gov Docket ID (e.g. EPA-HQ-OAR-2021-0317)",
    )
    parser.add_argument(
        "--bronze-path",
        default="./data/bronze/raw_comments",
        help="Path to local bronze Delta table",
    )
    parser.add_argument(
        "--silver-path",
        default="./data/silver/parsed_comments",
        help="Path to local silver Delta table",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Stop after processing this many comments",
    )
    parser.add_argument(
        "--max-detail-fetches",
        type=int,
        default=None,
        help="Stop making detail API calls after this many attempts",
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

    print(f"Starting ParserAgent for docket: {args.docket}...")
    print(f"Bronze path: {args.bronze_path}")
    print(f"Silver path: {args.silver_path}")
    if args.max_rows is not None:
        print(f"Max rows limit: {args.max_rows}")
    if args.max_detail_fetches is not None:
        print(f"Max detail fetches limit: {args.max_detail_fetches}")

    agent = ParserAgent()
    inputs = ParserInput(
        docket_id=args.docket,
        bronze_path=args.bronze_path,
        silver_path=args.silver_path,
        max_rows=args.max_rows,
        max_detail_fetches=args.max_detail_fetches,
    )

    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Parsing failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print("\n" + "=" * 50)
    print("PARSING SUMMARY")
    print("=" * 50)
    print(f"Docket ID:          {output.docket_id}")
    print(f"Comments Read:      {output.metadata.get('rows_read', 0)}")
    print(f"Comments Written:   {output.rows_written}")
    print(f"Successfully Parsed:{output.metadata.get('parsed_count', 0)}")
    print(f"Title Only Fallback:{output.metadata.get('title_only_count', 0)}")
    print(f"Missing Text Rows:  {output.metadata.get('missing_text_count', 0)}")
    print(f"Parse Errors:       {output.metadata.get('error_count', 0)}")
    print(
        f"Duration:           {output.metadata.get('duration_seconds', 0.0):.2f} seconds"
    )
    print(f"Silver Path:        {args.silver_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
