"""Fast local smoke test for the Databricks web analysis job.

This validates parameter parsing and agent input construction without starting
Databricks, calling public APIs, writing Delta tables, or invoking Foundation
Models. Pass ``--live`` only when intentionally extending this script to execute
the real pipeline stages.
"""

from __future__ import annotations

import argparse
import os
import pprint
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.web_analysis_job_support import (  # noqa: E402
    agent_inputs_as_safe_dict,
    build_agent_inputs,
    build_web_analysis_paths,
    parse_web_analysis_params,
    sanitize_regulations_gov_api_key,
)


SMOKE_PARAMS = {
    "docket_id": "CFPB-2016-0025",
    "source": "regulations_gov",
    "topic_id": "consumer_finance",
    "agency_id": "CFPB",
    "start_date": "",
    "end_date": "",
    "expected_scale": "10",
    "request_id": "manual_smoke_test",
    "catalog": "astroturf",
    "data_root": "/tmp/astroturf-web-job-smoke",
    "repo_path": ".",
    "vector_index_name": "",
    "clustering_mode": "local",
    "similarity_threshold": "0.92",
    "dry_run": "true",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test web_analysis_job parameter and input construction."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print constructed inputs without external calls.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Reserved for intentional live execution; not used by default.",
    )
    args = parser.parse_args()

    if not args.live:
        api_key = os.getenv("REGULATIONS_GOV_API_KEY") or "fake-smoke-test-key"
        sanitize_regulations_gov_api_key(api_key)
    elif not os.getenv("REGULATIONS_GOV_API_KEY"):
        raise RuntimeError("REGULATIONS_GOV_API_KEY is required for --live.")

    params = parse_web_analysis_params(SMOKE_PARAMS)
    paths = build_web_analysis_paths(params)
    agent_inputs = build_agent_inputs(params, paths)

    print("web_analysis_job smoke parameters parsed successfully")
    print(f"dry_run={args.dry_run or not args.live}")
    pprint.pprint(agent_inputs_as_safe_dict(agent_inputs), sort_dicts=True)

    if not args.live:
        print("Smoke test stopped before network, Databricks, and Delta calls.")
        return

    raise NotImplementedError(
        "--live is intentionally not implemented in the local smoke harness yet. "
        "Use the Databricks notebook for live execution after dry-run validation."
    )


if __name__ == "__main__":
    main()
