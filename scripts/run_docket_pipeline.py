#!/usr/bin/env python3
"""scripts/run_docket_pipeline.py — Unified orchestration runner for Astroturf.

Accepts registered dockets from configs/dockets.yaml and coordinates multi-stage pipeline
execution (ingest, parse, embed, cluster, export) across local and Databricks modes.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mlflow
from shared.api_keys import resolve_data_gov_api_key

log = logging.getLogger("run_docket_pipeline")
VALID_STAGES = ("ingest", "parse", "embed", "cluster", "export")

# Allowed processing_status values for configs/dockets.yaml. Documented in
# docs/product/product-vision.md (UI coverage tiers map onto these in
# docs/product/ui-information-architecture.md).
#
# - configured_awaiting_run: registered in config (or via /analyze) but no
#   pipeline run has occurred yet. UI label: "Configured, awaiting run".
# - queued: scheduled for an upcoming run. UI label: "Queued".
# - partially_processed: some stages have completed, others have not yet.
#   UI label: "Partially processed".
# - baseline_only: exact-hash baseline available, semantic clustering not
#   yet promoted. UI label: "Baseline only".
# - analyzed: full semantic dossier available. UI label: "Analyzed".
ALLOWED_PROCESSING_STATUSES: frozenset[str] = frozenset(
    {
        "configured_awaiting_run",
        "queued",
        "partially_processed",
        "baseline_only",
        "analyzed",
    }
)


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


@dataclass(frozen=True)
class DocketConfig:
    docket_id: str
    source: str
    topic_id: str
    agency_id: str
    title: str
    date_window: dict[str, str | None]
    ingestion_mode: str
    expected_scale: int
    processing_status: str
    notes: str


def load_dockets_config(path: str) -> list[DocketConfig]:
    """Parse and validate configs/dockets.yaml without adding a YAML dependency."""
    if not Path(path).exists():
        raise FileNotFoundError(f"Dockets config not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    dockets: list[dict[str, Any]] = []
    current_docket: dict[str, Any] | None = None
    in_date_window = False

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Start of a new list item
        if line.startswith("- "):
            if current_docket is not None:
                dockets.append(current_docket)
            current_docket = {}
            in_date_window = False
            line = line[2:].strip()

        if current_docket is None:
            continue

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")

            # Handle nulls
            if val.lower() == "null" or val == "":
                val = None

            if key == "date_window":
                current_docket["date_window"] = {}
                in_date_window = True
            elif in_date_window and key in ("start_date", "end_date"):
                if "date_window" not in current_docket:
                    current_docket["date_window"] = {}
                current_docket["date_window"][key] = val
            else:
                # Try parsing integers
                if val is not None:
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                current_docket[key] = val

    if current_docket is not None:
        dockets.append(current_docket)

    return [_validate_docket_config(row, path) for row in dockets]


def _validate_docket_config(row: dict[str, Any], path: str) -> DocketConfig:
    required = {
        "docket_id",
        "source",
        "topic_id",
        "agency_id",
        "title",
        "date_window",
        "ingestion_mode",
        "expected_scale",
        "processing_status",
        "notes",
    }
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"{path}: docket entry is missing required fields {missing}")
    if row["source"] not in {"regulations_gov", "ecfs"}:
        raise ValueError(f"{path}: unsupported source for {row['docket_id']!r}")
    if row["processing_status"] not in ALLOWED_PROCESSING_STATUSES:
        raise ValueError(
            f"{path}: unsupported processing_status for {row['docket_id']!r}"
        )
    date_window = row.get("date_window") or {}
    return DocketConfig(
        docket_id=str(row["docket_id"]),
        source=str(row["source"]),
        topic_id=str(row["topic_id"]),
        agency_id=str(row["agency_id"]),
        title=str(row["title"]),
        date_window={
            "start_date": date_window.get("start_date"),
            "end_date": date_window.get("end_date"),
        },
        ingestion_mode=str(row["ingestion_mode"]),
        expected_scale=int(row["expected_scale"]),
        processing_status=str(row["processing_status"]),
        notes=str(row["notes"]),
    )


def validate_stages(stages: list[str]) -> list[str]:
    unknown = [stage for stage in stages if stage not in VALID_STAGES]
    if unknown:
        raise ValueError(
            f"Unknown stage(s): {', '.join(unknown)}. "
            f"Valid stages are: {', '.join(VALID_STAGES)}."
        )
    deduped: list[str] = []
    for stage in stages:
        if stage not in deduped:
            deduped.append(stage)
    if not deduped:
        raise ValueError("At least one stage must be selected.")
    return deduped


def build_execution_plan(
    *,
    docket_config: DocketConfig,
    mode: str,
    stages: list[str],
    limit: int | None,
    resume: bool,
    catalog: str,
    vector_index_name: str | None,
    data_root: str | None = None,
) -> list[dict[str, Any]]:
    model_name = (
        "databricks-bge-large-en" if mode == "databricks" else "BAAI/bge-large-en-v1.5"
    )
    plan = []
    for order, stage in enumerate(stages, start=1):
        plan.append(
            {
                "order": order,
                "stage": stage,
                "docket_id": docket_config.docket_id,
                "source": docket_config.source,
                "mode": mode,
                "limit": limit,
                "resume": resume,
                "embedding_model": model_name
                if stage in {"embed", "cluster", "export"}
                else None,
                "catalog": catalog if mode == "databricks" else None,
                "data_root": data_root if mode == "databricks" else None,
                "vector_index_name": (
                    vector_index_name
                    if mode == "databricks" and stage == "cluster"
                    else None
                ),
            }
        )
    return plan


def run_pipeline(
    *,
    docket_id: str,
    config_path: str,
    mode: str,
    stages: list[str],
    limit: int | None,
    resume: bool,
    dry_run: bool,
    catalog: str,
    vector_index_name: str | None,
    data_root: str | None,
) -> None:
    """Orchestrate existing agent modules sequentially."""
    stages = validate_stages(stages)
    docket_configs = load_dockets_config(config_path)
    docket_config = next((d for d in docket_configs if d.docket_id == docket_id), None)

    if not docket_config:
        raise ValueError(
            f"Docket ID '{docket_id}' is not registered in dockets config file: {config_path}"
        )

    log.info(
        "Preparing pipeline for docket=%s topic=%s agency=%s mode=%s stages=%s limit=%s",
        docket_id,
        docket_config.topic_id,
        docket_config.agency_id,
        mode,
        stages,
        limit,
    )

    plan = build_execution_plan(
        docket_config=docket_config,
        mode=mode,
        stages=stages,
        limit=limit,
        resume=resume,
        catalog=catalog,
        vector_index_name=vector_index_name,
        data_root=data_root,
    )
    if dry_run:
        print("DRY-RUN EXECUTION PLAN")
        print("=" * 50)
        for item in plan:
            print(
                f"{item['order']}. {item['stage']} "
                f"docket={item['docket_id']} mode={item['mode']} "
                f"limit={item['limit']} resume={item['resume']}"
            )
            if item.get("embedding_model"):
                print(f"   embedding_model={item['embedding_model']}")
            if item.get("vector_index_name"):
                print(f"   vector_index_name={item['vector_index_name']}")
            if item.get("data_root"):
                print(f"   data_root={item['data_root']}")
        print("=" * 50)

    # Set up pipeline table path properties based on mode
    if mode == "local":
        bronze_path = "./data/bronze/raw_comments"
        silver_path = "./data/silver/parsed_comments"
        details_path = "./data/silver/comment_details"
        attachments_path = "./data/silver/comment_attachments"
        embeddings_path = "./data/silver/comment_embeddings"
        clusters_path = "./data/gold/comment_clusters"
        memberships_path = "./data/gold/comment_cluster_memberships"
        export_path = "./data/exports/cluster_review_export"
    else:
        resolved_data_root = (
            data_root or f"/Volumes/{catalog}/demo/exports/_lakehouse"
        ).rstrip("/\\")
        bronze_path = f"{resolved_data_root}/bronze/raw_comments"
        silver_path = f"{resolved_data_root}/silver/parsed_comments"
        details_path = f"{resolved_data_root}/silver/comment_details"
        attachments_path = f"{resolved_data_root}/silver/comment_attachments"
        embeddings_path = f"{resolved_data_root}/silver/comment_embeddings"
        clusters_path = f"{resolved_data_root}/gold/comment_clusters"
        memberships_path = f"{resolved_data_root}/gold/comment_cluster_memberships"
        export_path = f"{catalog}.demo.cluster_review_export"

    # Verify credentials
    try:
        resolve_data_gov_api_key(required=True)
    except RuntimeError as e:
        log.warning("Data.gov API key check returned warning: %s", e)

    # Define MLflow Experiment
    mlflow.set_experiment(f"astroturf-{mode}-orchestration")

    # Parent pipeline run
    parent_run_name = f"pipeline-{docket_id}-{mode}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    with mlflow.start_run(run_name=parent_run_name):
        mlflow.log_param("docket_id", docket_id)
        mlflow.log_param("mode", mode)
        mlflow.log_param("stages", ",".join(stages))
        mlflow.log_param("limit", limit)
        mlflow.log_param("resume", resume)
        mlflow.log_param("dry_run", dry_run)
        mlflow.log_param("catalog", catalog)

        # STAGE 1: Ingestion
        if "ingest" in stages:
            log.info("STAGE 1: Ingestion starting...")
            from agents.ingestion.agent import IngestionAgent, IngestionInput

            start_date_obj = None
            end_date_obj = None
            if docket_config.date_window:
                sd = docket_config.date_window.get("start_date")
                ed = docket_config.date_window.get("end_date")
                if sd:
                    start_date_obj = date.fromisoformat(sd)
                if ed:
                    end_date_obj = date.fromisoformat(ed)

            ingest_inputs = IngestionInput(
                docket_id=docket_id,
                source=docket_config.source,
                max_comments=limit,
                start_date=start_date_obj,
                end_date=end_date_obj,
            )

            if dry_run:
                log.info("[DRY-RUN] Ingestion inputs: %s", ingest_inputs)
            else:
                agent = IngestionAgent(config={"bronze_path": bronze_path})
                agent.run(ingest_inputs)

        # STAGE 2: Parsing
        if "parse" in stages:
            log.info("STAGE 2: Parsing starting...")
            from agents.parser.agent import ParserAgent, ParserInput

            parse_inputs = ParserInput(
                docket_id=docket_id,
                bronze_path=bronze_path,
                silver_path=silver_path,
                details_path=details_path,
                attachments_path=attachments_path,
                max_rows=limit,
                force_enrich=not resume,
            )

            if dry_run:
                log.info("[DRY-RUN] Parsing inputs: %s", parse_inputs)
            else:
                agent = ParserAgent(
                    config={
                        "bronze_path": bronze_path,
                        "silver_path": silver_path,
                        "details_path": details_path,
                        "attachments_path": attachments_path,
                    }
                )
                agent.run(parse_inputs)

        # STAGE 3: Embedding
        model_name = (
            "databricks-bge-large-en"
            if mode == "databricks"
            else "BAAI/bge-large-en-v1.5"
        )
        if "embed" in stages:
            log.info("STAGE 3: Embedding starting...")
            from agents.embedding.agent import (
                DatabricksFoundationModelBackend,
                EmbeddingAgent,
                EmbeddingInput,
                LocalSentenceTransformerBackend,
            )

            if mode == "local":
                backend = LocalSentenceTransformerBackend(model_name=model_name)
            else:
                backend = DatabricksFoundationModelBackend(model_name=model_name)

            embed_inputs = EmbeddingInput(
                docket_id=docket_id,
                parsed_path=silver_path,
                embeddings_path=embeddings_path,
                model_name=model_name,
                max_rows=limit,
                force_reembed=not resume,
            )

            if dry_run:
                log.info(
                    "[DRY-RUN] Embedding inputs: %s with backend: %s",
                    embed_inputs,
                    backend.backend_name,
                )
            else:
                agent = EmbeddingAgent(backend=backend)
                agent.run(embed_inputs)

        # STAGE 4: Clustering
        if "cluster" in stages:
            log.info("STAGE 4: Clustering starting...")
            from agents.clustering.agent import ClusteringAgent, ClusteringInput

            clustering_version = (
                "v1_vector_search_cosine"
                if mode == "databricks"
                else "v1_connected_components_cosine"
            )
            cluster_inputs = ClusteringInput(
                docket_id=docket_id,
                embedding_model=model_name,
                embeddings_path=embeddings_path,
                clusters_path=clusters_path,
                memberships_path=memberships_path,
                clustering_version=clustering_version,
                max_rows=limit,
                clustering_mode="vector_search" if mode == "databricks" else "local",
                vector_index_name=vector_index_name if mode == "databricks" else None,
            )

            if dry_run:
                log.info("[DRY-RUN] Clustering inputs: %s", cluster_inputs)
            else:
                agent = ClusteringAgent()
                agent.run(cluster_inputs)

        # STAGE 5: Exporting
        if "export" in stages:
            log.info("STAGE 5: Exporting starting...")
            from scripts.export_to_demo_table import export_to_demo_table

            if dry_run:
                log.info(
                    "[DRY-RUN] Exporting docket %s with model %s to target %s",
                    docket_id,
                    model_name,
                    export_path,
                )
            else:
                export_to_demo_table(
                    docket_id=docket_id,
                    topic_id=docket_config.topic_id,
                    agency_id=docket_config.agency_id,
                    embedding_model=model_name,
                    similarity_threshold=0.92,
                    clusters_path=clusters_path,
                    memberships_path=memberships_path,
                    parsed_comments_path=silver_path,
                    raw_comments_path=bronze_path,
                    output_target=export_path,
                    mode=mode,
                    overwrite=True,
                )

        mlflow.log_param("status", "SUCCESS")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified end-to-end pipeline runner for federal docket coordination."
    )
    parser.add_argument(
        "--docket-id", required=True, help="Registered docket ID (e.g. 17-108)"
    )
    parser.add_argument(
        "--config", default="configs/dockets.yaml", help="Path to dockets yaml"
    )
    parser.add_argument(
        "--mode",
        choices=("local", "databricks"),
        default="local",
        help="Pipeline execution mode",
    )
    parser.add_argument(
        "--stages",
        default="ingest,parse,embed,cluster,export",
        help="Comma-separated list of stages to execute: ingest,parse,embed,cluster,export",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Truncate comments processing limit"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Utilize cached outputs instead of force overwrite",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print step arguments without executing"
    )
    parser.add_argument(
        "--catalog",
        default=os.environ.get("DATABRICKS_CATALOG", "workspace"),
        help="Unity Catalog target catalog. Default 'workspace'",
    )
    parser.add_argument(
        "--vector-index-name",
        default=os.environ.get(
            "ASTROTURF_VECTOR_INDEX_NAME",
            "workspace.silver.comment_embeddings_bge_large_index",
        ),
        help="Databricks Vector Search index for databricks cluster stage",
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("ASTROTURF_DATABRICKS_DATA_ROOT"),
        help=(
            "Databricks Volume-backed Delta root for agent reads/writes. "
            "Default: /Volumes/<catalog>/demo/exports/_lakehouse"
        ),
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    # Initialize Logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    load_simple_env()

    stages_list = validate_stages(
        [s.strip() for s in args.stages.split(",") if s.strip()]
    )

    try:
        run_pipeline(
            docket_id=args.docket_id,
            config_path=args.config,
            mode=args.mode,
            stages=stages_list,
            limit=args.limit,
            resume=args.resume,
            dry_run=args.dry_run,
            catalog=args.catalog,
            vector_index_name=args.vector_index_name,
            data_root=args.data_root,
        )
        print("\n" + "=" * 50)
        print("PIPELINE RUN COMPLETED SUCCESSFULLY")
        print("=" * 50)
    except Exception as e:
        log.exception("Orchestration pipeline encountered critical failure: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
