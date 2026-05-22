#!/usr/bin/env python3
"""benchmark_ingestion.py — Benchmark IngestionAgent throughput on a docket."""

import argparse
import os
import sys
import time

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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


def get_dir_size(path):
    """Recursively calculate directory size in bytes."""
    total = 0
    if os.path.exists(path):
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
                except OSError:
                    pass
    return total


def main():
    parser = argparse.ArgumentParser(description="Benchmark IngestionAgent throughput.")
    parser.add_argument(
        "--docket",
        required=True,
        help="Regulations.gov Docket ID (e.g. FDA-2013-S-0610)",
    )
    parser.add_argument(
        "--max-comments", type=int, default=1000, help="Benchmark ceiling"
    )
    parser.add_argument(
        "--bronze-path",
        default="./data/bronze/raw_comments",
        help="Path to local Delta table",
    )

    args = parser.parse_args()

    # Load environment
    load_simple_env()

    # Verify API key
    if not os.environ.get("REGULATIONS_GOV_API_KEY"):
        print(
            "ERROR: REGULATIONS_GOV_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Benchmarking ingestion on docket {args.docket} up to {args.max_comments} comments..."
    )

    agent = IngestionAgent(config={"bronze_path": args.bronze_path})
    inputs = IngestionInput(docket_id=args.docket, max_comments=args.max_comments)

    start_time = time.monotonic()
    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.monotonic() - start_time

    comments_fetched = output.metadata.get("comments_fetched", 0)
    api_calls = output.metadata.get("api_calls_made", 0)

    comments_per_sec = comments_fetched / elapsed if elapsed > 0 else 0.0
    disk_size_bytes = get_dir_size(args.bronze_path)
    disk_size_mb = disk_size_bytes / (1024 * 1024)

    # Print benchmark output
    print("\n" + "=" * 50)
    print("BENCHMARK RESULTS")
    print("=" * 50)
    print(f"Docket ID:             {args.docket}")
    print(f"Comments Fetched:      {comments_fetched}")
    print(f"API Calls Made:        {api_calls}")
    print(f"Elapsed Time:          {elapsed:.2f} seconds")
    print(f"Throughput:            {comments_per_sec:.2f} comments/sec")
    print("Retries:               not available")
    print(f"Approx Table Size:     {disk_size_mb:.2f} MB ({disk_size_bytes} bytes)")
    print("=" * 50)


if __name__ == "__main__":
    main()
