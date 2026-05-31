# ADR-0009: Cluster review export table

- Status: Accepted
- Date: 2026-05-22

## Context

The Databricks v1 demo (ADR-0007) defines a four-task workflow whose final task
is `export_dashboard_data`. That task joins `gold.comment_clusters`,
`gold.comment_cluster_memberships`, and `silver.parsed_comments` so the review
UI can show one cluster's size, threshold, representative text, and member
sample without performing multi-table joins at read time.

Today the local debug UI and the `export_cluster_evidence.py` script both
hand-roll the same join. As soon as the Databricks Workflow exists, that join
needs to be a real, named artifact rather than logic re-implemented in every
caller. We also need a single contract that the review UI can target on
Databricks and locally without branching.

CLAUDE.md requires an ADR for every new Delta table or schema. This is the
first table in the `astroturf.demo` schema described by
`docs/databricks/integration.md`.

## Decision

Create a new dashboard-ready table:

- Unity Catalog table: `astroturf.demo.cluster_review_export`.
- Local path (Parquet, not Delta for v1): `./data/exports/cluster_review_export/`.

Schema owner: `shared/schemas/cluster_review_export.py`, with a Pydantic
`ClusterReviewExportRow` as the source of truth and derived PyArrow and PySpark
schemas, following the pattern in `shared/schemas/comment_clusters.py`.

Grain: one row per `(cluster_id, comment_id)` for one clustering run scope
(`docket_id` + `embedding_model` + `similarity_threshold`).

Fields (full list in the schema module):

- `cluster_id`, `docket_id`, `embedding_model`, `similarity_threshold`,
  `cluster_size`, `representative_comment_id` — carried from
  `gold.comment_clusters` so the UI never has to join back to gold for grouping
  or labelling.
- `comment_id`, `is_representative`, `text_source` — per-member identity.
- `text_preview` — joined parsed-comment text, whitespace-collapsed and
  truncated to ~500 chars so the UI can render preview cards without hitting
  silver. Full text remains in `silver.parsed_comments`.
- `submitter_name`, `posted_date` — best-effort attribution context, both
  nullable because attribution is incomplete for many comments.
- `source` — `"semantic"` or `"exact_hash"`, derived from `embedding_backend`
  so the UI can distinguish the embedding-driven clusters from the
  baseline-duplicate clusters at a glance.
- `exported_at` — when the row was produced, useful for cache-busting in the
  UI.

Local v1 writer: `scripts/export_cluster_review_dataset.py` joins the three
input Delta tables and writes a single Parquet file. It refuses to overwrite an
existing output directory unless `--overwrite` is passed.

## Consequences

Positive:

- The review UI gets a single, stable contract that works the same locally and
  on Databricks.
- Multi-table join logic lives in one place instead of being re-implemented in
  the debug UI, the evidence exporter, and the Databricks Workflow.
- The `source` column makes semantic vs exact-hash clusters self-describing
  without leaking implementation details (the UI doesn't need to know which
  backend strings count as which).
- Large text stays in silver. The export carries previews only, keeping the
  artifact small enough to ship as a Parquet snapshot or fit comfortably in a
  Databricks dashboard.

Negative:

- It is a denormalized derived table. Reruns must re-materialize the whole
  scope; ad-hoc updates are not supported and shouldn't be.
- Adding new reviewer-facing context (e.g., attribution evidence) requires a
  schema change, an ADR-0004-style additive migration, and a re-export.
- The Parquet-on-disk v1 differs from the Databricks Delta table. That is
  acceptable for the local demo, but production should align the local writer
  on Delta later.

## Alternatives considered

### 1. Render the join inside the UI at read time

Rejected. Each caller (debug UI, evidence exporter, Databricks dashboard) would
re-implement the same join, and the Databricks Workflow's `export_dashboard_data`
task in ADR-0007 explicitly calls for a stored artifact.

### 2. Use a view instead of a materialized table

Plausible on Databricks (a view over the three source tables would be cheap
enough for the demo scale). Rejected for v1 because the local prototype does
not have a Spark view abstraction, and we want one contract that works in both
environments without branching.

### 3. Reuse `gold.comment_clusters` and join in the UI

Rejected. `gold.comment_clusters` has one row per cluster, but the review UI
needs one row per member with comment text and submitter attribution attached.
Carrying member-level data in the gold cluster table would inflate that table
and violate the cluster/member normalization decided in ADR-0006.

### 4. Embed full comment text in the export

Rejected. Full text stays in `silver.parsed_comments`. The export carries a
~500-char preview so the artifact remains small and inspectable; the UI can
fetch full text on demand.
