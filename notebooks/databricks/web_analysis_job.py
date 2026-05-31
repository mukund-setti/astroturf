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
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date
from typing import Any, Mapping


def _widget(name: str) -> str:
    return dbutils.widgets.get(name).strip()


repo_path = _widget("repo_path").rstrip("/\\")

# Prioritize Databricks Serverless virtual environment dependencies, then force
# the uploaded repo root ahead of them for project module imports.
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

import agents.ingestion.agent as ingestion_agent_module
from agents.ingestion.agent import IngestionInput

print(f"DEBUG repo_path={repo_path}", flush=True)
print(f"DEBUG sys.path[0:5]={sys.path[0:5]}", flush=True)
print(
    "DEBUG ingestion agent module path="
    f"{getattr(ingestion_agent_module, '__file__', 'NO_FILE')}",
    flush=True,
)
print(
    f"DEBUG IngestionInput fields={[field.name for field in fields(IngestionInput)]}",
    flush=True,
)


EMBEDDING_MODEL = "databricks-bge-large-en"


@dataclass(frozen=True)
class WebAnalysisJobParams:
    docket_id: str
    source: str
    topic_id: str
    agency_id: str
    start_date: date | None
    end_date: date | None
    expected_scale: int
    request_id: str
    catalog: str
    data_root: str
    repo_path: str
    vector_index_name: str
    clustering_mode: str
    similarity_threshold: float
    dry_run: bool


@dataclass(frozen=True)
class WebAnalysisPaths:
    raw_comments_path: str
    parsed_path: str
    details_path: str
    attachments_path: str
    embeddings_path: str
    clusters_path: str
    memberships_path: str


@dataclass(frozen=True)
class WebAnalysisAgentInputs:
    ingestion: Any
    parser: Any
    embedding: Any
    clustering: Any


def _sanitize_regulations_gov_api_key(value: str | None) -> str:
    api_key = (value or "").strip().replace("\x00", "")
    if not api_key:
        raise RuntimeError(
            "REGULATIONS_GOV_API_KEY resolved but is empty after sanitization."
        )
    return api_key


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


def _required(raw: Mapping[str, str], name: str) -> str:
    value = _optional(raw, name)
    if not value:
        raise ValueError(f"Missing required Databricks job parameter: {name}")
    return value


def _optional(raw: Mapping[str, str], name: str) -> str:
    return str(raw.get(name, "")).strip()


def _optional_date(name: str, value: str) -> date | None:
    if not value or value.lower() == "null":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Databricks job parameter {name}={value!r}; expected YYYY-MM-DD."
        ) from exc


def _expected_scale(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Databricks job parameter expected_scale={value!r}; "
            "expected integer."
        ) from exc
    if parsed < 1:
        raise ValueError("expected_scale must be at least 1.")
    return parsed


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y"}


def _parse_web_analysis_params(raw: Mapping[str, str]) -> WebAnalysisJobParams:
    docket_id = _required(raw, "docket_id")
    source = _required(raw, "source")
    topic_id = _required(raw, "topic_id")
    agency_id = _required(raw, "agency_id")
    request_id = _required(raw, "request_id")
    catalog = _required(raw, "catalog")
    data_root = _required(raw, "data_root").rstrip("/\\")
    repo_path_value = _required(raw, "repo_path").rstrip("/\\")

    if source not in {"regulations_gov", "ecfs"}:
        raise ValueError(
            f"Unsupported source={source!r}. Supported hosted web analysis sources "
            "are 'regulations_gov' and 'ecfs'."
        )

    if data_root.startswith("/Volumes/") and "/bronze/raw_imports" in data_root:
        raise ValueError(
            "Hosted analysis job cannot use sample-loader raw_imports path. "
            "Use web_analysis_job."
        )

    vector_index_name = _optional(raw, "vector_index_name")
    if not vector_index_name:
        vector_index_name = f"{catalog}.silver.comment_embeddings_bge_large_index"

    clustering_mode_value = _optional(raw, "clustering_mode") or "vector_search"
    if clustering_mode_value not in {"vector_search", "local"}:
        raise ValueError("clustering_mode must be either 'vector_search' or 'local'.")

    return WebAnalysisJobParams(
        docket_id=docket_id,
        source=source,
        topic_id=topic_id,
        agency_id=agency_id,
        start_date=_optional_date("start_date", _optional(raw, "start_date")),
        end_date=_optional_date("end_date", _optional(raw, "end_date")),
        expected_scale=_expected_scale(_optional(raw, "expected_scale") or "1000"),
        request_id=request_id,
        catalog=catalog,
        data_root=data_root,
        repo_path=repo_path_value,
        vector_index_name=vector_index_name,
        clustering_mode=clustering_mode_value,
        similarity_threshold=float(_optional(raw, "similarity_threshold") or "0.92"),
        dry_run=_parse_bool(_optional(raw, "dry_run")),
    )


