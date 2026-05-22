# ADR-0007: Promote a small curated sample to Databricks first

- Status: Accepted
- Date: 2026-05-22

## Context

Astroturf already works as a local Delta lakehouse prototype. The agents use
durable medallion tables, local Delta I/O through delta-rs, shared schemas, and
MLflow run logging. The EmbeddingAgent can write real local
`BAAI/bge-large-en-v1.5` embeddings, and the ClusteringAgent can write
deterministic gold cluster tables for a small single-docket/model scope.

The Databricks Student Fellows submission needs proof that Databricks is
load-bearing, not merely a future deployment target. The demo needs visible
Unity Catalog tables, Databricks Foundation Model embeddings, Vector Search,
MLflow tracking, and a Databricks Workflow. At the same time, promoting all
211,885 CFPB-2016-0025 comments immediately would add runtime, API, and
debugging risk before the platform path is proven.

## Decision

Promote a small curated CFPB-2016-0025 sample first, not the full CFPB dataset.
The sample should be large enough to exercise the bronze/silver/gold contracts
and show at least one detected cluster, but small enough to inspect and rerun
quickly.

Use this v1 Databricks path:

```text
small sample -> Unity Catalog tables -> Databricks Foundation Model embeddings
-> silver.comment_embeddings -> model-filtered Vector Search index
-> ClusteringAgent -> dashboard/export table
```

Use Unity Catalog objects under catalog `astroturf`, with schemas `bronze`,
`silver`, `gold`, and `demo`. Use UC volumes for raw imports, attachments, and
exports.

Run embeddings with the Databricks Foundation Model endpoint
`databricks-bge-large-en`, writing rows to `astroturf.silver.comment_embeddings`
with `embedding_model = 'databricks-bge-large-en'`, `embedding_dim = 1024`, and
`backend = 'databricks_foundation_model'`.

Create a model-filtered Vector Search source table or view, such as
`astroturf.silver.comment_embeddings_bge_large`, over only the
`databricks-bge-large-en` / 1024-dimensional / Databricks-backend rows. Create
a Vector Search index from that filtered source.

Treat Vector Search in two phases:

1. Phase 1: create the model-filtered index as platform proof.
2. Phase 2: use Vector Search for candidate retrieval before clustering, so it
   becomes functional infrastructure rather than a decorative screenshot.

Orchestrate the minimum demo with a Databricks Workflow:

1. Load sample tables.
2. Embed.
3. Cluster.
4. Export dashboard data.

For v1 data movement, export the curated local sample to Parquet, upload the
files to a Unity Catalog volume, and create Delta tables in Databricks from
those Parquet files.

## Consequences

Positive:

- Proves the Databricks architecture quickly without waiting for a full
  production migration.
- Keeps demo data small, inspectable, and easy to rerun under deadline pressure.
- Exercises the important Databricks pieces: Unity Catalog, Foundation Models,
  Vector Search, MLflow, and Workflows.
- Avoids unnecessary `regulations.gov` API and rate-limit risk during the first
  Databricks promotion.
- Preserves the local-to-Databricks table shape already defined by the
  medallion architecture and ADR-0005 / ADR-0006.

Negative:

- This is not yet a full production migration.
- It does not prove throughput over all 211,885 CFPB comments.
- Parquet sample promotion is an extra temporary movement step that should be
  replaced or automated later.
- In Phase 1, Vector Search proves the platform source/index path before it
  replaces all-pairs candidate generation in `ClusteringAgent`.
- The Databricks Foundation Model backend is now implemented and mock-tested,
  but this path still needs an approved live Databricks validation run.

## Alternatives considered

### 1. Upload raw Delta directories

Rejected for v1. Local tables are real Delta tables and Databricks should be
able to read them, but moving raw transaction-log directories adds avoidable
compatibility and path-layout risk for the first platform demo. Parquet is a
simpler interchange format for a small curated sample.

### 2. Re-run `regulations.gov` ingestion in Databricks

Rejected for v1. This is the right production direction eventually, but it adds
API credentials, rate limits, paging behavior, and network failures before the
Databricks embedding/index/workflow path is proven.

### 3. Build a Databricks Asset Bundle first

Rejected for v1. Asset Bundles are useful packaging infrastructure, but the
first urgent proof is that the data and agent path works on Databricks. Bundle
packaging can follow once the slice is stable.

### 4. Process all 211,885 CFPB comments immediately

Rejected for v1. The full dataset is the right scale target, but it is too much
to make the first Databricks integration depend on. A small sample is enough to
prove the architecture and produce the Student Fellows evidence.
