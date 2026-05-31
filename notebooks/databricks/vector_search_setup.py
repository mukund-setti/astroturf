# Databricks notebook source
# MAGIC %md
# MAGIC # Vector Search v1 setup (reviewer-only)
# MAGIC
# MAGIC Companion notebook for [`docs/databricks/vector-search.md`](../../docs/databricks/vector-search.md).
# MAGIC
# MAGIC This notebook executes the 8-step runbook end-to-end on a Databricks
# MAGIC cluster. It is **not** meant to run locally. It does not modify any code
# MAGIC under `agents/` and it does not wire Vector Search into
# MAGIC `ClusteringAgent` — that is Phase 2 (see ADR-0007).
# MAGIC
# MAGIC Strategy source for table names and filter values:
# MAGIC [`docs/databricks/integration.md`](../../docs/databricks/integration.md)
# MAGIC (section: **Vector Search mapping**).
# MAGIC
# MAGIC Steps:
# MAGIC
# MAGIC 1. Confirm Unity Catalog objects.
# MAGIC 2. Create the model-filtered source view.
# MAGIC 3. Apply and sanity-check the model-specific filter.
# MAGIC 4. Enable Delta change data feed on the source if required.
# MAGIC 5. Create the endpoint and the index.
# MAGIC 6. Trigger a manual sync.
# MAGIC 7. Run one similarity query.
# MAGIC 8. Capture artifacts.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Constants
# MAGIC
# MAGIC All names match `docs/databricks/integration.md` verbatim. Do not rename
# MAGIC without updating the runbook and ADR-0007.

# COMMAND ----------

CATALOG = "workspace"
SILVER_SCHEMA = "silver"

BASE_EMBEDDINGS_TABLE = f"{CATALOG}.{SILVER_SCHEMA}.comment_embeddings"
PARSED_COMMENTS_TABLE = f"{CATALOG}.{SILVER_SCHEMA}.parsed_comments"
FILTERED_SOURCE_VIEW = f"{CATALOG}.{SILVER_SCHEMA}.comment_embeddings_bge_large"

VS_ENDPOINT_NAME = "astroturf-vs-endpoint"
VS_INDEX_NAME = f"{CATALOG}.{SILVER_SCHEMA}.comment_embeddings_bge_large_index"

EMBEDDING_MODEL = "databricks-bge-large-en"
EMBEDDING_DIM = 1024
EMBEDDING_BACKEND = "databricks_foundation_model"
PRIMARY_KEY = "comment_id"
EMBEDDING_COLUMN = "embedding_vector"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Confirm Unity Catalog objects
# MAGIC
# MAGIC Verify the catalog/schema/table layout exists. If any of these fail,
# MAGIC stop and fix the upstream promotion (see
# MAGIC `docs/databricks/integration.md` -> Unity Catalog layout) before continuing.

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW SCHEMAS IN workspace;

# COMMAND ----------

# MAGIC %sql
# MAGIC DESCRIBE TABLE workspace.silver.comment_embeddings;

# COMMAND ----------

# MAGIC %sql
# MAGIC DESCRIBE TABLE workspace.silver.parsed_comments;

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Create the model-filtered source view
# MAGIC
# MAGIC `workspace.silver.comment_embeddings_bge_large` is the fixed-dimension
# MAGIC slice that Vector Search will index. A view is preferred over a
# MAGIC materialized table for v1: the slice is small and the filter is trivial.
# MAGIC If the sync mode in Step 6 requires a managed Delta table instead,
# MAGIC swap `CREATE OR REPLACE VIEW` for `CREATE OR REPLACE TABLE` and
# MAGIC document the choice in run notes.

# COMMAND ----------

for cmd in [
    "DROP VIEW IF EXISTS workspace.silver.comment_embeddings_bge_large",
    "DROP TABLE IF EXISTS workspace.silver.comment_embeddings_bge_large",
]:
    try:
        spark.sql(cmd)
    except Exception:
        pass


# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE workspace.silver.comment_embeddings_bge_large AS
# MAGIC SELECT
# MAGIC   comment_id,
# MAGIC   docket_id,
# MAGIC   embedding_model,
# MAGIC   embedding_dim,
# MAGIC   text_hash,
# MAGIC   text_source,
# MAGIC   embedding_vector,
# MAGIC   embedded_at,
# MAGIC   backend
# MAGIC FROM workspace.silver.comment_embeddings
# MAGIC WHERE embedding_model = 'databricks-bge-large-en'
# MAGIC   AND embedding_dim = 1024
# MAGIC   AND backend = 'databricks_foundation_model';

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Apply and sanity-check the model-specific filter
# MAGIC
# MAGIC All five checks must pass before creating the index:
# MAGIC
# MAGIC 1. Row count is non-zero and matches the curated sample.
# MAGIC 2. `MIN(embedding_dim) = MAX(embedding_dim) = 1024`.
# MAGIC 3. Exactly one `embedding_model`, value `databricks-bge-large-en`.
# MAGIC 4. Exactly one `backend`, value `databricks_foundation_model`.
# MAGIC 5. `comment_id` is unique inside the slice.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   COUNT(*)                       AS row_count,
# MAGIC   COUNT(DISTINCT comment_id)     AS distinct_comment_ids,
# MAGIC   MIN(embedding_dim)             AS min_dim,
# MAGIC   MAX(embedding_dim)             AS max_dim,
# MAGIC   COUNT(DISTINCT embedding_model) AS distinct_models,
# MAGIC   COUNT(DISTINCT backend)        AS distinct_backends
# MAGIC FROM workspace.silver.comment_embeddings_bge_large;

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT DISTINCT embedding_model, backend, embedding_dim
# MAGIC FROM workspace.silver.comment_embeddings_bge_large;

# COMMAND ----------

# Programmatic guardrail: fail the notebook here if any sanity check fails.
# This keeps a broken slice from reaching the index.

from pyspark.sql import functions as F  # noqa: E402

_slice = spark.table(FILTERED_SOURCE_VIEW)
_row_count = _slice.count()
_distinct_ids = _slice.select(PRIMARY_KEY).distinct().count()
_dim_stats = _slice.agg(
    F.min("embedding_dim").alias("min_dim"),
    F.max("embedding_dim").alias("max_dim"),
).collect()[0]
_models = [r[0] for r in _slice.select("embedding_model").distinct().collect()]
_backends = [r[0] for r in _slice.select("backend").distinct().collect()]

assert _row_count > 0, "Filtered slice is empty — embeddings not promoted?"
assert _distinct_ids == _row_count, (
    f"comment_id not unique in slice: {_distinct_ids} distinct vs {_row_count} rows"
)
assert (
    _dim_stats["min_dim"] == EMBEDDING_DIM and _dim_stats["max_dim"] == EMBEDDING_DIM
), f"embedding_dim drift: min={_dim_stats['min_dim']} max={_dim_stats['max_dim']}"
assert _models == [EMBEDDING_MODEL], f"unexpected embedding_model values: {_models}"
assert _backends == [EMBEDDING_BACKEND], f"unexpected backend values: {_backends}"

f"Slice OK: {_row_count} rows, dim={EMBEDDING_DIM}, model={EMBEDDING_MODEL}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Enable Delta change data feed on the source
# MAGIC
# MAGIC Vector Search syncs from a Delta source generally require CDF on the
# MAGIC underlying table. The filtered view in Step 2 reads from
# MAGIC `workspace.silver.comment_embeddings`, so set the property on the base
# MAGIC table. If you materialized the filtered slice as its own Delta table,
# MAGIC set CDF on that table instead.

# COMMAND ----------

