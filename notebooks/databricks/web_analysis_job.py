# Databricks notebook source
# MAGIC %md
# MAGIC # Astroturf - Web Analysis Job
# MAGIC
# MAGIC Production entrypoint for hosted `/analyze` requests. This notebook is
# MAGIC intentionally separate from `workflow_tasks.py`: it ingests from public
# MAGIC source APIs and does not read pre-uploaded `bronze.raw_imports` Parquet
# MAGIC sample folders.

# COMMAND ----------
dbutils.widgets.text("docket_id", "", "Docket ID")
dbutils.widgets.dropdown(
    "source", "regulations_gov", ["regulations_gov", "ecfs"], "Source"
)
dbutils.widgets.text("topic_id", "", "Topic ID")
dbutils.widgets.text("agency_id", "", "Agency ID")
dbutils.widgets.text("start_date", "", "Start date (YYYY-MM-DD)")
dbutils.widgets.text("end_date", "", "End date (YYYY-MM-DD)")
dbutils.widgets.text("expected_scale", "1000", "Max comments to ingest")
dbutils.widgets.text("request_id", "", "Web analysis request ID")
dbutils.widgets.text("catalog", "astroturf", "Unity Catalog name")
dbutils.widgets.dropdown("dry_run", "false", ["true", "false"], "Construct only")
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
    "vector_index_name",
    "",
    "Vector Search index name; blank uses <catalog>.silver.comment_embeddings_bge_large_index",
)
dbutils.widgets.dropdown(
    "clustering_mode",
    "vector_search",
    ["vector_search", "local"],
    "Clustering mode",
)
dbutils.widgets.text("similarity_threshold", "0.92", "Cosine similarity threshold")

# COMMAND ----------
import os
import pprint
import sys


def _widget(name: str) -> str:
    return dbutils.widgets.get(name).strip()


repo_path = _widget("repo_path").rstrip("/\\")

if repo_path and repo_path not in sys.path:
    sys.path.insert(0, repo_path)

# Prioritize Databricks Serverless virtual environment dependencies in sys.path.
venv_paths = [
    p for p in sys.path if "envs/pythonEnv-" in p and p.endswith("site-packages")
]
for path in venv_paths:
    try:
        sys.path.remove(path)
    except ValueError:
        pass
    sys.path.insert(0, path)


def _configure_regulations_gov_api_key() -> None:
    api_key = os.getenv("REGULATIONS_GOV_API_KEY")
    if api_key:
        api_key = _sanitize_regulations_gov_api_key(api_key)
        os.environ["REGULATIONS_GOV_API_KEY"] = api_key
        os.environ["DATA_GOV_API_KEY"] = api_key
        print("Regulations.gov API key source: env")
        return

    try:
        api_key = dbutils.secrets.get("astroturf", "regulations-gov-api-key")
    except Exception as exc:
        raise RuntimeError(
            "REGULATIONS_GOV_API_KEY is not set and Databricks secret "
            "astroturf/regulations-gov-api-key could not be read."
        ) from exc

    api_key = _sanitize_regulations_gov_api_key(api_key)
    os.environ["REGULATIONS_GOV_API_KEY"] = api_key
    os.environ["DATA_GOV_API_KEY"] = api_key
    print("Regulations.gov API key source: databricks_secret")


def _sanitize_regulations_gov_api_key(value: str | None) -> str:
    from scripts.web_analysis_job_support import sanitize_regulations_gov_api_key

    return sanitize_regulations_gov_api_key(value)


_configure_regulations_gov_api_key()

from scripts.web_analysis_job_support import (
    EMBEDDING_MODEL,
    agent_inputs_as_safe_dict,
    build_agent_inputs,
    build_web_analysis_paths,
    parse_web_analysis_params,
)

params = parse_web_analysis_params(
    {
        "docket_id": _widget("docket_id"),
        "source": _widget("source"),
        "topic_id": _widget("topic_id"),
        "agency_id": _widget("agency_id"),
        "start_date": _widget("start_date"),
        "end_date": _widget("end_date"),
        "expected_scale": _widget("expected_scale"),
        "request_id": _widget("request_id"),
        "catalog": _widget("catalog") or "astroturf",
        "data_root": _widget("data_root"),
        "repo_path": repo_path,
        "vector_index_name": _widget("vector_index_name"),
        "clustering_mode": _widget("clustering_mode"),
        "similarity_threshold": _widget("similarity_threshold"),
        "dry_run": _widget("dry_run"),
    }
)
paths = build_web_analysis_paths(params)
agent_inputs = build_agent_inputs(params, paths)

docket_id = params.docket_id
source = params.source
topic_id = params.topic_id
agency_id = params.agency_id
request_id = params.request_id
catalog = params.catalog
data_root = params.data_root
max_comments = params.expected_scale
embedding_model = EMBEDDING_MODEL
similarity_threshold = params.similarity_threshold
clustering_mode = params.clustering_mode

raw_comments_path = paths.raw_comments_path
parsed_path = paths.parsed_path
details_path = paths.details_path
attachments_path = paths.attachments_path
embeddings_path = paths.embeddings_path
clusters_path = paths.clusters_path
memberships_path = paths.memberships_path

print("Astroturf hosted web analysis job")
print(f"request_id={request_id}")
print(f"docket_id={docket_id}")
print(f"source={source}")
print(f"topic_id={topic_id}")
print(f"agency_id={agency_id}")
print(f"expected_scale={max_comments}")
print(f"catalog={catalog}")
print(f"data_root={data_root}")
print(f"clustering_mode={clustering_mode}")

