#!/usr/bin/env python3
"""scripts/manage_vector_index.py — Manage Databricks Vector Search endpoints and indexes.

Enables automated index lifecycle operations: create, sync, status, delete-confirmed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import httpx

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


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
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")


def _normalize_host(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        return "https://" + value
    return value


def preflight_databricks(endpoint_name: str, timeout: float) -> None:
    """Fail fast before invoking Vector Search SDK calls."""
    host = _normalize_host(os.environ.get("DATABRICKS_HOST"))
    token = os.environ.get("DATABRICKS_TOKEN")
    if not host or not token:
        print(
            "ERROR: DATABRICKS_HOST and DATABRICKS_TOKEN are required for Vector Search.",
            file=sys.stderr,
        )
        print(
            "Run scripts/check_databricks_ready.py for setup guidance.", file=sys.stderr
        )
        sys.exit(2)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"{host}/api/2.0/vector-search/endpoints/{endpoint_name}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 404:
                response.raise_for_status()
    except Exception as exc:
        print(
            f"ERROR: Could not reach Databricks Vector Search endpoint API: {exc}",
            file=sys.stderr,
        )
        print("Run scripts/check_databricks_ready.py for diagnostics.", file=sys.stderr)
        sys.exit(1)


def get_vsc() -> Any:
    """Instantiate and return the VectorSearchClient lazily."""
    try:
        from databricks.vector_search.client import VectorSearchClient

        return VectorSearchClient()
    except ImportError:
        print(
            "ERROR: 'databricks-vectorsearch' is not installed.",
            file=sys.stderr,
        )
        print("Please run `pip install databricks-vectorsearch`", file=sys.stderr)
        sys.exit(1)


def ensure_endpoint(vsc: Any, endpoint_name: str) -> None:
    """Verify if the endpoint exists, or create and wait for it."""
    print(f"Verifying Vector Search Endpoint: '{endpoint_name}'...")
    try:
        existing = {ep["name"] for ep in vsc.list_endpoints().get("endpoints", [])}
    except Exception as exc:
        print(f"ERROR: Could not list Vector Search endpoints: {exc}", file=sys.stderr)
        sys.exit(1)
    if endpoint_name not in existing:
        print(f"Endpoint '{endpoint_name}' does not exist. Creating...")
        vsc.create_endpoint(name=endpoint_name, endpoint_type="STANDARD")
        print(f"Waiting for endpoint '{endpoint_name}' to become ready...")
        vsc.wait_for_endpoint(name=endpoint_name, verbose=True)
    else:
        print(f"Endpoint '{endpoint_name}' found. Ensuring it is online...")
        vsc.wait_for_endpoint(name=endpoint_name, verbose=True)
    print(f"Endpoint '{endpoint_name}' is ready.")


def cmd_create(args: argparse.Namespace) -> None:
    preflight_databricks(args.endpoint, args.timeout_s)
    vsc = get_vsc()
    ensure_endpoint(vsc, args.endpoint)

    existing_indexes = {
        ix["name"]
        for ix in vsc.list_indexes(name=args.endpoint).get("vector_indexes", [])
    }
    if args.index in existing_indexes:
        print(f"Index '{args.index}' already exists on endpoint '{args.endpoint}'.")
        return

    print(
        f"Creating Delta-Sync Vector Index: '{args.index}' on endpoint '{args.endpoint}'..."
    )
    print(f"  - Source Table     : {args.source_table}")
    print(f"  - Primary Key      : {args.primary_key}")
    print(f"  - Embedding Column : {args.embedding_col}")
    print(f"  - Dimension        : {args.dimension}")

    try:
        vsc.create_delta_sync_index(
            endpoint_name=args.endpoint,
            index_name=args.index,
            source_table_name=args.source_table,
            pipeline_type="TRIGGERED",
            primary_key=args.primary_key,
            embedding_vector_column=args.embedding_col,
            embedding_dimension=args.dimension,
        )
        print(
            f"Successfully requested creation of '{args.index}'. Use 'sync' command to populate."
        )
    except Exception as e:
        print(f"ERROR: Failed to create index: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_sync(args: argparse.Namespace) -> None:
    preflight_databricks(args.endpoint, args.timeout_s)
    vsc = get_vsc()
    try:
        index = vsc.get_index(endpoint_name=args.endpoint, index_name=args.index)
    except Exception as exc:
        print(f"ERROR: Could not open index '{args.index}': {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Triggering sync for index '{args.index}'...")
    try:
        index.sync()
    except Exception as e:
        print(f"Note: Sync trigger returned: {e}. Moving to polling loop.")

    if args.wait:
        print("Waiting for sync to complete (polling index state)...")
        t0 = time.time()
        timeout = args.sync_timeout_s
        while True:
            desc = index.describe()
            status = desc.get("status") or {}
            ready = status.get("ready", False)
            state = status.get("detailed_state", "UNKNOWN")

            print(f"  - Current State: {state}")
            if ready:
                break

            if time.time() - t0 > timeout:
                print(
                    f"ERROR: Index sync timed out after {timeout} seconds.",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(15)

        duration = round(time.time() - t0, 1)
        print(f"Successfully synced! Index is online (completed in {duration}s).")


def cmd_status(args: argparse.Namespace) -> None:
    preflight_databricks(args.endpoint, args.timeout_s)
    vsc = get_vsc()
    try:
        index = vsc.get_index(endpoint_name=args.endpoint, index_name=args.index)
        desc = index.describe()

        print("\n" + "=" * 60)
        print(f"VECTOR INDEX STATUS: {args.index}")
        print("=" * 60)
        print(f"Endpoint Name      : {args.endpoint}")
        print(f"Index Type         : {desc.get('index_type')}")
        print(f"Primary Key        : {desc.get('primary_key')}")

        status = desc.get("status") or {}
        print(f"Ready State        : {status.get('ready', False)}")
        print(f"Detailed State     : {status.get('detailed_state')}")

        spec = desc.get("delta_sync_index_spec") or {}
        print(f"Source Table       : {spec.get('source_table')}")

        embedding_spec = (spec.get("embedding_vector_columns") or [{}])[0]
        print(f"Embedding Column   : {embedding_spec.get('name')}")
        print(f"Embedding Dim      : {embedding_spec.get('dimension')}")

        print("=" * 60)
    except Exception as e:
        print(f"ERROR: Could not fetch index status: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_delete(args: argparse.Namespace) -> None:
    preflight_databricks(args.endpoint, args.timeout_s)
    vsc = get_vsc()
    print(
        f"WARNING: You are deleting index '{args.index}' from endpoint '{args.endpoint}'."
    )
    if not args.yes:
        confirm = input("Type 'confirm' to execute: ")
    else:
        confirm = "confirm"
    if confirm.strip().lower() != "confirm":
        print("Aborted.")
        return

    print(f"Deleting index '{args.index}'...")
    try:
        vsc.delete_index(endpoint_name=args.endpoint, index_name=args.index)
        print("Successfully deleted index.")
    except Exception as e:
        print(f"ERROR: Failed to delete index: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI utility to manage Databricks Vector Search endpoints and indexes."
    )
    parser.add_argument(
        "--endpoint",
        default="astroturf-vs-endpoint",
        help="Vector search endpoint name. Default 'astroturf-vs-endpoint'",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=10.0,
        help="HTTP preflight timeout in seconds.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create parser
    p_create = subparsers.add_parser("create", help="Create Delta-Sync Index")
    p_create.add_argument("--index", required=True, help="Full index name")
    p_create.add_argument("--source-table", required=True, help="UC source view/table")
    p_create.add_argument("--primary-key", default="comment_id")
    p_create.add_argument("--embedding-col", default="embedding_vector")
    p_create.add_argument("--dimension", type=int, default=1024)

    # sync parser
    p_sync = subparsers.add_parser("sync", help="Trigger Sync on Index")
    p_sync.add_argument("--index", required=True)
    p_sync.add_argument(
        "--no-wait",
        action="store_false",
        dest="wait",
        help="Do not wait for readiness.",
    )
    p_sync.add_argument("--sync-timeout-s", type=int, default=900)

    # status parser
    p_status = subparsers.add_parser("status", help="Get Index Status")
    p_status.add_argument("--index", required=True)

    # delete parser
    p_delete = subparsers.add_parser("delete-confirmed", help="Delete Index")
    p_delete.add_argument("--index", required=True)
    p_delete.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive prompt; command name is still delete-confirmed.",
    )

    args = parser.parse_args()

    load_simple_env()

    # Dispatch command
    if args.command == "create":
        cmd_create(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "delete-confirmed":
        cmd_delete(args)


if __name__ == "__main__":
    main()
