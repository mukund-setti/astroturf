# ADR-0006: Cluster identity and gold table layout

## Context

Astroturf needs its first gold-layer output: detected public-comment campaign
clusters derived from `silver.comment_embeddings`. The v1 implementation is a
local prototype over one docket and one `embedding_model` at a time. It uses
pairwise cosine similarity and connected components, which is appropriate for
small and medium local samples but not the final production candidate-generation
strategy.

The output must be idempotent. Rerunning the same deterministic clustering scope
must not leave stale rows behind, and cluster provenance must show which text
hashes and embedding backend produced the result.

## Decision

Create two gold Delta tables:

- `gold.comment_clusters`: one row per detected component.
- `gold.comment_cluster_memberships`: one row per `(cluster_id, comment_id)`.

Both tables include:

- `clustering_run_id`, a deterministic hash of `docket_id`, `embedding_model`,
  `clustering_version`, `similarity_threshold`, sorted candidate `comment_id`s,
  and sorted candidate `text_hash`es.
- `embedding_backend`, so reviewers can distinguish local
  `sentence-transformers`, Databricks Foundation Model, and mock/debug runs.
- `clustering_version` and `similarity_threshold`, which define the exact output
  scope together with `docket_id` and `embedding_model`.

Cluster IDs are content-addressed hashes of the clustering version, docket,
embedding model, threshold, and sorted member IDs. They are stable for the same
component membership, but they are not permanent campaign IDs. A future product
layer can assign human-facing campaign identities after review.

For each exact scope:

```text
docket_id + embedding_model + clustering_version + similarity_threshold
```

the writer first deletes existing rows from both gold tables, then writes the
new deterministic output via Delta MERGE. This scoped replacement is allowed for
derived gold outputs because it is not a blind append: it replaces exactly one
recomputable result scope.

`gold.comment_clusters` stores `representative_comment_id` and
`representative_text_hash`, but not the representative text itself. Long text
stays in `silver.parsed_comments`; the UI can join to silver when needed.

## Consequences

- Reruns are idempotent for a given clustering scope.
- Changes in source text hashes produce a new `clustering_run_id`, making
  provenance visible even if cluster membership is unchanged.
- Old outputs for the same scope cannot coexist with fresh results.
- Outputs from different thresholds, versions, dockets, or embedding models can
  coexist.
- Pairwise cosine is simple and transparent, but it is O(n^2) and must be
  guarded by `max_rows` for local experimentation.

## Alternatives

- Random UUID cluster IDs. Rejected because reruns would not be naturally
  idempotent.
- A single table with nested member arrays. Rejected because membership joins,
  review UI queries, and scoped replacement are cleaner with a normalized
  membership table.
- Persisting all pairwise edges. Rejected for v1 because it is noisy and grows
  quickly. Edge counts are logged to MLflow instead.
- DBSCAN or HDBSCAN. Deferred; connected components over a threshold is easier
  to explain and test for the first prototype.
- Databricks Vector Search for candidate generation. This is the intended later
  path; it will replace local all-pairs candidate generation when clustering is
  moved onto larger production slices.
