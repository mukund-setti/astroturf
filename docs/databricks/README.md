# Databricks Deployment Checklist

This document describes the safe public configuration path for running Astroturf on Databricks. It intentionally uses placeholders; provide real values through environment variables, Databricks secrets, or your hosting platform's secret manager.

## Required Workspace Capabilities

- Unity Catalog enabled.
- Serverless notebooks/jobs or a compatible Databricks cluster.
- A SQL Warehouse for UI hydration and validation queries.
- Access to the `databricks-bge-large-en` Foundation Model endpoint.
- Optional: Vector Search endpoint and index for scalable semantic neighbor lookup.

## Environment Variables

Backend / notebooks:

```bash
ASTROTURF_DELTA_BACKEND=auto
DATABRICKS_HOST=https://<databricks-workspace-host>
DATABRICKS_TOKEN=<databricks-token>
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
DATABRICKS_CATALOG=<catalog>
DATABRICKS_DATA_ROOT=/Volumes/<catalog>/<schema>/<volume-or-path>
DATABRICKS_REPO_PATH=/Workspace/Repos/<user-or-service-principal>/astroturf
DATABRICKS_VECTOR_INDEX_NAME=<catalog>.silver.comment_embeddings_bge_large_index
DATA_GOV_API_KEY=<optional-api-data-gov-key>
```

Hosted UI:

```bash
ASTROTURF_DEPLOYMENT_MODE=production
ASTROTURF_EXECUTION_MODE=databricks_job
ASTROTURF_DATA_MODE=auto
DATABASE_URL=<postgres-connection-url-with-ssl>
DATABRICKS_JOB_ID=<web-analysis-job-id>
DATABRICKS_HOST=https://<databricks-workspace-host>
DATABRICKS_TOKEN=<databricks-token>
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
DATABRICKS_CATALOG=<catalog>
DATABRICKS_DATA_ROOT=/Volumes/<catalog>/<schema>/<volume-or-path>
DATABRICKS_REPO_PATH=/Workspace/Repos/<user-or-service-principal>/astroturf
```

## Lakehouse Layout

Create or allow the workflow to create the following schemas:

- `<catalog>.bronze`
- `<catalog>.silver`
- `<catalog>.gold`
- `<catalog>.demo`

Expected tables/views:

- `bronze.raw_comments`
- `silver.parsed_comments`
- `silver.comment_details`
- `silver.comment_attachments`
- `silver.comment_embeddings`
- `gold.comment_clusters`
- `gold.comment_cluster_memberships`
- `gold.campaign_attributions`
- `gold.rule_migrations`
- `demo.cluster_review_export`

## Job Entry Points

- Hosted `/analyze` requests: `notebooks/databricks/web_analysis_job.py`
- Sample/demo workflow: `notebooks/databricks/workflow_tasks.py`
- Vector Search setup: `notebooks/databricks/vector_search_setup.py`

Do not point the hosted web app's `DATABRICKS_JOB_ID` at the sample-loader workflow. Hosted requests need `web_analysis_job.py`, which ingests from the public source APIs.

## Deployment Steps

1. Sync the repository into a Databricks workspace repo.
2. Configure runtime secrets without committing them.
3. Create the Unity Catalog schemas and storage root.
4. Run `scripts/check_databricks_ready.py` with the same environment values used by the job.
5. Create a Databricks job for `web_analysis_job.py`.
6. Configure the hosted UI with the job ID and SQL Warehouse HTTP path.
7. Run a small public docket slice first, then inspect MLflow metrics and row counts.

## Validation Queries

Run from a SQL Warehouse after a successful job:

```sql
SELECT COUNT(*) FROM <catalog>.bronze.raw_comments WHERE docket_id = '<docket-id>';
SELECT COUNT(*) FROM <catalog>.silver.parsed_comments WHERE docket_id = '<docket-id>';
SELECT COUNT(*) FROM <catalog>.silver.comment_embeddings WHERE docket_id = '<docket-id>';
SELECT COUNT(*) FROM <catalog>.gold.comment_clusters WHERE docket_id = '<docket-id>';
SELECT COUNT(*) FROM <catalog>.gold.comment_cluster_memberships WHERE docket_id = '<docket-id>';
SELECT COUNT(*) FROM <catalog>.demo.cluster_review_export WHERE docket_id = '<docket-id>';
```

## Public Repo Safety

Keep real workspace hostnames, tokens, warehouse IDs, job IDs, database URLs, and run URLs out of committed files. If a public write-up needs to mention a validation run, include non-sensitive row counts and elapsed time, not private IDs.
