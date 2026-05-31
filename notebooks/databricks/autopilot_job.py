# Databricks notebook source
# MAGIC %md
# MAGIC # Astroturf — Autopilot Discovery & Classification Job
# MAGIC
# MAGIC Scheduled entrypoint for the Autopilot workflow. Runs
# MAGIC `scripts/run_autopilot.py::run_autopilot_orchestrator` in Databricks
# MAGIC mode, populating Unity Catalog Delta tables:
# MAGIC
# MAGIC   - `<catalog>.discovery.docket_catalog`
# MAGIC   - `<catalog>.discovery.autopilot_runs`
# MAGIC
# MAGIC The UI's `listDiscoveredDockets()` seeds Supabase Postgres from the
# MAGIC `discovery.docket_catalog` Delta table the first time `/discoveries`
# MAGIC loads with an empty cache, so populating Delta indirectly populates
# MAGIC the dashboard.

# COMMAND ----------
dbutils.widgets.text("catalog", "astroturf", "Unity Catalog name")
dbutils.widgets.text(
    "repo_path",
    "/Workspace/Users/mukund.setti@gmail.com/astroturf",
    "Repo working directory",
)
dbutils.widgets.dropdown(
    "trigger_jobs", "false", ["true", "false"], "Auto-trigger priority analysis runs"
)
dbutils.widgets.text("max_dockets", "25", "Max discovered dockets per sweep")
dbutils.widgets.dropdown(
    "dry_run", "false", ["true", "false"], "Construct only (no writes)"
)

# COMMAND ----------
import os
import sys


def _widget(name: str) -> str:
    return dbutils.widgets.get(name).strip()


repo_path = _widget("repo_path").rstrip("/\\")
catalog = _widget("catalog")
trigger_jobs = _widget("trigger_jobs").lower() in {"1", "true", "yes", "y"}
dry_run = _widget("dry_run").lower() in {"1", "true", "yes", "y"}
max_dockets = int(_widget("max_dockets") or "25")

# Force the uploaded repo root ahead of any Databricks Serverless site-packages
# so project modules import from /Workspace/... not from random venv builds.
venv_paths = [
    p for p in sys.path if "envs/pythonEnv-" in p and p.endswith("site-packages")
]
for path in venv_paths:
    try:
        sys.path.remove(path)
    except ValueError:
        pass
    sys.path.insert(0, path)

if repo_path:
    if repo_path in sys.path:
        sys.path.remove(repo_path)
    sys.path.insert(0, repo_path)

print(f"DEBUG repo_path={repo_path}", flush=True)
print(f"DEBUG sys.path[0:3]={sys.path[0:3]}", flush=True)

# Resolve data.gov API key — same Databricks Secret as web_analysis_job.
try:
    api_key = dbutils.secrets.get("astroturf", "regulations-gov-api-key")
    os.environ["REGULATIONS_GOV_API_KEY"] = api_key.strip().replace("\x00", "")
    os.environ["DATA_GOV_API_KEY"] = os.environ["REGULATIONS_GOV_API_KEY"]
    print("Regulations.gov API key source: databricks_secret")
except Exception as exc:
    # Discovery can still run via the deterministic fallback dockets if the
    # key is missing, so log and continue rather than abort.
    print(
        f"Warning: could not load regulations-gov-api-key secret ({exc}). "
        "Discovery will fall back to the seed-docket catalog."
    )

# COMMAND ----------
# MLflow registry binding (same shape as web_analysis_job).
try:
    import mlflow
    import mlflow.tracking._model_registry.utils

    mlflow.tracking._model_registry.utils._get_registry_uri_from_spark_session = (
        lambda: "databricks-uc"
    )
    mlflow.set_registry_uri("databricks-uc")
except Exception as exc:
    print(f"Warning: MLflow registry binding failed: {exc}")

# COMMAND ----------
# Ensure the discovery schema AND target Delta tables exist before the
# orchestrator runs. run_autopilot.py uses MERGE INTO, which requires the
# target to already exist — without these CREATE TABLE IF NOT EXISTS calls
# the first-ever run silently writes nothing.
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.discovery")

from shared.schemas.autopilot_runs import autopilot_runs_struct
from shared.schemas.docket_catalog import docket_catalog_struct


def _ensure_delta_table(full_name: str, struct) -> None:
    if spark.catalog.tableExists(full_name):
        return
    empty_df = spark.createDataFrame([], schema=struct)
    empty_df.write.format("delta").mode("overwrite").saveAsTable(full_name)
    print(f"Created empty Delta table: {full_name}")


_ensure_delta_table(f"{catalog}.discovery.docket_catalog", docket_catalog_struct())
_ensure_delta_table(f"{catalog}.discovery.autopilot_runs", autopilot_runs_struct())
print(f"Ensured {catalog}.discovery schema and target tables exist.")

# COMMAND ----------
import logging

from scripts.run_autopilot import run_autopilot_orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Workspace-relative paths for the local JSON artefacts the orchestrator also
# writes. These land under the repo path on the driver volume — harmless side
# output that helps post-run debugging from the workspace file browser.
run_autopilot_orchestrator(
    config_path=f"{repo_path}/configs/discovery_sources.yaml",
    catalog_file=f"{repo_path}/data/discovery/docket_catalog.json",
    watchlist_file=f"{repo_path}/ui/.data/watchlist.json",
    runs_file=f"{repo_path}/data/discovery/autopilot_runs.json",
    mode="databricks",
    dry_run=dry_run,
    max_dockets=max_dockets,
    topic=None,
    agency=None,
    trigger_jobs=trigger_jobs,
    catalog=catalog,
)

# COMMAND ----------
# Sanity-check what landed in Unity Catalog so the run output makes the result
# legible without needing the catalog explorer.
print("\n=== Post-run catalog state ===")
spark.sql(
    f"SELECT docket_id, source, agency_id, topic_id, status, priority_score "
    f"FROM {catalog}.discovery.docket_catalog "
    f"ORDER BY priority_score DESC LIMIT 25"
).show(truncate=False)

run_count = spark.sql(
    f"SELECT COUNT(*) AS n FROM {catalog}.discovery.autopilot_runs"
).first()["n"]
print(f"{catalog}.discovery.autopilot_runs row count: {run_count}")

dbutils.notebook.exit("autopilot sweep completed")
