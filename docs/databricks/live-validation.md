# Live Databricks Validation

Phase 6 validated the Databricks production path in a real Databricks workspace using Serverless notebook/job execution. It did not validate local Windows CLI execution for production-mode `/Volumes/...` path operations.

## What Was Validated

- Readiness checker returned `READY` for the workspace.
- Unity Catalog schemas were present: `workspace.bronze`, `workspace.silver`, `workspace.gold`, and `workspace.demo`.
- Foundation Model endpoint `databricks-bge-large-en` was ready.
- Vector Search endpoint `astroturf-vs-endpoint` was reachable.
- SQL Warehouse connectivity passed with `SELECT 1`.
- FCC ECFS docket `17-108` controlled 500-comment slice processed end to end.
- Databricks Vector Search clustering path produced one semantic cluster and refreshed the demo export table.

## Execution Location

Production mode was live-validated inside Databricks Serverless notebook tasks. The local Windows command `scripts/run_docket_pipeline.py --mode databricks` is not the supported production execution path because it cannot execute Databricks `/Volumes/...` file operations from Windows.

Recommended production execution location:

1. Databricks multi-task job using `notebooks/databricks/workflow_tasks.py`.
2. Databricks notebook task execution on Serverless compute.
3. SQL validation from a Databricks SQL Warehouse.

## Notebook Task Order

The successful production run used this task order:

1. `load_sample_tables`
2. `embed`
3. `cluster`
4. `export_dashboard_data`

The validated cluster task used `clustering_mode="vector_search"` for the FCC `17-108` slice.

## Live Run References

The validation was performed in a private Databricks workspace. Private run
identifiers are intentionally omitted from the public repository. Reproduce the
validation by running the task order above in your own workspace and inspecting
the resulting Databricks job and MLflow run pages.

## Final Row Counts

| Table | Validated count |
| --- | ---: |
| `workspace.bronze.raw_comments` | 500 |
| `workspace.silver.parsed_comments` | 500 |
| `workspace.silver.comment_embeddings` | 500 BGE rows |
| `workspace.silver.comment_embeddings_bge_large` | 500 |
| `workspace.gold.comment_clusters` | 1 |
| `workspace.gold.comment_cluster_memberships` | 500 |
| `workspace.demo.cluster_review_export` | 500 |

## Cluster Result

- Cluster count: 1 semantic cluster.
- Cluster size: 500 comments.
- Representative comment: `10828445130115`.
- Mean similarity: `0.95395`.
- Minimum similarity: `0.94317`.

## Validation Queries

Run these from a Databricks SQL Warehouse connected to the same catalog:

```sql
SELECT 1;
```

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

Inspect the live cluster export:

```sql
SELECT
  cluster_id,
  cluster_size,
  representative_comment_id,
  ROUND(AVG(similarity), 5) AS mean_similarity,
  ROUND(MIN(similarity), 5) AS min_similarity
FROM workspace.demo.cluster_review_export
WHERE docket_id = '17-108'
GROUP BY cluster_id, cluster_size, representative_comment_id;
```

## Screenshots

Recommended screenshot placeholders for reviewer packets:

- Databricks job run graph showing `load_sample_tables -> embed -> cluster -> export_dashboard_data`.
- SQL Warehouse validation query results for the row-count table.
- Vector Search endpoint page for `astroturf-vs-endpoint`.
- Foundation Model endpoint readiness page for `databricks-bge-large-en`.
- MLflow run pages for the four production tasks.

## What Was Not Validated

- The production path was not validated through local Windows CLI execution.
- The Next.js UI was not visually validated against the live SQL Warehouse during Phase 6.
- UI live SQL hydration was validated at the Databricks table/query layer, while the UI still needed a data-mode switch to stop forcing FCC `17-108` into offline artifacts.
- Attachment PDF/DOCX extraction, OCR, and LLM extraction remain deferred.
- Expanded production Vector Search recall tuning remains future work.

## Caveats

- Use Databricks notebooks/jobs for production runs involving UC volumes and `/Volumes/...` paths.
- Keep local runs focused on development, tests, mock embeddings, exact-hash baselines, and fallback demo artifacts.
- A live UI demo requires `ASTROTURF_DATA_MODE=live` plus valid Databricks SQL environment variables. Do not claim visual live UI validation until the app is actually run against the SQL Warehouse.
