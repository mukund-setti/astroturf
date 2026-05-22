# Databricks Vector Search v1 runbook

This is the **operator's runbook** for standing up the Astroturf Vector Search
v1 platform proof. It is not a strategy document — the strategy lives in
[`databricks-integration.md`](databricks-integration.md), and the architectural
decision lives in [ADR-0007](decisions/0007-databricks-promotion-path.md). Read
those first; this file assumes you already agree with the plan and just need to
execute it.

## What this runbook produces

A model-filtered Vector Search index over
`astroturf.silver.comment_embeddings_bge_large` that a **human reviewer** can
query interactively to inspect nearest neighbors of a chosen comment. That is
the entire v1 scope. The index exists, syncs, and answers similarity queries —
it is a Student Fellows-visible artifact, not a piece of production
infrastructure.

## Why Vector Search v1 is reviewer-only, not wired into ClusteringAgent

`ClusteringAgent` already does candidate generation locally with an all-pairs
cosine path. That path is transparent, deterministic, and fine for the curated
CFPB sample. Replacing it with Vector Search candidate retrieval is a real
infrastructure swap: it changes recall behavior, changes how thresholds
interact with candidate counts, and adds an external dependency to a gold-table
write path that is currently fully local.

ADR-0007 splits this into two phases on purpose:

- **Phase 1 (this runbook).** Create the model-filtered Vector Search index as
  platform proof. Validate the source table/view shape, the embedding column,
  the primary key, and the dimension. Use the index from a reviewer's notebook,
  not from `ClusteringAgent`.
- **Phase 2 (later, out of scope here).** Use Vector Search for candidate
  retrieval inside `ClusteringAgent`, replacing the all-pairs cosine pass.
  Requires re-evaluating recall, threshold semantics, and the gold-table
  contract.

If you find yourself editing anything under `agents/` while following this
runbook, stop — you are doing Phase 2, not Phase 1.

## Prerequisites

Before starting:

- Embeddings have been written to `astroturf.silver.comment_embeddings` by a
  Databricks run of `EmbeddingAgent` with `DatabricksFoundationModelBackend`.
  Rows must carry `embedding_model = 'databricks-bge-large-en'`,
  `embedding_dim = 1024`, and `backend = 'databricks_foundation_model'`. Mock
  rows must not be present in the slice you index.
- You have permission to create endpoints in Databricks Vector Search and
  permission to `CREATE TABLE` and `CREATE OR REPLACE VIEW` in the `astroturf`
  catalog.
- You know the docket scope of the sample (CFPB-2016-0025 for the demo).

If any of those are missing, fix them before continuing. This runbook does not
cover provisioning the catalog, schemas, or the Foundation Model endpoint —
that path is covered by `databricks-integration.md` and is a precondition.

## The 8 steps

The runbook is exactly eight steps. Steps 1–4 prepare the source. Steps 5–6
build and populate the index. Step 7 proves it answers. Step 8 captures
artifacts for the Student Fellows submission.

### Step 1 — Confirm Unity Catalog objects

