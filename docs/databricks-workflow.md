# Databricks Workflow runbook: `astroturf-cfpb-demo`

This runbook explains how to wire `notebooks/databricks/workflow_tasks.py` into
the four-task `astroturf-cfpb-demo` Databricks Workflow described in
[`docs/databricks-integration.md`](./databricks-integration.md) under
*Minimal Databricks Workflow*. It is the implementation-side companion to that
plan.

The notebook is one file with four `# COMMAND ----------` blocks - one per
Workflow task. Each task in the Workflow points at the same notebook and uses
the `task` widget to dispatch to a single block. Each block can also be
promoted to its own notebook later by copying the **Shared setup** block plus
the target block into a new file.

Related docs:

- [`databricks-integration.md`](./databricks-integration.md) - UC layout,
  Foundation Model backend, Vector Search mapping, evidence checklist.
- [`databricks-vector-search.md`](./databricks-vector-search.md) -
  model-filtered Vector Search index over
  `astroturf.silver.comment_embeddings_bge_large` (Agent 1 deliverable; file
  may not exist yet).
- [`architecture.md`](./architecture.md) - agent contracts and table layout.

## Prerequisites

Before creating the Workflow:

1. The `astroturf` Unity Catalog exists and the runner has `USE CATALOG`,
   `CREATE SCHEMA`, `CREATE TABLE`, and `MODIFY` privileges on its schemas.
2. The volume `astroturf.bronze.raw_imports` exists and contains the local
   Parquet sample under `raw_comments/` and `parsed_comments/`. Export from
   the local lakehouse with:
   ```bash
   python -c "from deltalake import DeltaTable; DeltaTable('./data/bronze/raw_comments').to_pyarrow_table().to_parquet('./out/raw_comments.parquet')"
   ```
   then upload via the UC volume UI or `databricks fs cp`.
3. The "working lakehouse" volume path passed as `data_root`
   (default `/Volumes/astroturf/demo/exports/_lakehouse`) exists. UC external
   tables register over this path, so the runner needs write access to it.
4. The repo is checked out into `/Workspace/Repos/<user>/astroturf` (or another
   path passed as `repo_path`). The notebook adds this path to `sys.path` so it
   can `import agents...` and `import shared...` without packaging.
5. The cluster has the project Python dependencies installed (`deltalake`,
   `tenacity`, `mlflow`, `pyarrow`, `pydantic`, `numpy`, `databricks-sdk`,
   `sentence-transformers` is only needed if the local backend is selected).
   Use a Databricks Runtime ML image or a cluster init script that runs
   `pip install -r requirements.txt`.
6. The Foundation Model endpoint `databricks-bge-large-en` is reachable from
   the workspace. Inside a Workflow run the Databricks SDK picks up
   notebook-scoped credentials automatically.

## Task layout

| Order | Workflow task name      | Notebook                                            | Depends on               |
| ----- | ----------------------- | --------------------------------------------------- | ------------------------ |
| 1     | `load_sample_tables`    | `notebooks/databricks/workflow_tasks.py`            | -                        |
| 2     | `embed`                 | `notebooks/databricks/workflow_tasks.py`            | `load_sample_tables`     |
| 3     | `cluster`               | `notebooks/databricks/workflow_tasks.py`            | `embed`                  |
| 4     | `export_dashboard_data` | `notebooks/databricks/workflow_tasks.py`            | `cluster`                |

All four tasks point at the **same** notebook file. Each task sets `task` to
its own block name so the rest of the notebook short-circuits.

To promote a block to its own notebook later, copy the **Shared setup** block
plus the target block into a new file (e.g. `notebooks/databricks/embed.py`)
and update the Workflow task to point at the new path. The `task` widget can
be dropped from a promoted notebook.

## Widget parameter mapping

Per-task widget values to set in the Workflow's "Parameters" section
(`base_parameters` in the JSON). Every task also sets the **Shared setup**
widgets.

### Shared setup (all tasks)