def _build_web_analysis_paths(params: WebAnalysisJobParams) -> WebAnalysisPaths:
    data_root_value = params.data_root
    return WebAnalysisPaths(
        raw_comments_path=f"{data_root_value}/bronze/raw_comments",
        parsed_path=f"{data_root_value}/silver/parsed_comments",
        details_path=f"{data_root_value}/silver/comment_details",
        attachments_path=f"{data_root_value}/silver/comment_attachments",
        embeddings_path=f"{data_root_value}/silver/comment_embeddings",
        clusters_path=f"{data_root_value}/gold/comment_clusters",
        memberships_path=f"{data_root_value}/gold/comment_cluster_memberships",
    )


def _build_agent_inputs(
    params: WebAnalysisJobParams,
    paths: WebAnalysisPaths,
) -> WebAnalysisAgentInputs:
    from agents.clustering.agent import ClusteringInput
    from agents.embedding.agent import EmbeddingInput
    from agents.ingestion.agent import IngestionInput
    from agents.parser.agent import ParserInput

    ingestion_values = {
        "docket_id": params.docket_id,
        "source": params.source,
        "max_comments": params.expected_scale,
        "start_date": params.start_date,
        "end_date": params.end_date,
    }
    parser_values = {
        "docket_id": params.docket_id,
        "bronze_path": paths.raw_comments_path,
        "silver_path": paths.parsed_path,
        "details_path": paths.details_path,
        "attachments_path": paths.attachments_path,
        "max_rows": params.expected_scale,
        "force_enrich": False,
    }
    embedding_values = {
        "docket_id": params.docket_id,
        "parsed_path": paths.parsed_path,
        "embeddings_path": paths.embeddings_path,
        "model_name": EMBEDDING_MODEL,
        "batch_size": 16,
        "max_rows": params.expected_scale,
        "force_reembed": False,
    }
    clustering_values = {
        "docket_id": params.docket_id,
        "embedding_model": EMBEDDING_MODEL,
        "embeddings_path": paths.embeddings_path,
        "clusters_path": paths.clusters_path,
        "memberships_path": paths.memberships_path,
        "clustering_version": (
            "v1_vector_search_cosine"
            if params.clustering_mode == "vector_search"
            else "v1_connected_components_cosine"
        ),
        "similarity_threshold": params.similarity_threshold,
        "max_rows": params.expected_scale,
        "allow_mock": False,
        "clustering_mode": params.clustering_mode,
        "vector_index_name": (
            params.vector_index_name
            if params.clustering_mode == "vector_search"
            else None
        ),
    }

    return WebAnalysisAgentInputs(
        ingestion=_construct_dataclass(IngestionInput, ingestion_values),
        parser=_construct_dataclass(ParserInput, parser_values),
        embedding=_construct_dataclass(EmbeddingInput, embedding_values),
        clustering=_construct_dataclass(ClusteringInput, clustering_values),
    )


def _agent_inputs_as_safe_dict(inputs: WebAnalysisAgentInputs) -> dict[str, Any]:
    return {
        "ingestion": asdict(inputs.ingestion),
        "parser": asdict(inputs.parser),
        "embedding": asdict(inputs.embedding),
        "clustering": asdict(inputs.clustering),
    }


def _construct_dataclass(cls: type[Any], values: dict[str, Any]) -> Any:
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} must be a dataclass.")

    field_names = {field.name for field in fields(cls)}
    unknown = sorted(set(values) - field_names)
    if unknown:
        raise RuntimeError(
            f"{cls.__name__} does not define expected field(s): {unknown}. "
            "Sync the Databricks repo/job code with the local repository."
        )
    return cls(**values)


_configure_regulations_gov_api_key()

