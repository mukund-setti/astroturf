# End-to-End Pipeline Runbook

This runbook separates the local development path from the Databricks production path. The production path has been live-validated inside Databricks Serverless notebook tasks.

> Docket entries in [`configs/dockets.yaml`](../configs/dockets.yaml) carry a
> `processing_status` enforced by
> [`scripts/run_docket_pipeline.py`](../scripts/run_docket_pipeline.py)'s
> `ALLOWED_PROCESSING_STATUSES`. The five values are
> `configured_awaiting_run`, `queued`, `partially_processed`, `baseline_only`,
> and `analyzed`. The mapping to UI labels and tiers is documented in
> [`docs/product-vision.md`](product-vision.md) and
> [`docs/ui-information-architecture.md`](ui-information-architecture.md).

## Local Development Path

Local development is for fast iteration, tests, exact-hash baselines, mock embeddings, and offline UI review.

```powershell
uv sync
.uv-test-venv\Scripts\python.exe -m pytest
```

Run the offline UI:

```powershell
cd ui
$env:ASTROTURF_DATA_MODE = "mock"
npm run dev
```

Open `http://localhost:3000`.

On Windows, `npm run dev` intentionally uses Next's webpack dev server. Turbopack is still available with `npm run dev:turbo`, but webpack is the safer default after Turbopack produced native out-of-memory crashes during mock-mode local review.

Local scripts remain useful for development runs:

```powershell
.uv-test-venv\Scripts\python.exe scripts\run_ingestion.py --help
.uv-test-venv\Scripts\python.exe scripts\run_embedding.py --help
.uv-test-venv\Scripts\python.exe scripts\run_clustering.py --help
.uv-test-venv\Scripts\python.exe scripts\run_exact_hash_baseline.py --help
.uv-test-venv\Scripts\python.exe scripts\run_attribution.py --help
.uv-test-venv\Scripts\python.exe scripts\run_migration.py --help
```

### Optional: Attribution and Migration (Phase 8, evidence layer)

Both are optional. They produce evidence packets, not accusations — see
[ADR-0015](decisions/0015-attribution-and-migration-agents.md) and
[`docs/attribution-and-migration-methodology.md`](attribution-and-migration-methodology.md).

```powershell
.uv-test-venv\Scripts\python.exe scripts\run_attribution.py `
    --docket-id 17-108 --mode offline_seed --max-clusters 5

.uv-test-venv\Scripts\python.exe scripts\run_migration.py `
    --docket-id 17-108 --mode local_text `
    --final-rule-text evals\fixtures\migration\fcc_17_108_final_rule_excerpt.txt `
    --max-clusters 5
```

The export script picks up `gold.campaign_attributions` and
`gold.rule_migrations` automatically if they exist; absence is treated as
"not yet analyzed" and never breaks the export or UI.

## Databricks Production Path

Use Databricks notebooks/jobs for production mode. Do not rely on local Windows CLI execution for `/Volumes/...` operations.

Production notebook entry point:

```text
notebooks/databricks/workflow_tasks.py
```

Run tasks in this order:

1. `load_sample_tables`
2. `embed`
3. `cluster`
4. `export_dashboard_data`

For the validated FCC `17-108` production slice, the successful live run IDs were:

| Task | Run ID |
| --- | --- |
| `load_sample_tables` | `916653215561127` |
| `embed` | `546125942192140` |
| `cluster` | `1028362756517371` |
| `export_dashboard_data` | `156035613634033` |

The cluster task used `clustering_mode="vector_search"`.

## Validate Row Counts

Run from a Databricks SQL Warehouse:

```sql
SELECT COUNT(*) FROM workspace.bronze.raw_comments WHERE docket_id = '17-108';
SELECT COUNT(*) FROM workspace.silver.parsed_comments WHERE docket_id = '17-108';
SELECT COUNT(*) FROM workspace.silver.comment_embeddings
WHERE docket_id = '17-108' AND embedding_model = 'databricks-bge-large-en';
SELECT COUNT(*) FROM workspace.silver.comment_embeddings_bge_large WHERE docket_id = '17-108';
SELECT COUNT(*) FROM workspace.gold.comment_clusters WHERE docket_id = '17-108';
SELECT COUNT(*) FROM workspace.gold.comment_cluster_memberships WHERE docket_id = '17-108';
SELECT COUNT(*) FROM workspace.demo.cluster_review_export WHERE docket_id = '17-108';
```

Expected Phase 6 counts:

- `raw_comments`: 500
- `parsed_comments`: 500
- `comment_embeddings`: 500 BGE rows
- `comment_embeddings_bge_large`: 500
- `comment_clusters`: 1
- `comment_cluster_memberships`: 500
- `cluster_review_export`: 500

## Inspect MLflow Runs

Each agent run emits MLflow metrics, inputs, row counts, and timing. In Databricks:

1. Open the job run page.
2. Open each task run.
3. Follow the MLflow run link or open the workspace experiment used by the task.
4. Verify input parameters, output row-count metrics, timing, and task status.

The key production run IDs to inspect are `916653215561127`, `546125942192140`, `1028362756517371`, and `156035613634033`.

## Refresh Demo Export Table

Refresh the reviewer-facing export by rerunning the final notebook task:

```text
export_dashboard_data
```

The output table is:

```text
workspace.demo.cluster_review_export
```

After refresh, validate:

```sql
SELECT COUNT(*) FROM workspace.demo.cluster_review_export WHERE docket_id = '17-108';
SELECT cluster_id, cluster_size, representative_comment_id
FROM workspace.demo.cluster_review_export
WHERE docket_id = '17-108' AND is_representative = true;
```