| Widget       | Value                                          | Notes                                                          |
| ------------ | ---------------------------------------------- | -------------------------------------------------------------- |
| `task`       | one of `load_sample_tables` / `embed` / `cluster` / `export_dashboard_data` | Selects which block runs. Set per task.           |
| `catalog`    | `astroturf`                                    | UC catalog from `databricks-integration.md`.                   |
| `docket_id`  | `CFPB-2016-0025`                               | Demo docket.                                                   |
| `data_root`  | `/Volumes/astroturf/demo/exports/_lakehouse`   | Volume root that backs the UC external tables.                 |
| `repo_path`  | `/Workspace/Repos/<user>/astroturf`            | Where `agents/` and `shared/` live on the cluster.             |

### `load_sample_tables`

| Widget          | Value                                | Notes                                              |
| --------------- | ------------------------------------ | -------------------------------------------------- |
| `bronze_volume` | `/Volumes/astroturf/bronze/raw_imports` | Parquet upload landing zone. Must contain `raw_comments/` and `parsed_comments/`. |

Writes `astroturf.bronze.raw_comments` and `astroturf.silver.parsed_comments`
as UC external Delta tables under `data_root`.

### `embed`

| Widget                  | Value                       | Notes                                            |
| ----------------------- | --------------------------- | ------------------------------------------------ |
| `embedding_model`       | `databricks-bge-large-en`   | Stored verbatim in `silver.comment_embeddings.embedding_model`. |
| `embedding_batch_size`  | `16`                        | Safe default for the BGE serving endpoint (see `agents/embedding/agent.py`). |
| `embedding_max_rows`    | (blank)                     | Set to a small integer when smoke-testing on Databricks. |
| `force_reembed`         | `false`                     | Set `true` only when re-running after a parser change. |

Reads `astroturf.silver.parsed_comments`. Writes
`astroturf.silver.comment_embeddings` (MERGE on
`(comment_id, embedding_model)`) and registers the UC external table.

Vector Search index sync (`astroturf.silver.comment_embeddings_bge_large_index`)
is **not** triggered here - see [`databricks-vector-search.md`](./databricks-vector-search.md).

### `cluster`

| Widget                    | Value                                | Notes                                          |
| ------------------------- | ------------------------------------ | ---------------------------------------------- |
| `cluster_embedding_model` | `databricks-bge-large-en`            | Slice filter on `comment_embeddings`.          |
| `similarity_threshold`    | `0.92`                               | Matches `DEFAULT_SIMILARITY_THRESHOLD`.        |
| `min_cluster_size`        | `2`                                  | Drop singletons.                               |
| `clustering_max_rows`     | (blank)                              |                                                |
| `clustering_version`      | `v1_connected_components_cosine`     | Carried into `gold.comment_clusters.clustering_version`. |
| `clustering_mode`         | `vector_search`                      | Use Vector Search candidate retrieval for Databricks production runs. |
| `vector_index_name`       | `astroturf.silver.comment_embeddings_bge_large_index` | Required when `clustering_mode=vector_search`. |
| `allow_mock`              | `false`                              | Must be `false` for the demo run.              |

Reads `astroturf.silver.comment_embeddings`. Writes
`astroturf.gold.comment_clusters` and
`astroturf.gold.comment_cluster_memberships`, then registers both as UC
external tables.

### `export_dashboard_data`

| Widget                         | Value                       | Notes                                  |
| ------------------------------ | --------------------------- | -------------------------------------- |
| `export_embedding_model`       | `databricks-bge-large-en`   | Must match the `cluster` task scope.   |
| `export_similarity_threshold`  | `0.92`                      | Must match the `cluster` task scope.   |

Writes `astroturf.demo.cluster_review_export` via `CREATE OR REPLACE TABLE` so
the dashboard always sees the latest scope. Column set matches
`shared/schemas/cluster_review_export.py`.

## Task dependencies

Wire the Workflow DAG so that:

```text
load_sample_tables -> embed -> cluster -> export_dashboard_data
```

In the Databricks UI: each task's "Depends on" field references the prior
task. In a JSON job definition use `"depends_on": [{"task_key": "..."}]`.

## Expected MLflow output

Two MLflow runs land in the workspace experiment per Workflow run (the
`load_sample_tables` and `export_dashboard_data` tasks do not start runs):

