# Databricks integration plan

This document is the Databricks promotion path for the Student Fellows demo. It
turns the local lakehouse prototype into the smallest credible Databricks slice
without trying to migrate the full CFPB dataset before the platform proof is
visible.

The direction of record is:

```text
small sample -> Unity Catalog tables -> Databricks Foundation Model embeddings
-> silver.comment_embeddings -> model-filtered Vector Search index
-> ClusteringAgent -> dashboard/export table
```

## Minimum credible Databricks demo path

The smallest slice that proves Databricks is load-bearing is:

1. Curate a small local sample from CFPB-2016-0025 that includes the substantive
   parsed comments and at least one known cluster candidate.
2. Export the sample as Parquet and upload it to a Unity Catalog volume.
3. Create Unity Catalog Delta tables for the promoted bronze and silver sample.
4. Run `EmbeddingAgent` on Databricks with `DatabricksFoundationModelBackend`,
   writing `astroturf.silver.comment_embeddings`.
5. Create a model-filtered Vector Search index over the Databricks-generated
   embedding rows.
6. Run `ClusteringAgent` against the Databricks-produced embeddings for one
   docket/model/threshold scope.
7. Export a dashboard-ready table that joins clusters, memberships, and parsed
   comments so the UI can show cluster size, threshold, representative/sample
   text, and supporting evidence.

This path does not need all 211,885 CFPB comments. The point of v1 is to prove
that Databricks is part of the working system: governed tables, Foundation Model
embeddings, Vector Search, MLflow, and Workflows.

## Unity Catalog layout

Use one project catalog:

```text
astroturf
```

Schemas:

- `astroturf.bronze` - raw and minimally transformed source records.
- `astroturf.silver` - parsed text, details, attachments, and embeddings.
- `astroturf.gold` - campaign clusters, memberships, attributions, and rule
  migrations.
- `astroturf.demo` - dashboard-ready exports and application-facing views.

Tables:

| Layer | Unity Catalog table | Purpose |
| --- | --- | --- |
| Bronze | `astroturf.bronze.raw_comments` | Comment records from `regulations.gov`; idempotent on `comment_id`. |
| Silver | `astroturf.silver.parsed_comments` | Normalized comment text and text provenance. |
| Silver | `astroturf.silver.comment_details` | Raw detail JSON and enrichment provenance. |
| Silver | `astroturf.silver.comment_attachments` | Attachment metadata and download/extraction state. |
| Silver | `astroturf.silver.comment_embeddings` | Dense vectors keyed by `(comment_id, embedding_model)`. |
| Silver | `astroturf.silver.comment_embeddings_bge_large` | Model-filtered table/view for Vector Search. |
| Gold | `astroturf.gold.comment_clusters` | One row per detected cluster/component. |
| Gold | `astroturf.gold.comment_cluster_memberships` | One row per `(cluster_id, comment_id)` membership. |
| Gold | `astroturf.gold.campaign_attributions` | Future attribution evidence. |
| Gold | `astroturf.gold.rule_migrations` | Future final-rule language matches. |
| Demo | `astroturf.demo.cluster_review_export` | UI-ready join of clusters, memberships, and sample text. |

Volumes:

| Volume | Purpose |
| --- | --- |
| `astroturf.bronze.raw_imports` | Uploaded Parquet samples from the local lakehouse. |
| `astroturf.silver.attachments` | Downloaded PDFs/DOCX files and later extracted text artifacts. |
| `astroturf.demo.exports` | Dashboard snapshots, application exports, and evidence artifacts. |

## Local-to-Databricks mapping

| Local path | Unity Catalog object |
| --- | --- |
| `./data/bronze/raw_comments` | `astroturf.bronze.raw_comments` |
| `./data/silver/parsed_comments` | `astroturf.silver.parsed_comments` |
| `./data/silver/comment_details` | `astroturf.silver.comment_details` |
| `./data/silver/comment_attachments` | `astroturf.silver.comment_attachments` |
| `./data/silver/comment_embeddings` | `astroturf.silver.comment_embeddings` |
| `./data/gold/comment_clusters` | `astroturf.gold.comment_clusters` |
| `./data/gold/comment_cluster_memberships` | `astroturf.gold.comment_cluster_memberships` |
| `./data/gold/campaign_attributions` | `astroturf.gold.campaign_attributions` |
| `./data/gold/rule_migrations` | `astroturf.gold.rule_migrations` |

## Data movement plan

For v1, move a small curated sample by exporting local tables to Parquet,
uploading those Parquet files to `astroturf.bronze.raw_imports`, and creating
Unity Catalog Delta tables from them.

This is the preferred first path because it is:

- Small enough to inspect manually.
- Less brittle than uploading local Delta transaction logs.
- Faster than re-running `regulations.gov` ingestion in Databricks.
- Independent of Databricks Asset Bundles, which can come after the platform
  proof is working.

The sample should include the minimum set needed for the demo:

- `bronze.raw_comments` rows for the selected comments.
- `silver.parsed_comments` rows with substantive `text_source` values.
- Optional `silver.comment_details` rows for provenance screenshots.
- Optional `silver.comment_attachments` rows only if the UI needs to explain
  deferred attachment extraction.

## Foundation Model backend requirements

`DatabricksFoundationModelBackend` is implemented against the Databricks SDK
with `model_name = "databricks-bge-large-en"`, `dimension = 1024`, and
`backend_name = "databricks_foundation_model"`. It is mock-tested locally; the
remaining runtime work is an explicitly approved live Databricks validation run.

Implementation requirements:

- Use the Databricks Foundation Model endpoint `databricks-bge-large-en`.
- Preserve the `EmbeddingBackend.encode(texts: list[str]) -> list[list[float]]`
  contract.
