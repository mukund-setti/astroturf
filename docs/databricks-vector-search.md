# Databricks Vector Search runbook

This is the operator runbook for the Astroturf Vector Search production
clustering path. Strategy lives in `docs/databricks-integration.md`; this file
is the concrete setup and operating surface.

## What This Produces

A model-filtered Vector Search index over
`astroturf.silver.comment_embeddings_bge_large` that `ClusteringAgent` can use
with `clustering_mode="vector_search"` to retrieve sparse nearest-neighbor
candidates. The same index can still be queried interactively by a reviewer,
but Phase 5 makes it load-bearing: candidate retrieval comes from Vector
Search, then the agent builds connected components and writes the existing gold
tables without changing their schemas.

The local all-pairs cosine path remains available for small local runs and unit
tests. It must not be used as the production strategy for large dockets because
it scales quadratically.

## Production Path

In Databricks mode, `scripts/run_docket_pipeline.py` passes
`clustering_mode="vector_search"` plus a configured `vector_index_name`.
`ClusteringAgent` then:

1. Loads the docket/model embedding slice.
2. Queries Vector Search for the top `vector_search_limit` neighbors per
   comment.
3. Filters returned neighbors by `similarity_threshold`.
4. Constructs sparse connected components from candidate edges.
5. Writes `gold.comment_clusters` and `gold.comment_cluster_memberships` using
   the existing schemas.

Threshold semantics are still cosine-score semantics, but recall also depends
on `vector_search_limit`. Increase that limit for larger or more diverse
dockets if reviewer validation shows missed near-duplicates.

## Required Objects

- Endpoint: `astroturf-vs-endpoint`
- Source table or materialized view:
  `astroturf.silver.comment_embeddings_bge_large`
- Index: `astroturf.silver.comment_embeddings_bge_large_index`
- Primary key: `comment_id`
- Embedding column: `embedding_vector`
- Embedding dimension: `1024`
- Sync mode: triggered/manual

The source slice must filter:

```sql
embedding_model = 'databricks-bge-large-en'
AND embedding_dim = 1024
AND backend = 'databricks_foundation_model'
```

## Manage The Index

Create the endpoint and index:

```bash
python scripts/manage_vector_index.py \
  --endpoint astroturf-vs-endpoint \
  create \
  --index astroturf.silver.comment_embeddings_bge_large_index \
  --source-table astroturf.silver.comment_embeddings_bge_large \
  --primary-key comment_id \
  --embedding-col embedding_vector \
  --dimension 1024
```

Trigger a sync and wait:

```bash
python scripts/manage_vector_index.py \
  --endpoint astroturf-vs-endpoint \
  sync \
  --index astroturf.silver.comment_embeddings_bge_large_index
```

Check status:

```bash
python scripts/manage_vector_index.py \
  --endpoint astroturf-vs-endpoint \
  status \
  --index astroturf.silver.comment_embeddings_bge_large_index
```

Delete only with the explicit destructive command:

```bash
python scripts/manage_vector_index.py \
  --endpoint astroturf-vs-endpoint \
  delete-confirmed \
  --index astroturf.silver.comment_embeddings_bge_large_index
```

## Pipeline Dry Run

Confirm the Databricks routing plan without writing gold rows:

```bash
python scripts/run_docket_pipeline.py \
  --docket-id 17-108 \
  --mode databricks \
  --stages cluster \
  --dry-run \
  --vector-index-name astroturf.silver.comment_embeddings_bge_large_index
```

## Evidence To Capture

- Vector Search endpoint and index status.
- Indexed row count after sync.
- One direct nearest-neighbor query showing plausible neighbors.
- One `ClusteringAgent` MLflow run with `mode=vector_search`,
  `vector_index_name`, `comments_considered`, `clusters_found`,
  `largest_cluster_size`, `coverage`, and `runtime_seconds`.

## Out Of Scope

- Continuous sync mode.
- Indexing additional embedding models.
- Changing gold cluster or membership schemas.