# MAGIC %python
# MAGIC import re
# MAGIC # 1. Enable CDF on underlying base embeddings Delta table path
# MAGIC try:
# MAGIC     tbl_desc = spark.sql(f"SHOW CREATE TABLE {BASE_EMBEDDINGS_TABLE}").collect()[0][0]
# MAGIC     match = re.search(r"delta\.`([^`]+)`", tbl_desc)
# MAGIC     if match:
# MAGIC         resolved_target = f"delta.`{match.group(1)}`"
# MAGIC     else:
# MAGIC         resolved_target = BASE_EMBEDDINGS_TABLE
# MAGIC except Exception:
# MAGIC     resolved_target = BASE_EMBEDDINGS_TABLE
# MAGIC
# MAGIC print(f"Enabling Change Data Feed on base target: {resolved_target}")
# MAGIC spark.sql(f"ALTER TABLE {resolved_target} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
# MAGIC
# MAGIC # 2. Enable CDF on the filtered table
# MAGIC print(f"Enabling Change Data Feed on filtered table: {FILTERED_SOURCE_VIEW}")
# MAGIC try:
# MAGIC     spark.sql(f"ALTER TABLE {FILTERED_SOURCE_VIEW} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
# MAGIC except Exception as e:
# MAGIC     print(f"Warning: Could not enable CDF directly on {FILTERED_SOURCE_VIEW}: {e}")

# COMMAND ----------

# MAGIC %python
# MAGIC print("Base table properties:")
# MAGIC display(spark.sql(f"SHOW TBLPROPERTIES {resolved_target}"))
# MAGIC print("Filtered table properties:")
# MAGIC display(spark.sql(f"SHOW TBLPROPERTIES {FILTERED_SOURCE_VIEW}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Create the endpoint and the index
# MAGIC
# MAGIC Uses the Databricks Vector Search Python SDK. The endpoint is created
# MAGIC if missing; if it already exists the call is a no-op. The index is
# MAGIC created with **triggered** sync (manual sync is the v1 mode — see
# MAGIC Step 6).

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient  # noqa: E402

vsc = VectorSearchClient()

_existing_endpoints = {ep["name"] for ep in vsc.list_endpoints().get("endpoints", [])}
if VS_ENDPOINT_NAME not in _existing_endpoints:
    vsc.create_endpoint(name=VS_ENDPOINT_NAME, endpoint_type="STANDARD")
    vsc.wait_for_endpoint(name=VS_ENDPOINT_NAME, verbose=True)
else:
    vsc.wait_for_endpoint(name=VS_ENDPOINT_NAME, verbose=True)

f"Endpoint ready: {VS_ENDPOINT_NAME}"

# COMMAND ----------

_existing_indexes = {
    ix["name"]
    for ix in vsc.list_indexes(name=VS_ENDPOINT_NAME).get("vector_indexes", [])
}
if VS_INDEX_NAME not in _existing_indexes:
    vsc.create_delta_sync_index(
        endpoint_name=VS_ENDPOINT_NAME,
        index_name=VS_INDEX_NAME,
        source_table_name=FILTERED_SOURCE_VIEW,
        pipeline_type="TRIGGERED",
        primary_key=PRIMARY_KEY,
        embedding_vector_column=EMBEDDING_COLUMN,
        embedding_dimension=EMBEDDING_DIM,
    )

f"Index requested: {VS_INDEX_NAME}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Trigger a manual sync
# MAGIC
# MAGIC Triggered / manual sync is the v1 mode. Wait for the index to become
# MAGIC ready before querying. Re-running this cell on an unchanged source is
# MAGIC a no-op for query results — the operator can rerun the notebook safely.

# COMMAND ----------

import time  # noqa: E402

index = vsc.get_index(endpoint_name=VS_ENDPOINT_NAME, index_name=VS_INDEX_NAME)
try:
    print("Triggering index sync...")
    index.sync()
except Exception as e:
    print(
        f"Note: Sync trigger returned: {e}. Moving to polling loop to wait for index readiness."
    )

# Poll until the index reports a ready/online status. Record duration for
# the artifacts in Step 8.
_t0 = time.time()
_timeout_s = 30 * 60
while True:
    _desc = index.describe()
    _status = (_desc.get("status") or {}).get("detailed_state") or _desc.get("status")
    _ready = (_desc.get("status") or {}).get("ready", False)
    if _ready:
        break
    if time.time() - _t0 > _timeout_s:
        raise TimeoutError(
            f"Vector Search index sync timed out after {_timeout_s}s: {_status}"
        )
    time.sleep(15)