- Batch requests using `EmbeddingInput.batch_size`; start with 16 or 32 rows
  per batch.
- Send request payloads shaped around a list of input strings.
- Normalize the endpoint response into one float vector per input string.
- Validate that the response count equals the input count.
- Validate that every vector has dimension 1024.
- Return float vectors suitable for `embedding_vector`.
- Retry transient failures such as 429, timeout, and 5xx with exponential
  backoff, then raise after retries.
- Prefer Databricks-native credentials inside Workflows. For local fallback,
  use `DATABRICKS_HOST` and `DATABRICKS_TOKEN` or equivalent secret-backed
  configuration.
- Log MLflow parameters for endpoint/model name, backend, batch size, and
  embedding dimension.
- Add MLflow metrics for request count, retry count, failed batches, embedded
  text count, total run duration, and Foundation Model backend latency.

The stored `embedding_model` for Databricks-generated rows should be
`databricks-bge-large-en` so `ClusteringAgent` and Vector Search can target a
single production model slice.

## Vector Search mapping

`silver.comment_embeddings` intentionally stores variable-size vectors so
multiple models can coexist under the compound key `(comment_id,
embedding_model)`. Vector Search needs a fixed-dimension source, so Databricks
must index a model-specific slice.

Create a model-filtered table or materialized view:

```text
astroturf.silver.comment_embeddings_bge_large
```

Filter:

```text
embedding_model = 'databricks-bge-large-en'
embedding_dim = 1024
backend = 'databricks_foundation_model'
```

Index mapping:

- Source table/view: `astroturf.silver.comment_embeddings_bge_large`
- Index name: `astroturf.silver.comment_embeddings_bge_large_index`
- Primary key: `comment_id`
- Embedding column: `embedding_vector`
- Dimension: `1024`
- Sync mode for v1: triggered/manual sync

Phased target:

1. Phase 1: create the model-filtered Vector Search index as platform proof.
   This gives a concrete Student Fellows artifact and validates the source table
   shape.
2. Phase 2: use Vector Search for candidate retrieval before clustering. The
   current `ClusteringAgent` all-pairs cosine path is transparent and fine for a
   small sample, but it should not remain the production candidate-generation
   strategy.

Risks:

- Indexing the unfiltered base table could mix models or dimensions.
- `comment_id` is only sufficient as the primary key after filtering to one
  embedding model.
- Mock rows must be excluded from the index.
- Continuous sync may need table-property work; use triggered/manual sync first.

## Minimal Databricks Workflow

Workflow name:

```text
astroturf-cfpb-demo
```

Tasks:

1. `load_sample_tables`
   - Read Parquet sample files from `astroturf.bronze.raw_imports`.
   - Create or replace the small-sample Unity Catalog Delta tables.
   - Output at least `astroturf.bronze.raw_comments` and
     `astroturf.silver.parsed_comments`.

2. `embed`
   - Run `EmbeddingAgent` with `DatabricksFoundationModelBackend`.
   - Read `astroturf.silver.parsed_comments`.
   - Write `astroturf.silver.comment_embeddings`.
   - Log an MLflow run.

3. `cluster`
   - Run `ClusteringAgent` for docket `CFPB-2016-0025`, model
     `databricks-bge-large-en`, and the selected threshold.
   - Read `astroturf.silver.comment_embeddings`.
   - Write `astroturf.gold.comment_clusters` and
     `astroturf.gold.comment_cluster_memberships`.
   - Log an MLflow run.

4. `export_dashboard_data`
   - Join clusters, memberships, parsed comments, and optional raw comment
     metadata.
   - Write `astroturf.demo.cluster_review_export`.
   - Keep this table stable for the debug/final UI.

## Evidence checklist

Capture these artifacts for the Student Fellows application:

- Unity Catalog screenshot showing `astroturf` with `bronze`, `silver`, `gold`,
  and `demo` schemas.
- Unity Catalog table screenshots for `raw_comments`, `parsed_comments`,
  `comment_embeddings`, `comment_clusters`, and `comment_cluster_memberships`.
- MLflow embedding run showing `backend = databricks_foundation_model`,
  `embedding_model = databricks-bge-large-en`, row counts, and latency metrics.
- MLflow clustering run showing candidate count, threshold, edge count,
  cluster count, and membership count.
- Vector Search screenshot showing the model-filtered index, primary key,
  embedding column, and dimension.
- Workflow screenshot showing the four-task DAG and a successful run.
- UI screenshot showing one cluster with size, threshold, representative or
  sample text, and sample comments.
- GitHub commits and ADRs showing that the Databricks promotion path was
  intentional, not improvised.

## Cut list

Must-have:

- Small curated sample promoted to Unity Catalog tables.
- `DatabricksFoundationModelBackend` producing rows in
  `astroturf.silver.comment_embeddings`.
- MLflow runs from Databricks for embedding and clustering.
- Gold cluster and membership tables from Databricks-generated embeddings.
- Dashboard/export table for one visible cluster.
- Screenshots for Unity Catalog, MLflow, Workflow, and the UI.

Strongly desirable:

- Model-filtered Vector Search index over `comment_embeddings_bge_large`.
- Workflow with all four tasks green.
- `astroturf.demo.cluster_review_export` as the UI contract.

Nice-to-have:

- Vector Search candidate retrieval wired into clustering.
- Continuous Vector Search sync.
- Databricks Asset Bundle packaging.
- Full 211,885-comment CFPB run.
- Attachment text extraction.
- AttributionAgent.
- MigrationAgent.
- Second docket.
- Live Databricks run during the presentation.
