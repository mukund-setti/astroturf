#!/usr/bin/env python3
"""scripts/run_migration.py - Run MigrationAgent for one docket.

Default mode is ``local_text`` (ADR-0015). Other modes are accepted by the
agent but refuse to run until their tooling is configured.

Example:
    python scripts/run_migration.py --docket-id 17-108 --mode local_text \\
        --final-rule-text evals/fixtures/migration/fcc_17_108_final_rule_excerpt.txt \\
        --max-clusters 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.migration.agent import (
    DEFAULT_CLUSTERS_PATH,
    DEFAULT_MEMBERSHIPS_PATH,
    DEFAULT_MIGRATIONS_PATH,
    DEFAULT_PARSED_COMMENTS_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    MigrationAgent,
    MigrationInput,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run MigrationAgent and write language-overlap evidence to "
            "gold.rule_migrations. See ADR-0015 — outputs are phrase-level "
            "matches with mandatory caveats. They do NOT prove causality."
        )
    )
    parser.add_argument("--docket-id", required=True)
    parser.add_argument(
        "--mode",
        choices=("local_text", "federal_register_api"),
        default="local_text",
    )
    parser.add_argument(
        "--final-rule-text",
        dest="final_rule_text_path",
        default=None,
        help="Path to local final-rule text fixture (required in local_text mode).",
    )
    parser.add_argument("--final-rule-url", default=None)
    parser.add_argument("--final-rule-document-id", default="")
    parser.add_argument("--cluster-id", action="append", dest="cluster_ids")
    parser.add_argument("--max-clusters", type=int, default=None)
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
    )
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)
    parser.add_argument("--migrations-path", default=DEFAULT_MIGRATIONS_PATH)
    parser.add_argument(
        "--no-replace-scope",
        action="store_true",
        help="Do not delete prior migration rows before merging.",
    )
    parser.add_argument("--max-rows-per-cluster", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    inputs = MigrationInput(
        docket_id=args.docket_id,
        final_rule_text_path=args.final_rule_text_path,
        final_rule_document_id=args.final_rule_document_id,
        final_rule_url=args.final_rule_url,
        cluster_ids=args.cluster_ids,
        max_clusters=args.max_clusters,
        mode=args.mode,
        similarity_threshold=args.similarity_threshold,
        clusters_path=args.clusters_path,
        memberships_path=args.memberships_path,
        parsed_comments_path=args.parsed_comments_path,
        migrations_path=args.migrations_path,
        replace_scope=not args.no_replace_scope,
        max_rows_per_cluster=args.max_rows_per_cluster,
    )
    output = MigrationAgent().run(inputs)
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
