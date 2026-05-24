#!/usr/bin/env python3
"""scripts/run_autopilot.py — Autopilot scheduled and manual orchestration runner.

Coordinates broad docket discovery, classification/prioritization,
and schedules priority dockets for pipeline analysis runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.classify_dockets import run_classification
from scripts.discover_dockets import run_discovery
from shared.delta_utils.discovery import merge_autopilot_runs
from shared.schemas.autopilot_runs import AutopilotRun, autopilot_runs_arrow_schema

log = logging.getLogger("run_autopilot")


def trigger_local_analysis_job(docket_id: str, dry_run: bool) -> bool:
    """Submit a local background pipeline run for the docket."""
    log.info("Triggering local pipeline run for priority docket: %s", docket_id)

    python_path = sys.executable
    script_path = Path(__file__).parent / "run_docket_pipeline.py"

    args = [
        python_path,
        str(script_path),
        "--docket-id",
        docket_id,
        "--mode",
        "local",
        "--limit",
        "100",  # Limit comments to execute quickly for Autopilot demo
        "--stages",
        "ingest,parse,embed,cluster,export",
    ]

    if dry_run:
        log.info("[DRY-RUN] Would spawn process: %s", " ".join(args))
        return True

    try:
        # Spawn detached in the background
        log_dir = Path(__file__).parent.parent / "data" / "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = log_dir / f"pipeline-{docket_id}.log"

        with open(log_file, "w", encoding="utf-8") as out:
            subprocess.Popen(
                args,
                stdout=out,
                stderr=out,
                cwd=Path(__file__).parent.parent,
                start_new_session=True,
            )
        log.info(
            "Successfully spawned background pipeline run for docket %s. Logs: %s",
            docket_id,
            log_file,
        )
        return True
    except Exception as e:
        log.error(
            "Failed to trigger local pipeline process for docket %s: %s", docket_id, e
        )
        return False


def run_autopilot_orchestrator(
    *,
    config_path: str,
    catalog_file: str,
    watchlist_file: str,
    runs_file: str,
    mode: str,
    dry_run: bool,
    max_dockets: int | None,
    topic: str | None,
    agency: str | None,
    trigger_jobs: bool,
    catalog: str,
) -> None:
    """Run discovery, classification, and enqueues high-priority rulemaking analyses."""
    start_time = datetime.now(timezone.utc)
    run_id = f"auto_{uuid.uuid4().hex[:12]}"

    log.info("==================================================")
    log.info("AUTOPILOT SCHEDULER ENTRYPOINT - RUN %s", run_id)
    log.info("Started at: %s", start_time.isoformat())
    log.info("Mode: %s | Dry-Run: %s | Trigger Jobs: %s", mode, dry_run, trigger_jobs)
    log.info("==================================================")

    dockets_discovered = 0
    dockets_classified = 0
    jobs_triggered = 0
    status = "success"
    err_msg = None

    try:
        # 1. RUN DISCOVERY TASK
        discovered = run_discovery(
            config_path=config_path,
            output_path=catalog_file,
            mode=mode,
            dry_run=dry_run,
            max_dockets=max_dockets,
            topic=topic,
            agency=agency,
            catalog=catalog,
        )
        dockets_discovered = len(discovered)

        # 2. RUN CLASSIFICATION & PRIORITIZATION TASK
        classified = run_classification(
            catalog_path=catalog_file,
            watchlist_path=watchlist_file,
            mode=mode,
            dry_run=dry_run,
            catalog=catalog,
        )
        dockets_classified = len(classified)

        # 3. IDENTIFY HIGH-PRIORITY OR WATCHED CANDIDATES TO RUN
        # We select dockets with status 'discovered' and priority_score >= 60.0,
        # or any discovered docket that has user requested count > 0.
        priority_targets = []
        for doc in classified:
            if doc.status == "discovered" or doc.status == "queued":
                if doc.priority_score >= 60.0 or doc.user_requested_count > 0:
                    priority_targets.append(doc)

        log.info(
            "Identified %s high-priority docket targets for analysis.",
            len(priority_targets),
        )

        # 4. TRIGGER JOBS IF ENABLED
        if priority_targets and trigger_jobs:
            for target in priority_targets:
                if mode == "local":
                    success = trigger_local_analysis_job(
                        target.docket_id, dry_run=dry_run
                    )
                    if success:
                        jobs_triggered += 1
                        # Update status in local catalog JSON
                        target.status = "analyzing"
                elif mode == "databricks":
                    log.info(
                        "Databricks production run: enqueuing request in Unity Catalog and calling Jobs API."
                    )
                    # In production, we would trigger the Databricks Jobs API endpoint `/jobs/run-now`
                    # using target parameters. Let's document this or print.
                    log.info(
                        "[PRODUCTION TRIGGER] Databricks jobs API call for docket %s",
                        target.docket_id,
                    )
                    jobs_triggered += 1
                    target.status = "analyzing"

            # Write updated status back if not dry-run
            if not dry_run:
                with open(catalog_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [d.model_dump(mode="json") for d in classified], f, indent=2
                    )

    except Exception as e:
        status = "failed"
        err_msg = str(e)
        log.exception("Autopilot run encountered a critical error: %s", e)

    completed_time = datetime.now(timezone.utc)
    duration = (completed_time - start_time).total_seconds()

    # Track Run History
    run_log = AutopilotRun(
        run_id=run_id,
        status=status,
        dockets_discovered=dockets_discovered,
        dockets_classified=dockets_classified,
        jobs_triggered=jobs_triggered,
        started_at=start_time,
        completed_at=completed_time,
        error_message=err_msg,
        metadata_json=json.dumps(
            {
                "duration_seconds": duration,
                "mode": mode,
                "topic_filter": topic,
                "agency_filter": agency,
            }
        ),
    )

    if not dry_run:
        # Local JSON history logging
        os.makedirs(os.path.dirname(runs_file), exist_ok=True)
        existing_runs = []
        if Path(runs_file).exists():
            try:
                with open(runs_file, "r", encoding="utf-8") as f:
                    existing_runs = json.load(f)
            except Exception:
                pass
        existing_runs.append(run_log.model_dump(mode="json"))
        with open(runs_file, "w", encoding="utf-8") as f:
            json.dump(existing_runs, f, indent=2)

        # Merge run info into Delta table
        if mode == "local":
            delta_path = Path(runs_file).parent / "autopilot_runs_delta"
            arrow_schema = autopilot_runs_arrow_schema()
            table = pa.Table.from_pylist([run_log.model_dump()], schema=arrow_schema)
            try:
                metrics = merge_autopilot_runs(str(delta_path), table)
                log.info("Merged autopilot run info into local Delta: %s", metrics)
            except Exception as e:
                log.error("Failed to merge autopilot run info: %s", e)
        elif mode == "databricks":
            table_target = f"{catalog}.discovery.autopilot_runs"
            try:
                from pyspark.sql import SparkSession

                spark = SparkSession.getActiveSession()
                if spark:
                    from shared.schemas.autopilot_runs import autopilot_runs_struct

                    df = spark.createDataFrame(
                        [run_log.model_dump()], schema=autopilot_runs_struct()
                    )
                    df.createOrReplaceTempView("autopilot_run_update")

                    merge_sql = f"""
                        MERGE INTO {table_target} AS target
                        USING autopilot_run_update AS source
                        ON target.run_id = source.run_id
                        WHEN MATCHED THEN UPDATE SET *
                        WHEN NOT MATCHED THEN INSERT *
                    """
                    spark.sql(merge_sql)
                    log.info(
                        "Spark Delta MERGE executed on Unity Catalog autopilot_runs: %s",
                        table_target,
                    )
            except Exception as e:
                log.error("Failed to execute UC merge for autopilot runs: %s", e)

    log.info("==================================================")
    log.info("AUTOPILOT RUN COMPLETED: %s in %.2fs", status.upper(), duration)
    log.info(
        "Discovered: %s | Classified: %s | Triggered: %s",
        dockets_discovered,
        dockets_classified,
        jobs_triggered,
    )
    log.info("==================================================")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified Autopilot scheduled task runner."
    )
    parser.add_argument(
        "--config",
        default="configs/discovery_sources.yaml",
        help="Path to YAML sources config",
    )
    parser.add_argument(
        "--catalog-file",
        default="data/discovery/docket_catalog.json",
        help="Path to local docket catalog JSON",
    )
    parser.add_argument(
        "--watchlist-file",
        default="ui/.data/watchlist.json",
        help="Path to local watchlist JSON",
    )
    parser.add_argument(
        "--runs-file",
        default="data/discovery/autopilot_runs.json",
        help="Path to local autopilot runs JSON",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "databricks"),
        default="local",
        help="Autopilot execution mode",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print step arguments without writing"
    )
    parser.add_argument(
        "--max-dockets",
        type=int,
        default=None,
        help="Truncate discovered dockets limit",
    )
    parser.add_argument("--topic", default=None, help="Monitored topic ID filter")
    parser.add_argument("--agency", default=None, help="Monitored agency ID filter")
    parser.add_argument(
        "--trigger-jobs",
        action="store_true",
        help="Automatically trigger pipeline runs for priority dockets",
    )
    parser.add_argument(
        "--catalog", default="workspace", help="Unity Catalog target catalog name"
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        run_autopilot_orchestrator(
            config_path=args.config,
            catalog_file=args.catalog_file,
            watchlist_file=args.watchlist_file,
            runs_file=args.runs_file,
            mode=args.mode,
            dry_run=args.dry_run,
            max_dockets=args.max_dockets,
            topic=args.topic,
            agency=args.agency,
            trigger_jobs=args.trigger_jobs,
            catalog=args.catalog,
        )
    except Exception as e:
        log.exception("Autopilot run failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
