#!/usr/bin/env python3
"""scripts/run_attribution.py - Run AttributionAgent for one docket.

Default mode is ``offline_seed`` (ADR-0015). Other modes are accepted by the
agent but refuse to run until their tooling is configured.

Example:
    python scripts/run_attribution.py --docket-id 17-108 --mode offline_seed \\
        --max-clusters 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.attribution.agent import (
    DEFAULT_ATTRIBUTIONS_PATH,
    DEFAULT_CLUSTERS_PATH,
    DEFAULT_MEMBERSHIPS_PATH,
    DEFAULT_PARSED_COMMENTS_PATH,
    AttributionAgent,
    AttributionInput,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run AttributionAgent and write evidence packets to "
            "gold.campaign_attributions. See ADR-0015 — outputs are CANDIDATE "
            "origins with confidence labels, not accusations."
        )
    )
    parser.add_argument("--docket-id", required=True)
    parser.add_argument(
        "--mode",
        choices=("offline_seed", "web_research", "llm_assisted"),
        default="offline_seed",
    )
    parser.add_argument("--cluster-id", action="append", dest="cluster_ids")
    parser.add_argument("--max-clusters", type=int, default=None)
    parser.add_argument("--confidence-threshold", type=float, default=0.0)
    parser.add_argument("--seed-path", default=None)
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)
    parser.add_argument("--attributions-path", default=DEFAULT_ATTRIBUTIONS_PATH)
    parser.add_argument(
        "--no-replace-scope",
        action="store_true",
        help="Do not delete prior attribution rows before merging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    inputs = AttributionInput(
        docket_id=args.docket_id,
        cluster_ids=args.cluster_ids,
        max_clusters=args.max_clusters,
        mode=args.mode,
        confidence_threshold=args.confidence_threshold,
        seed_path=args.seed_path,
        clusters_path=args.clusters_path,
        memberships_path=args.memberships_path,
        parsed_comments_path=args.parsed_comments_path,
        attributions_path=args.attributions_path,
        replace_scope=not args.no_replace_scope,
    )
    output = AttributionAgent().run(inputs)
    print(
        json.dumps(
            {
                "docket_id": output.docket_id,
                "rows_written": output.rows_written,
                "metadata": output.metadata,
            },
            default=str,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