if params.dry_run:
    print("dry_run=true")
    pprint.pprint(agent_inputs_as_safe_dict(agent_inputs), sort_dicts=True)
    dbutils.notebook.exit("Dry run completed before external calls.")


# COMMAND ----------
def _sql_identifier(value: str, *, param_name: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"{param_name} must be an alphanumeric SQL identifier.")
    return value


def _sql_string(value: str) -> str:
    return value.replace("'", "''")


def _create_uc_objects() -> None:
    safe_catalog = _sql_identifier(catalog, param_name="catalog")
    try:
        spark.sql(f"CREATE CATALOG IF NOT EXISTS {safe_catalog}")
    except Exception as exc:
        print(
            "CREATE CATALOG skipped or failed. Continuing to USE CATALOG so an "
            f"existing catalog can still run. Detail: {exc}"
        )
    spark.sql(f"USE CATALOG {safe_catalog}")

    for schema_name in ["bronze", "silver", "gold", "demo"]:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {safe_catalog}.{schema_name}")

    if data_root.startswith("/Volumes/"):
        parts = data_root.split("/")
        if len(parts) < 5:
            raise ValueError(
                "data_root under /Volumes must look like "
                "/Volumes/<catalog>/<schema>/<volume>/..."
            )
        volume_catalog, volume_schema, volume_name = parts[2], parts[3], parts[4]
        _sql_identifier(volume_catalog, param_name="data_root catalog")
        _sql_identifier(volume_schema, param_name="data_root schema")
        _sql_identifier(volume_name, param_name="data_root volume")
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {volume_catalog}.{volume_schema}")
        spark.sql(
            f"CREATE VOLUME IF NOT EXISTS "
            f"{volume_catalog}.{volume_schema}.{volume_name}"
        )

    os.makedirs(data_root, exist_ok=True)


def _register_delta_view(full_name: str, path: str) -> None:
    spark.sql(f"CREATE OR REPLACE VIEW {full_name} AS SELECT * FROM delta.`{path}`")
    row_count = spark.table(full_name).count()
    print(f"{full_name} rows: {row_count}")


_create_uc_objects()

# COMMAND ----------
try:
    import mlflow
    import mlflow.tracking._model_registry.utils

    mlflow.tracking._model_registry.utils._get_registry_uri_from_spark_session = (
        lambda: "databricks-uc"
    )
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment("astroturf-web-analysis")
except Exception as exc:
    print(f"Warning: MLflow setup failed; agents may still create runs. Detail: {exc}")

# COMMAND ----------
print("Stage 1/5: API ingestion")
from agents.ingestion.agent import IngestionAgent

ingestion_output = IngestionAgent(config={"bronze_path": raw_comments_path}).run(
    agent_inputs.ingestion
)
print(f"ingestion rows_written={ingestion_output.rows_written}")
print(f"ingestion metadata={ingestion_output.metadata}")
_register_delta_view(f"{catalog}.bronze.raw_comments", raw_comments_path)

# COMMAND ----------
print("Stage 2/5: parsing")
from agents.parser.agent import ParserAgent

parser_output = ParserAgent(
    config={
        "bronze_path": raw_comments_path,
        "silver_path": parsed_path,
        "details_path": details_path,
        "attachments_path": attachments_path,
    }
).run(agent_inputs.parser)
print(f"parser rows_written={parser_output.rows_written}")
print(f"parser metadata={parser_output.metadata}")
_register_delta_view(f"{catalog}.silver.parsed_comments", parsed_path)

# COMMAND ----------
print("Stage 3/5: Databricks Foundation Model embedding")
from agents.embedding.agent import (
    DatabricksFoundationModelBackend,
    EmbeddingAgent,
)

embedding_output = EmbeddingAgent(
    backend=DatabricksFoundationModelBackend(model_name=embedding_model)
).run(agent_inputs.embedding)
print(f"embedding rows_written={embedding_output.rows_written}")
print(f"embedding metadata={embedding_output.metadata}")
_register_delta_view(f"{catalog}.silver.comment_embeddings", embeddings_path)

# COMMAND ----------
print("Stage 4/5: clustering")
from agents.clustering.agent import ClusteringAgent

clustering_output = ClusteringAgent().run(agent_inputs.clustering)
print(f"clustering rows_written={clustering_output.rows_written}")
print(f"clustering metadata={clustering_output.metadata}")
_register_delta_view(f"{catalog}.gold.comment_clusters", clusters_path)
_register_delta_view(f"{catalog}.gold.comment_cluster_memberships", memberships_path)

# COMMAND ----------
print("Stage 5/5: export dashboard data")
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
    WHERE c.docket_id = '{_sql_string(docket_id)}'
      AND c.embedding_model = '{_sql_string(embedding_model)}'
      AND ABS(c.similarity_threshold - {similarity_threshold}) < 1e-9
    """
)

export_count = spark.table(f"{catalog}.demo.cluster_review_export").count()
cluster_count = spark.sql(
    f"SELECT COUNT(DISTINCT cluster_id) AS n FROM {catalog}.demo.cluster_review_export"
).first()["n"]
print(f"{catalog}.demo.cluster_review_export rows: {export_count}")
print(f"{catalog}.demo.cluster_review_export distinct clusters: {cluster_count}")
print("Hosted web analysis job completed successfully.")
