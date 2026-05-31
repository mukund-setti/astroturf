# Databricks notebook source
# MAGIC %md
# MAGIC # Astroturf - Databricks Workflow Tasks
# MAGIC
# MAGIC Source notebook for the `astroturf-cfpb-demo` Workflow. Each `# COMMAND`
# MAGIC cell below is a self-contained block intended to be promoted to its own
# MAGIC notebook task in the Workflow. Until then, the **task** widget at the top
# MAGIC selects which block(s) execute when this notebook is run as a whole.
# MAGIC
# MAGIC Tasks:
# MAGIC 1. `load_sample_tables` - register UC Delta tables over the Parquet sample
# MAGIC    uploaded to `astroturf.bronze.raw_imports`.
# MAGIC 2. `embed` - run `EmbeddingAgent` with `DatabricksFoundationModelBackend`
# MAGIC    against `astroturf.silver.parsed_comments`.
# MAGIC 3. `cluster` - run `ClusteringAgent` for one docket/model/threshold scope.
# MAGIC 4. `export_dashboard_data` - join clusters, memberships, parsed comments,
# MAGIC    and raw comment metadata into `astroturf.demo.cluster_review_export`.
# MAGIC
# MAGIC Runbook: `docs/databricks/workflow.md`.
# MAGIC Vector Search wiring (referenced by `embed`): `docs/databricks/vector-search.md`.

# COMMAND ----------
# MAGIC %md
# MAGIC ## Shared setup
# MAGIC Widgets used by every task. When promoting a cell to its own notebook,
# MAGIC copy this block plus the target cell. The `task` widget is only needed
# MAGIC while every block lives in one notebook; promoted notebooks can drop it.

# COMMAND ----------
dbutils.widgets.dropdown(
    "task",
    "all",
    ["all", "load_sample_tables", "embed", "cluster", "export_dashboard_data"],
    "Task to run",
)
dbutils.widgets.text("catalog", "astroturf", "Unity Catalog name")
dbutils.widgets.text("docket_id", "CFPB-2016-0025", "Docket ID")
dbutils.widgets.text(
    "data_root",
    "/Volumes/astroturf/demo/exports/_lakehouse",
    "Working lakehouse root (Volume path)",
)
dbutils.widgets.text(
    "repo_path",
    "/Workspace/Repos/<user>/astroturf",
    "Repo working directory on the cluster",
)
dbutils.widgets.text(
    "request_id",
    "",
    "Hosted web request ID. Must be blank for sample-loader workflow.",
)

import sys

task = dbutils.widgets.get("task")
catalog = dbutils.widgets.get("catalog")
docket_id = dbutils.widgets.get("docket_id")
data_root = dbutils.widgets.get("data_root").rstrip("/")
repo_path = dbutils.widgets.get("repo_path").rstrip("/")
request_id = dbutils.widgets.get("request_id").strip()

if request_id and task in ("all", "load_sample_tables"):
    raise ValueError(
        "Hosted analysis job cannot use sample-loader raw_imports path. "
        "Use web_analysis_job."
    )

if repo_path and repo_path not in sys.path:
    sys.path.insert(0, repo_path)


# Prioritize Databricks Serverless virtual environment dependencies in sys.path
import sys

venv_paths = [
    p for p in sys.path if "envs/pythonEnv-" in p and p.endswith("site-packages")
]
for p in venv_paths:
    try:
        sys.path.remove(p)
    except ValueError:
        pass
    sys.path.insert(0, p)

try:
    import pyarrow

    print(f"PyArrow version loaded: {pyarrow.__version__} from {pyarrow.__file__}")
except Exception as e:
    print(f"Failed to inspect PyArrow: {e}")


# Configure MLflow model registry URI bypass for Databricks Serverless (Spark Connect)
try:
    import mlflow
    import mlflow.tracking._model_registry.utils

    mlflow.tracking._model_registry.utils._get_registry_uri_from_spark_session = (
        lambda: "databricks-uc"
    )
    mlflow.set_registry_uri("databricks-uc")
    print("Successfully configured Databricks Serverless MLflow model registry bypass.")
except Exception as e:
    print(f"Warning: Failed to configure MLflow model registry bypass: {e}")

raw_comments_path = f"{data_root}/bronze/raw_comments"
parsed_path = f"{data_root}/silver/parsed_comments"
embeddings_path = f"{data_root}/silver/comment_embeddings"
clusters_path = f"{data_root}/gold/comment_clusters"
memberships_path = f"{data_root}/gold/comment_cluster_memberships"