Verify the catalog/schema/table layout matches
[`databricks-integration.md`](databricks-integration.md#unity-catalog-layout).
Required objects for this runbook:

- Catalog `astroturf` with schemas `bronze`, `silver`, `gold`, `demo`.
- Table `astroturf.silver.comment_embeddings` populated by a Databricks
  Foundation Model embedding run.
- Table `astroturf.silver.parsed_comments` populated from the curated sample.

Do not invent new schemas. If the layout is wrong, fix it upstream and rerun.

### Step 2 — Create the model-filtered source table/view

Vector Search needs a fixed-dimension source. The base
`silver.comment_embeddings` table intentionally stores variable-size vectors so
multiple models can coexist under the compound key
`(comment_id, embedding_model)` (see ADR-0005 and the
[Vector Search mapping](databricks-integration.md#vector-search-mapping)
section in the strategy doc).

Create `astroturf.silver.comment_embeddings_bge_large` as a view over the
filtered slice. Keep this object name verbatim — it is referenced by the
strategy doc, by ADR-0007, and by the notebook in this runbook.

A view is preferred over a materialized table for v1 because the slice is
small, the filter is trivial, and a view stays in sync with the base table
automatically. If a managed Delta table is required for sync mode in Step 6,
materialize the slice there instead and document the choice in the run notes.

### Step 3 — Apply the model-specific filter

The filter is fixed. All three predicates must hold or the index is invalid:

```text
embedding_model = 'databricks-bge-large-en'
embedding_dim   = 1024
backend         = 'databricks_foundation_model'
```

`embedding_model` alone is not sufficient. `embedding_dim` guards against a
schema regression that lets a different-size vector slip through.
`backend` excludes any rows that were written by the local
`sentence-transformers` backend or by the mock backend during smoke tests.

Sanity-check the result before continuing:

- Row count is non-zero and matches the curated sample's substantive-comment
  count.
- `MIN(embedding_dim) = MAX(embedding_dim) = 1024`.
- `COUNT(DISTINCT embedding_model) = 1` and value is
  `databricks-bge-large-en`.
- `COUNT(DISTINCT backend) = 1` and value is `databricks_foundation_model`.
- `COUNT(DISTINCT comment_id) = COUNT(*)`. After filtering to one model,
  `comment_id` must be unique because the base table's compound key is
  `(comment_id, embedding_model)`.

If any sanity check fails, stop and fix the upstream embedding write before
creating the index.

### Step 4 — Enable Delta change data feed if required

Vector Search indexes that sync from a Delta source generally require Delta
change data feed (CDF) on the source. For Databricks-managed sync (Step 6),
enable CDF on the source table backing the view:

```sql
ALTER TABLE astroturf.silver.comment_embeddings
  SET TBLPROPERTIES (delta.enableChangeDataFeed = true);
```

If you materialized the filtered slice as its own Delta table in Step 2, set
the property on that table instead. If the Vector Search SDK accepts the view
directly without CDF for the sync mode you choose, this step is a no-op — but
leave it in the runbook so the operator confirms the property rather than
discovering it missing during sync.

### Step 5 — Create the endpoint and the index

Create (or reuse) a Vector Search endpoint, then create the index over the
filtered source. The names below are non-negotiable for v1:

- **Endpoint name:** `astroturf-vs-endpoint`
- **Source table/view:** `astroturf.silver.comment_embeddings_bge_large`
- **Index name:** `astroturf.silver.comment_embeddings_bge_large_index`
- **Primary key:** `comment_id`
- **Embedding column:** `embedding_vector`
- **Embedding dimension:** `1024`
- **Pipeline type:** triggered (manual) sync for v1 (see Step 6)

The index name lives under the `astroturf.silver` schema so it sits next to the
source it is derived from. The primary key is `comment_id` and only
`comment_id` — it is unique inside the filtered slice (Step 3 sanity check)
even though the base table's primary key is the compound
`(comment_id, embedding_model)`.

### Step 6 — Trigger a manual sync

Use **triggered / manual sync** for v1. Continuous sync may need additional
table-property work and is explicitly out of scope (see the
[Vector Search mapping](databricks-integration.md#vector-search-mapping) risks
list in the strategy doc).

Trigger a sync, then wait for the index to reach a `READY`/`ONLINE` state
before querying. Record the sync duration and the number of rows indexed — both
are evidence artifacts for Step 8. Re-running this runbook should be safe: a
re-triggered sync on an unchanged source is a no-op for query results.

### Step 7 — Run one similarity query

The single required query for v1: given a sample `comment_id` from
`silver.parsed_comments`, return its nearest neighbors and a short text
preview from `parsed_comments` so a human reviewer can judge whether the
neighbors look plausible.

Concretely:

1. Pick a `comment_id` from `silver.parsed_comments` that has a substantive
   `text_source` (i.e. a body the reviewer can read).
2. Look up its `embedding_vector` from
   `astroturf.silver.comment_embeddings_bge_large`.
3. Call the Vector Search index `similarity_search` with that vector and a
   small `num_results` (10 is plenty).
4. Join the results back to `silver.parsed_comments` on `comment_id` to attach
   `title` and a truncated `normalized_text` preview.
5. Eyeball the output. The query comment itself should appear as the top
   result with the highest similarity score. The remaining neighbors should
   look topically related.

The notebook at `notebooks/databricks/vector_search_setup.py` runs this exact
query in its final cell.

### Step 8 — Capture artifacts

For the Student Fellows submission, capture:

- A screenshot of the Vector Search index page showing source, primary key,
  embedding column, dimension, and the `READY`/`ONLINE` state.
- A screenshot or saved output of the Step 7 similarity query showing the
  query comment, its top neighbors, similarity scores, and the joined
  `parsed_comments` preview.
- The row count of the indexed slice and the sync duration recorded in Step 6.

Add these to the evidence set described in
[`databricks-integration.md` → Evidence checklist](databricks-integration.md#evidence-checklist).

## Out of scope for this runbook

Deliberately not covered here:

- Wiring Vector Search into `ClusteringAgent`. That is Phase 2 — see ADR-0007.
- Continuous sync mode. v1 uses triggered/manual sync.
- A `scripts/setup_vector_search.py` helper. Deferred on purpose; the index is
  a one-time setup, and the notebook is the operator surface for v1.
- Indexing additional embedding models. The filter pins the slice to
  `databricks-bge-large-en` for v1.

## Cross-links

- Strategy: [`docs/databricks-integration.md`](databricks-integration.md),
  especially the **Vector Search mapping** section, which is the source for
  table names and filter values.
- Decision: [ADR-0007](decisions/0007-databricks-promotion-path.md).
- Companion notebook:
  [`notebooks/databricks/vector_search_setup.py`](../notebooks/databricks/vector_search_setup.py).