params = _parse_web_analysis_params(
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
paths = _build_web_analysis_paths(params)
agent_inputs = _build_agent_inputs(params, paths)

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
    pprint.pprint(_agent_inputs_as_safe_dict(agent_inputs), sort_dicts=True)
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


def _register_delta_view(full_name: str, path: str) -> int:
    spark.sql(f"CREATE OR REPLACE VIEW {full_name} AS SELECT * FROM delta.`{path}`")
    row_count = spark.table(full_name).count()
    print(f"{full_name} rows: {row_count}")
    return int(row_count)


def _register_delta_view_if_exists(full_name: str, path: str) -> int | None:
    """Same as ``_register_delta_view`` but silently skips if the Delta path
    has not been written yet.

    Used for tables the parser only populates conditionally (for example
    ``silver.comment_details`` and ``silver.comment_attachments``, which
    ParserAgent skips for ECFS rows entirely). Registering the view in
    advance — when the path exists — means downstream consumers can rely
    on the view name being present without the notebook having to know
    every agent's write pattern.
    """
    try:
        spark.read.format("delta").load(path).limit(0).collect()
    except Exception as exc:
        print(
            f"Skipping view registration for {full_name}; Delta path not yet "
            f"materialised at {path}: {exc.__class__.__name__}"
        )
        return None
    return _register_delta_view(full_name, path)


def _count_docket_rows(full_name: str, docket_value: str) -> int:
    """Count rows in a registered Delta view that belong to a specific docket.

    The bronze and silver tables accumulate across dockets, so the
    total row count of the underlying Delta path is not a safe signal
    that *this* docket produced reviewable rows. We always filter by
    ``docket_id`` so a zero-row analysis is detected even when other
    dockets have populated the same lakehouse path.
    """

    safe_docket = _sql_string(docket_value)
    row = spark.sql(
        f"SELECT COUNT(*) AS n FROM {full_name} WHERE docket_id = '{safe_docket}'"
    ).first()
    row_count = int(row["n"]) if row is not None else 0
    print(f"{full_name} rows for docket_id={docket_value!r}: {row_count}")
    return row_count


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
raw_comment_count = _count_docket_rows(f"{catalog}.bronze.raw_comments", docket_id)
if raw_comment_count == 0:
    raise RuntimeError(
        "No raw comments were ingested for "
        f"docket_id={docket_id!r}, source={source!r}. "
        "The bronze.raw_comments table has zero rows for this docket. "
        "Refusing to mark this hosted analysis as successful: this is "
        "a no-data run, not a campaign dashboard. Common causes: an "
        "unsupported docket/source pair, an upstream API outage, or "
        "no public comments yet posted for the docket."
    )

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
# silver.comment_details and silver.comment_attachments are only populated
# by ParserAgent v2A for regulations.gov rows (ECFS path skips the detail
# fetch entirely; see ADR-0012). Register the views conditionally so the
# names exist as soon as the underlying paths do, without failing the run
# on docket types that don't materialise them.
_register_delta_view_if_exists(f"{catalog}.silver.comment_details", details_path)
_register_delta_view_if_exists(
    f"{catalog}.silver.comment_attachments", attachments_path
)
parsed_comment_count = _count_docket_rows(
    f"{catalog}.silver.parsed_comments", docket_id
)
if parsed_comment_count == 0:
    raise RuntimeError(
        "No parsed comments were produced for "
        f"docket_id={docket_id!r}, source={source!r}. "
        f"Bronze had {raw_comment_count} raw rows but silver.parsed_comments "
        "has zero rows for this docket. Refusing to mark this hosted "
        "analysis as successful: parsing eliminated every row, so there is "
        "nothing to embed, cluster, or review."
    )

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

# Per-docket-safe export. The export is a single denormalized table holding rows
# for every analyzed docket, keyed logically by (docket_id, cluster_id, comment_id).
# Using CREATE OR REPLACE TABLE would wipe every prior docket on every run, so
# instead we (a) create the table the first time it is needed, and (b) on
# subsequent runs delete only this docket's rows and re-insert them. Other
# dockets' rows are untouched.
export_table = f"{catalog}.demo.cluster_review_export"
export_select_sql = f"""
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

if spark.catalog.tableExists(export_table):
    spark.sql(
        f"DELETE FROM {export_table} WHERE docket_id = '{_sql_string(docket_id)}'"
    )
    spark.sql(f"INSERT INTO {export_table} {export_select_sql}")
else:
    spark.sql(f"CREATE TABLE {export_table} AS {export_select_sql}")

export_count = spark.table(f"{catalog}.demo.cluster_review_export").count()
cluster_count = spark.sql(
    f"SELECT COUNT(DISTINCT cluster_id) AS n FROM {catalog}.demo.cluster_review_export"
).first()["n"]
print(f"{catalog}.demo.cluster_review_export rows: {export_count}")
print(f"{catalog}.demo.cluster_review_export distinct clusters: {cluster_count}")
print("Hosted web analysis job completed successfully.")