_sync_seconds = round(time.time() - _t0, 1)
f"Index ready after {_sync_seconds}s — capture this number for Step 8."

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 — Run one similarity query
# MAGIC
# MAGIC Pick a substantive sample `comment_id` from `silver.parsed_comments`,
# MAGIC look up its embedding from the filtered slice, query the index for its
# MAGIC nearest neighbors, and join back to `parsed_comments` so a reviewer can
# MAGIC read the previews.
# MAGIC
# MAGIC The query comment should appear as the top result with the highest
# MAGIC similarity score. The remaining neighbors should look topically related.

# COMMAND ----------

# Choose any substantive comment from the curated sample. Override SAMPLE_COMMENT_ID
# manually below if a specific evidence comment is preferred for the demo.
SAMPLE_COMMENT_ID: str | None = None
NUM_RESULTS = 10
PREVIEW_CHARS = 240

if SAMPLE_COMMENT_ID is None:
    _candidate = (
        spark.table(PARSED_COMMENTS_TABLE)
        .where(F.col("normalized_text").isNotNull())
        .where(F.length("normalized_text") > 200)
        .select("comment_id")
        .limit(1)
        .collect()
    )
    if not _candidate:
        raise RuntimeError(
            "No substantive parsed comments found — embed the sample first."
        )
    SAMPLE_COMMENT_ID = _candidate[0]["comment_id"]

SAMPLE_COMMENT_ID

# COMMAND ----------

_query_row = (
    spark.table(FILTERED_SOURCE_VIEW)
    .where(F.col("comment_id") == SAMPLE_COMMENT_ID)
    .select("embedding_vector")
    .collect()
)
if not _query_row:
    raise RuntimeError(
        f"comment_id {SAMPLE_COMMENT_ID} not present in {FILTERED_SOURCE_VIEW} — "
        "is it in the embedded slice?"
    )
_query_vector = list(_query_row[0]["embedding_vector"])

_results = index.similarity_search(
    query_vector=_query_vector,
    columns=["comment_id", "docket_id", "embedding_model"],
    num_results=NUM_RESULTS,
)

_data = (_results.get("result") or {}).get("data_array") or []
_columns = [c["name"] for c in (_results.get("manifest") or {}).get("columns", [])]
_neighbors = spark.createDataFrame(_data, _columns)

_previewed = (
    _neighbors.alias("n")
    .join(
        spark.table(PARSED_COMMENTS_TABLE)
        .select(
            F.col("comment_id"),
            F.col("title"),
            F.substring("normalized_text", 1, PREVIEW_CHARS).alias("preview"),
        )
        .alias("p"),
        on="comment_id",
        how="left",
    )
    .orderBy(
        F.col("score").desc_nulls_last() if "score" in _neighbors.columns else F.lit(1)
    )
)

display(_previewed)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 — Capture artifacts
# MAGIC
# MAGIC For the Student Fellows submission, capture:
# MAGIC
# MAGIC - Screenshot of the Vector Search index page showing source table/view,
# MAGIC   primary key (`comment_id`), embedding column (`embedding_vector`),
# MAGIC   embedding dimension (1024), and the `READY`/`ONLINE` state.
# MAGIC - Screenshot or saved output of the Step 7 similarity query showing the
# MAGIC   query comment, its top neighbors, similarity scores, and the joined
# MAGIC   `parsed_comments` preview.
# MAGIC - Row count of the indexed slice (printed in Step 3) and the sync
# MAGIC   duration in seconds (printed in Step 6).
# MAGIC
# MAGIC Add these to the evidence set described in
# MAGIC [`docs/databricks/integration.md` -> Evidence checklist](../../docs/databricks/integration.md).

# COMMAND ----------

# MAGIC %sql
# MAGIC DESCRIBE EXTENDED workspace.silver.comment_embeddings_bge_large;

# COMMAND ----------

_summary = {
    "endpoint": VS_ENDPOINT_NAME,
    "index": VS_INDEX_NAME,
    "source": FILTERED_SOURCE_VIEW,
    "primary_key": PRIMARY_KEY,
    "embedding_column": EMBEDDING_COLUMN,
    "embedding_dim": EMBEDDING_DIM,
    "embedding_model": EMBEDDING_MODEL,
    "backend": EMBEDDING_BACKEND,
    "indexed_rows": _row_count,
    "sync_seconds": _sync_seconds,
    "sample_comment_id": SAMPLE_COMMENT_ID,
}
_summary