print(f"task={task}")
print(f"catalog={catalog}")
print(f"docket_id={docket_id}")
print(f"data_root={data_root}")
print(f"raw_comments_path={raw_comments_path}")
print(f"parsed_path={parsed_path}")
print(f"embeddings_path={embeddings_path}")
print(f"clusters_path={clusters_path}")
print(f"memberships_path={memberships_path}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Task 1 - `load_sample_tables`
# MAGIC
# MAGIC Reads the Parquet sample uploaded to `astroturf.bronze.raw_imports`,
# MAGIC writes Delta files under `data_root`, and registers UC external tables
# MAGIC `astroturf.bronze.raw_comments` and `astroturf.silver.parsed_comments`.
# MAGIC
# MAGIC Expected Parquet layout inside the volume:
# MAGIC
# MAGIC ```text
# MAGIC /Volumes/astroturf/bronze/raw_imports/
# MAGIC   raw_comments/         # exported from local ./data/bronze/raw_comments
# MAGIC   parsed_comments/      # exported from local ./data/silver/parsed_comments
# MAGIC ```

# COMMAND ----------
if task in ("all", "load_sample_tables"):
    dbutils.widgets.text(
        "bronze_volume",
        "/Volumes/astroturf/bronze/raw_imports",
        "Bronze parquet upload volume",
    )
    bronze_volume = dbutils.widgets.get("bronze_volume").rstrip("/")

    import os

    def resolve_parquet_path(volume: str, table_key: str) -> str:
        candidates = [
            f"{volume}/{table_key}",
            f"{volume}/bronze.{table_key}"
            if "raw" in table_key
            else f"{volume}/silver.{table_key}",
            f"{volume}/uc_sample/{table_key}",
            f"{volume}/uc_sample/bronze.{table_key}"
            if "raw" in table_key
            else f"{volume}/uc_sample/silver.{table_key}",
        ]
        resolved = None
        for c in candidates:
            # 1. Try standard os.path.exists check (reliable for Volume mounts)
            try:
                if os.path.exists(c):
                    resolved = c
                    print(f"Resolved parquet source path via os.path.exists: {c}")
                    break
            except Exception:
                pass

            # 2. Try spark read check (failsafe validation)
            try:
                spark.read.parquet(c).limit(0).count()
                resolved = c
                print(f"Resolved parquet source path via spark.read validation: {c}")
                break
            except Exception:
                pass

        if not resolved:
            resolved = candidates[0]
            print(
                f"Warning: Could not confirm existence of candidate paths, defaulting fallback to: {resolved}"
            )
        return resolved

    spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.bronze")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.gold")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.demo")

    # Clean old directories to ensure we don't inherit the deletionVectors table feature in existing Delta logs
    import shutil

    for p in [
        raw_comments_path,
        parsed_path,
        embeddings_path,
        clusters_path,
        memberships_path,
    ]:
        try:
            shutil.rmtree(p)
            print(f"Cleaned FUSE path: {p}")
        except Exception as e:
            print(f"Path cleaning skipped for {p}: {e}")

    resolved_raw_path = resolve_parquet_path(bronze_volume, "raw_comments")
    raw_df = spark.read.parquet(resolved_raw_path)
    (
        raw_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .option("delta.enableDeletionVectors", "false")
        .save(raw_comments_path)
    )
    spark.sql(
        f"CREATE OR REPLACE VIEW {catalog}.bronze.raw_comments "
        f"AS SELECT * FROM delta.`{raw_comments_path}`"
    )

    resolved_parsed_path = resolve_parquet_path(bronze_volume, "parsed_comments")
    parsed_df = spark.read.parquet(resolved_parsed_path)
    (
        parsed_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .option("delta.enableDeletionVectors", "false")
        .save(parsed_path)
    )
    spark.sql(
        f"CREATE OR REPLACE VIEW {catalog}.silver.parsed_comments "
        f"AS SELECT * FROM delta.`{parsed_path}`"
    )

    raw_count = spark.table(f"{catalog}.bronze.raw_comments").count()
    parsed_count = spark.table(f"{catalog}.silver.parsed_comments").count()
    print(f"{catalog}.bronze.raw_comments rows: {raw_count}")
    print(f"{catalog}.silver.parsed_comments rows: {parsed_count}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Task 2 - `embed`
# MAGIC
# MAGIC Runs `EmbeddingAgent` with `DatabricksFoundationModelBackend` against
# MAGIC `astroturf.silver.parsed_comments`, MERGEs results into
# MAGIC `astroturf.silver.comment_embeddings`, and registers the UC external
# MAGIC table over the Delta location. Emits one MLflow run with
# MAGIC `backend = databricks_foundation_model`,
# MAGIC `embedding_model = databricks-bge-large-en`, and Foundation Model
# MAGIC latency / retry metrics (see `agents/embedding/agent.py`).
# MAGIC
# MAGIC Vector Search index sync (model-filtered slice
# MAGIC `astroturf.silver.comment_embeddings_bge_large_index`) is **out of scope**
# MAGIC for this cell. See `docs/databricks/vector-search.md` for the index setup
# MAGIC owned by Agent 1.

# COMMAND ----------
if task in ("all", "embed"):
    dbutils.widgets.text(
        "embedding_model",
        "databricks-bge-large-en",
        "Foundation Model name",
    )
    dbutils.widgets.text("embedding_batch_size", "16", "Batch size")
    dbutils.widgets.text("embedding_max_rows", "", "Max rows (blank = all)")
    dbutils.widgets.dropdown(
        "force_reembed",
        "false",
        ["true", "false"],
        "Force re-embed cached rows",
    )

    embedding_model = dbutils.widgets.get("embedding_model")
    embedding_batch_size = int(dbutils.widgets.get("embedding_batch_size") or "16")
    _max_rows_str = dbutils.widgets.get("embedding_max_rows").strip()
    embedding_max_rows = int(_max_rows_str) if _max_rows_str else None
    force_reembed = dbutils.widgets.get("force_reembed").lower() == "true"

    from agents.embedding.agent import (
        DatabricksFoundationModelBackend,
        EmbeddingAgent,
        EmbeddingInput,
    )

    backend = DatabricksFoundationModelBackend(model_name=embedding_model)
    agent = EmbeddingAgent(backend=backend)
    embed_output = agent.run(
        EmbeddingInput(
            docket_id=docket_id,
            parsed_path=parsed_path,
            embeddings_path=embeddings_path,
            model_name=embedding_model,
            batch_size=embedding_batch_size,
            max_rows=embedding_max_rows,
            force_reembed=force_reembed,
        )
    )

    spark.sql(
        f"CREATE OR REPLACE VIEW {catalog}.silver.comment_embeddings "
        f"AS SELECT * FROM delta.`{embeddings_path}`"
    )

    print(f"rows_written={embed_output.rows_written}")
    print(f"metadata={embed_output.metadata}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Task 3 - `cluster`
# MAGIC
# MAGIC Runs `ClusteringAgent` against the Databricks-produced embeddings for one
# MAGIC `(docket_id, embedding_model, similarity_threshold)` scope and MERGEs
# MAGIC rows into `astroturf.gold.comment_clusters` and
# MAGIC `astroturf.gold.comment_cluster_memberships`. Emits a second MLflow run
# MAGIC with `candidates_total`, `edge_count_above_threshold`, `clusters_written`,
# MAGIC and `memberships_written`.

# COMMAND ----------
if task in ("all", "cluster"):
    dbutils.widgets.text(
        "cluster_embedding_model",
        "databricks-bge-large-en",
        "Embedding model slice to cluster",
    )
    dbutils.widgets.text("similarity_threshold", "0.92", "Cosine similarity threshold")
    dbutils.widgets.text("min_cluster_size", "2", "Minimum cluster size")
    dbutils.widgets.text("clustering_max_rows", "", "Max rows (blank = all)")
    dbutils.widgets.text(
        "clustering_version",
        "v1_vector_search_cosine",
        "Clustering version tag",
    )
    dbutils.widgets.dropdown(
        "clustering_mode",
        "vector_search",
        ["vector_search", "local"],
        "Candidate retrieval mode",
    )
    dbutils.widgets.text(
        "vector_index_name",
        f"{catalog}.silver.comment_embeddings_bge_large_index",
        "Vector Search index name",
    )
    dbutils.widgets.dropdown(
        "allow_mock",
        "false",
        ["true", "false"],
        "Allow mock-backend embeddings",
    )

    cluster_embedding_model = dbutils.widgets.get("cluster_embedding_model")
    similarity_threshold = float(dbutils.widgets.get("similarity_threshold") or "0.92")
    min_cluster_size = int(dbutils.widgets.get("min_cluster_size") or "2")
    _cmax_str = dbutils.widgets.get("clustering_max_rows").strip()
    clustering_max_rows = int(_cmax_str) if _cmax_str else None
    clustering_version = dbutils.widgets.get("clustering_version")
    clustering_mode = dbutils.widgets.get("clustering_mode")
    vector_index_name = dbutils.widgets.get("vector_index_name").strip() or None
    allow_mock = dbutils.widgets.get("allow_mock").lower() == "true"

    from agents.clustering.agent import ClusteringAgent, ClusteringInput

    cluster_agent = ClusteringAgent()
    cluster_output = cluster_agent.run(
        ClusteringInput(
            docket_id=docket_id,
            embedding_model=cluster_embedding_model,
            embeddings_path=embeddings_path,
            clusters_path=clusters_path,
            memberships_path=memberships_path,
            clustering_version=clustering_version,
            similarity_threshold=similarity_threshold,
            min_cluster_size=min_cluster_size,
            max_rows=clustering_max_rows,
            allow_mock=allow_mock,
            clustering_mode=clustering_mode,
            vector_index_name=vector_index_name,
        )
    )

    spark.sql(
        f"CREATE OR REPLACE VIEW {catalog}.gold.comment_clusters "
        f"AS SELECT * FROM delta.`{clusters_path}`"
    )
    spark.sql(
        f"CREATE OR REPLACE VIEW {catalog}.gold.comment_cluster_memberships "
        f"AS SELECT * FROM delta.`{memberships_path}`"
    )

    print(f"rows_written={cluster_output.rows_written}")
    print(f"metadata={cluster_output.metadata}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Task 4 - `export_dashboard_data`
# MAGIC
# MAGIC Builds the UI-facing join `astroturf.demo.cluster_review_export` for one
# MAGIC `(docket_id, embedding_model, similarity_threshold)` scope. Column set
# MAGIC matches `shared/schemas/cluster_review_export.py`; the SQL CTAS replaces
# MAGIC the table each run so the dashboard always sees the latest scope.

# COMMAND ----------
if task in ("all", "export_dashboard_data"):
    dbutils.widgets.text(
        "export_embedding_model",
        "databricks-bge-large-en",
        "Embedding model slice to export",
    )
    dbutils.widgets.text(
        "export_similarity_threshold",
        "0.92",
        "Cosine similarity threshold to export",
    )

    export_embedding_model = dbutils.widgets.get("export_embedding_model")
    export_similarity_threshold = float(
        dbutils.widgets.get("export_similarity_threshold") or "0.92"
    )

    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.demo")
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE {catalog}.demo.cluster_review_export AS
        SELECT
            c.cluster_id,
            c.docket_id,
            c.embedding_model,
            c.similarity_threshold,
            c.cluster_size,
            c.representative_comment_id,
            m.comment_id,
            CAST(m.comment_id = c.representative_comment_id AS BOOLEAN)
                AS is_representative,
            m.text_source,
            SUBSTR(
                REGEXP_REPLACE(COALESCE(p.raw_text, p.normalized_text, ''), '\\\\s+', ' '),
                1,
                500
            ) AS text_preview,
            r.submitter_name,
            p.posted_date,
            CASE
                WHEN c.embedding_backend = 'exact_hash' THEN 'exact_hash'
                ELSE 'semantic'
            END AS source,
            CURRENT_TIMESTAMP() AS exported_at
        FROM {catalog}.gold.comment_clusters c
        JOIN {catalog}.gold.comment_cluster_memberships m
            ON c.cluster_id = m.cluster_id
        LEFT JOIN {catalog}.silver.parsed_comments p
            ON m.comment_id = p.comment_id
        LEFT JOIN {catalog}.bronze.raw_comments r
            ON m.comment_id = r.comment_id
        WHERE c.docket_id = '{docket_id}'
          AND c.embedding_model = '{export_embedding_model}'
          AND ABS(c.similarity_threshold - {export_similarity_threshold}) < 1e-9
        """
    )

    export_count = spark.table(f"{catalog}.demo.cluster_review_export").count()
    cluster_count = spark.sql(
        f"SELECT COUNT(DISTINCT cluster_id) AS n "
        f"FROM {catalog}.demo.cluster_review_export"
    ).first()["n"]
    print(f"{catalog}.demo.cluster_review_export rows: {export_count}")
    print(f"{catalog}.demo.cluster_review_export distinct clusters: {cluster_count}")