- `embedding-CFPB-2016-0025` (from `agents/embedding/agent.py`)
  - Params: `docket_id`, `embedding_model = databricks-bge-large-en`,
    `embedding_dim = 1024`, `backend = databricks_foundation_model`,
    `batch_size = 16`, `force_reembed`, `max_rows`.
  - Metrics: `candidates_total`, `skipped_cache_hit`, `skipped_corrupt`,
    `embedded_count`, `new_count`, `stale_reembedded_count`, `rows_written`,
    `duration_seconds`, `fm_request_count`, `fm_retry_count`,
    `fm_failed_batch_count`, `fm_total_latency_seconds`.
- `clustering-CFPB-2016-0025` (from `agents/clustering/agent.py`)
  - Params: `docket_id`, `embedding_model`, `clustering_version`,
    `similarity_threshold`, `min_cluster_size`, `allow_mock`, plus
    `embedding_backend = databricks_foundation_model` once candidates load.
  - Params: include `mode` / `clustering_mode` and, for production runs,
    `vector_index_name`.
  - Metrics: `candidates_total`, `candidates_after_mock_filter`,
    `rows_clustered`, `comments_considered`, `pair_count_evaluated`,
    `edge_count_above_threshold`, `clusters_written`, `clusters_found`,
    `memberships_written`, `deleted_clusters`, `deleted_memberships`,
    `largest_cluster_size`, `mean_cluster_size`, `coverage`,
    `duration_seconds`, and `runtime_seconds`.

Both runs share the workspace MLflow experiment associated with the notebook.
Use the experiment ID in the Workflow definition if you want runs pinned to a
named experiment.

## Promotion plan (one notebook -> four notebooks)

When the demo path is stable, split this file into four notebooks so each
Workflow task has its own minimal blast radius:

1. Copy `notebooks/databricks/workflow_tasks.py` to
   `notebooks/databricks/load_sample_tables.py`, keep the **Shared setup**
   block and the `load_sample_tables` block, delete the rest, drop the `task`
   widget guard.
2. Repeat for `embed.py`, `cluster.py`, `export_dashboard_data.py`.
3. Update each Workflow task's notebook path. Leave the original combined
   notebook in place as the integration smoke test (set `task = all`).

## Screenshot checklist

For the Student Fellows evidence package (cross-referenced in
`databricks-integration.md`), capture from a successful run:

- [ ] Workflow page showing the four-task DAG with all green.
- [ ] Each task's run detail page showing the widget values used.
- [ ] MLflow `embedding-CFPB-2016-0025` run with `backend`, `embedding_model`,
      and `fm_request_count` visible.
- [ ] MLflow `clustering-CFPB-2016-0025` run with `edge_count_above_threshold`
      and `clusters_written` visible.
- [ ] UC catalog explorer showing `astroturf.bronze.raw_comments`,
      `astroturf.silver.parsed_comments`,
      `astroturf.silver.comment_embeddings`,
      `astroturf.gold.comment_clusters`,
      `astroturf.gold.comment_cluster_memberships`, and
      `astroturf.demo.cluster_review_export`.
- [ ] Sample row of `astroturf.demo.cluster_review_export` for one cluster.
- [ ] Vector Search index page from
      [`databricks-vector-search.md`](./databricks-vector-search.md)
      (separate evidence; not produced by this Workflow).

## Smoke-running the notebook ad hoc

Without a Workflow, attach the notebook to a Databricks Runtime ML cluster,
set `task = all`, and run all cells. Each guarded block will execute in
sequence. Use `task = embed` (etc.) to run a single block while iterating.

## Things this notebook intentionally does not do

- It does not create the `bronze.raw_imports` volume or upload Parquet files;
  do that once before the first run.
- It does not create the Vector Search index or trigger sync; see
  [`databricks-vector-search.md`](./databricks-vector-search.md).
- It does not run AttributionAgent or MigrationAgent; both are out of scope
  for the v1 Workflow per `databricks-integration.md`.
- It does not modify agent code, schemas, or local CLI scripts. All four
  blocks are thin wrappers around the existing agent contracts in
  `agents/embedding/agent.py` and `agents/clustering/agent.py`.
