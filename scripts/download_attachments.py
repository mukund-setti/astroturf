#!/usr/bin/env python3
"""download_attachments.py — CLI wrapper around AttachmentDownloaderAgent."""

import argparse
import logging
import os
import sys

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.downloader.agent import AttachmentDownloaderAgent, DownloaderInput


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
        description="Run the AttachmentDownloaderAgent to safely download cataloged silver attachments."
    )
    parser.add_argument(
        "--docket",
        required=True,
        help="Regulations.gov Docket ID (e.g. EPA-HQ-OAR-2021-0317)",
    )
    parser.add_argument(
        "--attachments-path",
        default="./data/attachments",
        help="Root directory where downloaded attachments are saved",
    )
    parser.add_argument(
        "--attachments-table-path",
        default="./data/silver/comment_attachments",
        help="Path to local comment_attachments Delta table",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=10,
        help="Limit the number of downloaded files in this run",
    )
    parser.add_argument(
        "--max-file-mb",
        type=int,
        default=25,
        help="Limit the size of downloaded files (in MB)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="If set, attempts to retry downloading previously failed attachments",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="If set, downloads and overwrites existing files on disk",
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

    # Load local environment
    load_simple_env()

    print(f"Starting AttachmentDownloaderAgent for docket: {args.docket}...")
    print(f"Attachments storage path:   {args.attachments_path}")
    print(f"Attachments Delta path:     {args.attachments_table_path}")
    print(f"Max downloads safety limit: {args.max_downloads}")
    print(f"Max file size safety limit: {args.max_file_mb} MB")
    print(f"Retry previously failed:    {args.retry_failed}")
    print(f"Force download overwrite:   {args.force_download}")

    # Set up http_client that reads regulations.gov api key if needed
    # though downloads are direct links, some sites might require specific headers
    api_key = os.environ.get("REGULATIONS_GOV_API_KEY")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if api_key:
        headers["X-Api-Key"] = api_key

    import httpx

    http_client = httpx.Client(
        headers=headers,
        timeout=30.0,
        follow_redirects=True,
    )

    agent = AttachmentDownloaderAgent(http_client=http_client)
    inputs = DownloaderInput(
        docket_id=args.docket,
        attachments_path=args.attachments_path,
        attachments_table_path=args.attachments_table_path,
        max_downloads=args.max_downloads,
        max_file_mb=args.max_file_mb,
        retry_failed=args.retry_failed,
        force_download=args.force_download,
    )

    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Attachment downloading failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print("\n" + "=" * 50)
    print("DOWNLOADER RUN SUMMARY")
    print("=" * 50)
    print(f"Docket ID:            {output.docket_id}")
    print(f"Files Downloaded:     {output.downloaded_count}")
    print(f"Files Skipped:        {output.skipped_count}")
    print(f"Files Failed:         {output.failed_count}")
    print(f"Total Bytes Saved:    {output.total_bytes_downloaded}")
    print(
        f"Total Saved Size:     {output.total_bytes_downloaded / (1024 * 1024):.2f} MB"
    )
    print("=" * 50)


if __name__ == "__main__":
    main()
