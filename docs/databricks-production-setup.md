# Databricks Production Setup

This setup supports the live production path for Astroturf on Databricks. Production runs should execute inside Databricks notebooks or jobs, not from the local Windows CLI.

## Required Environment Variables

For Databricks SQL hydration in the Next.js UI:

```powershell
$env:ASTROTURF_DATA_MODE = "live"
$env:DATABRICKS_HOST = "https://<workspace-host>"
$env:DATABRICKS_TOKEN = "<personal-access-token-or-service-principal-token>"
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/<warehouse-id>"
$env:DATABRICKS_CATALOG = "workspace"
$env:DEMO_DOCKET_ID = "17-108"
```

For local/offline UI review:

```powershell
$env:ASTROTURF_DATA_MODE = "mock"
```

`OFFLINE_MODE=true` is still accepted as a legacy alias for mock mode.

## Required Unity Catalog Objects

The validated catalog was `workspace`. Required schemas:

- `workspace.bronze`
- `workspace.silver`
- `workspace.gold`
- `workspace.demo`

Validated tables for the Phase 6 FCC slice:

- `workspace.bronze.raw_comments`
- `workspace.silver.parsed_comments`
- `workspace.silver.comment_embeddings`
- `workspace.silver.comment_embeddings_bge_large`
- `workspace.gold.comment_clusters`
- `workspace.gold.comment_cluster_memberships`
- `workspace.demo.cluster_review_export`

## Required Endpoints

- Foundation Model endpoint: `databricks-bge-large-en`
- Vector Search endpoint: `astroturf-vs-endpoint`
- Vector Search index: `workspace.silver.comment_embeddings_bge_large_index`
- SQL Warehouse: any running warehouse reachable through `DATABRICKS_HTTP_PATH`

## Readiness Checks

Run the readiness checker before production execution:

```powershell
.uv-test-venv\Scripts\python.exe scripts\check_databricks_ready.py
```

Expected readiness criteria:

- UC schemas found: `bronze`, `silver`, `gold`, `demo`
- Foundation Model endpoint ready
- Vector Search endpoint reachable
- SQL Warehouse `SELECT 1` succeeds

## Recommended Execution Location

Use Databricks Serverless notebook tasks or a Databricks multi-task job. The production notebook entry point is:

```text
notebooks/databricks/workflow_tasks.py
```

Recommended task order:

1. `load_sample_tables`
2. `embed`
3. `cluster`
4. `export_dashboard_data`

For production semantic clustering at scale, run the cluster task with Vector Search mode:

```text
clustering_mode="vector_search"
```

## Known Windows Local Limitation

Local Windows execution of:

```powershell
.uv-test-venv\Scripts\python.exe scripts\run_docket_pipeline.py --mode databricks
```

is not the production path for live Databricks validation. It cannot reliably execute Databricks `/Volumes/...` path operations from Windows. Use Databricks notebook/job execution for production-mode file and volume operations.

## UI Data Mode

The Next.js UI uses `ASTROTURF_DATA_MODE`:

| Mode | Behavior |
| --- | --- |
| `mock` | Always use fallback/demo artifacts. |
| `live` | Always query Databricks SQL and fail visibly if SQL is unavailable. |
| `auto` | Try Databricks SQL when credentials are present; otherwise use fallback artifacts. |

Local development defaults to `auto`, which is safe because it falls back to artifacts when Databricks SQL variables are absent. Production should set `ASTROTURF_DATA_MODE=live`.

For Windows stability, the default local dev command uses webpack:

```powershell
cd ui
npm run dev
```

Turbopack remains available for targeted testing:

```powershell
npm run dev:turbo
```