## UI Data Mode

The Next.js UI supports three modes through `ASTROTURF_DATA_MODE`.

### Mock Mode

Always use fallback/demo artifacts:

```powershell
cd ui
$env:ASTROTURF_DATA_MODE = "mock"
npm run dev
```

The UI label should read `Offline benchmark artifact mode`.

### Live Mode

Always query Databricks SQL and fail visibly if unavailable:

```powershell
cd ui
$env:ASTROTURF_DATA_MODE = "live"
$env:DATABRICKS_HOST = "https://<workspace-host>"
$env:DATABRICKS_TOKEN = "<token>"
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/<warehouse-id>"
$env:DATABRICKS_CATALOG = "workspace"
$env:DEMO_DOCKET_ID = "17-108"
npm run dev
```

The UI label should read `Live Databricks SQL mode`.

### Auto Mode

Try Databricks SQL when credentials are present; otherwise fall back to artifacts:

```powershell
cd ui
$env:ASTROTURF_DATA_MODE = "auto"
npm run dev
```

Without SQL credentials, the UI label should read `Auto mode: using fallback artifacts`.

## Hosted Databricks Jobs Integration & Ingestion Queue

To separate local developer script execution from production-hosted servers, configure the `ASTROTURF_EXECUTION_MODE` environment variable inside `ui/.env.local`:

```bash
# Options: command | local_process | databricks_job
ASTROTURF_EXECUTION_MODE=command
```

### Safety and Spawning Boundaries

> [!IMPORTANT]
> **Hosted Server Spawning Restriction**: Deployed web applications (such as in serverless Vercel or hosted container environments) **cannot and must never spawn local Python processes** or execute background scripts directly. Long-running Python processes will time out, fail silently, or crash serverless functions.
> - **Production hosted apps** must use `ASTROTURF_EXECUTION_MODE=databricks_job` or fall back to `command` mode.
> - Setting `ASTROTURF_EXECUTION_MODE=local_process` while running in production (`process.env.NODE_ENV === "production"`) will be caught by server-side safety checks and **rejected immediately with a validation error**.

### Configuration for Databricks Jobs Mode (`databricks_job`)

To submit runs directly to your cloud compute from the UI, configure these environment variables inside `ui/.env.local`:

```bash
ASTROTURF_EXECUTION_MODE=databricks_job
DATABRICKS_JOB_ID="<your-databricks-job-id>"
DATABRICKS_HOST="https://<your-databricks-instance>.cloud.databricks.com"
DATABRICKS_TOKEN="dapi****************"
DATABRICKS_AUTOPILOT_JOB_ID="<optional-autopilot-workflow-job-id>"
```

1. **Submit Analysis Request**: Click **Submit Analysis Job** on the `/analyze` page. This creates a durable request in `ui/.data/analysis-requests.json` and issues a `POST` request using bearer authorization to Databricks' `/api/2.1/jobs/run-now` REST API.
2. **Execution Monitoring**: The app redirects you to `/analysis/[request_id]` displaying details and status. Click **Sync Databricks Run** to query the run status (`GET /api/2.1/jobs/runs/get`) and map it back into local state (`submitted`, `running`, `succeeded`, `failed`).
3. **Data Sync Guard**: When status updates to `succeeded`, the page links to `/dockets/[docket_id]`. If the final Unity Catalog export table is still replicating, a waiting screen appears. Click **Verify Table Sync** to check Databricks SQL Warehouse tables.

### Command-Generation Mode (`command`)

If no cloud credentials exist or process triggering is disabled, use `ASTROTURF_EXECUTION_MODE=command` (default). Clicking "Register Docket Draft" will save a draft record in the queue database and redirect to `/analysis/[request_id]` where copy-pasteable terminal commands are displayed for offline developer execution. 

## Production Control Plane & Database Migrations (PostgreSQL)

In hosted production environments (`ASTROTURF_DEPLOYMENT_MODE=production`), Astroturf operates a **durable PostgreSQL control plane** instead of using unstable server-local JSON file stores. This makes the Next.js control plane fully stateless, reliable, and production-safe.

### Required Database Settings

Ensure you configure the following variables in your hosted environment:

```env
# Enforce production mode (disables all local JSON fallback operations)
ASTROTURF_DEPLOYMENT_MODE=production

# Provide standard PostgreSQL connection URL (e.g. Neon, Supabase, Vercel Postgres, Railway)
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<dbname>?sslmode=require
```

### Relational Database Migrations

Before deploying the UI web layer, apply the relational database migrations to establish the schema:

```bash
psql -d "DATABASE_URL" -f ui/db/migrations/001_initial_control_plane.sql
```

The migration defines:
- `docket_catalog`: Table caching discovered rulemaking dockets, metadata, and prioritization scores.
- `analysis_requests`: Table tracking jobs sent to the Databricks Jobs scheduler.
- `watchlist_items`: Table representing keywords, dockets, topics, and agencies active in monitoring.
- `autopilot_runs`: History of proactive discovery/monitoring runs.

### Pre-Deployment Verification

Verify database connectivity, schema tables, and Databricks cloud variables using our built-in production readiness check utility:

```powershell
cd ui
npm run check-env
```

The script will automatically assert connection safety, verify required tables are present in the public schema, and check Databricks API parameters.

## Known Limitations

- Phase 6 validated table/query readiness but did not visually validate the Next.js UI against the live SQL Warehouse.
- Local Windows production-mode execution against Databricks `/Volumes/...` paths remains unsupported.
- Fallback artifact mode is intentionally retained for reviewers without Databricks credentials.
