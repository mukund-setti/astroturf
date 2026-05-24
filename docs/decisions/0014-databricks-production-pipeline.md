# ADR-0014: Databricks Production Pipeline Strategy

- **Status**: Proposed
- **Date**: 2026-05-24

## Context

Astroturf has successfully expanded from a single-docket Net Neutrality showcase into a multi-topic, multi-agency regulatory intelligence platform. The Next.js frontend now features topics such as Telecom, Oil & Gas, and Finance, showing different agencies (FCC, EPA, CFPB) and their respective dockets (`17-108`, `EPA-HQ-OAR-2021-0317`, `CFPB-2016-0025`).

However, the backend pipeline presents a major architectural bottleneck:
1.  **Memory Wall ($O(N^2)$)**: Local connected-components clustering calculates all pairwise cosine similarities using dense vectors in a single matrix multiplication. While this is deterministic and simple for small samples, it scales quadratically and crashes with out-of-memory (OOM) errors on large dockets (e.g. 100K+ Net Neutrality or Payday lending comments).
2.  **Disjoint Orchestration**: Executing the pipeline requires invoking multiple separate scripts with manually matched command-line options.
3.  **Incomplete Databricks Setup**: While `DatabricksFoundationModelBackend` and manual Vector Search indexes exist, they are isolated showcase pieces rather than integrated components of a production-ready, repeatable lakehouse application.

To support true high-throughput processing over 100K+ comments, we must establish a repeatable platform pipeline and integrate Databricks-native capabilities directly into the core agents.

---

## Decision

We will transition Astroturf into a production-grade, dual-mode platform. The architectural decisions are structured as follows:

### 1. Local vs. Databricks Execution Modes
We will support two first-class execution modes throughout the pipeline:
*   **Local Mode (`--mode local`)**:
    *   Reads and writes to local Delta tables under `./data/`.
    *   Uses pluggable local backends (e.g., `sentence-transformers` or deterministic `mock` for testing).
    *   Performs standard local all-pairs cosine clustering (limited to small, curated scopes to protect memory).
    *   Exports UI review datasets as local Parquet files under `./data/exports/`.
*   **Databricks Mode (`--mode databricks`)**:
    *   Reads and writes to governed Unity Catalog tables under the `astroturf` catalog (schemas `bronze`, `silver`, `gold`, `demo`).
    *   Utilizes the Databricks Foundation Model API endpoint `databricks-bge-large-en` to generate high-quality dense vectors.
    *   Coordinates with Databricks Vector Search to perform trigger-based synchronization and high-performance candidate retrieval.
    *   Executes denormalized UI exports directly against the Databricks SQL Warehouse to hydrate the governed production table `workspace.demo.cluster_review_export`.

### 2. Medallion Storage: Local Delta vs. Unity Catalog
*   Medallion tables share identical schemas across both modes (derived from shared Pydantic models).
*   **Local delta-rs**: Uses the local file system with `delta-rs` for C-based Spark-free Delta Lake access, keeping local developer setups light and dependency-free.
*   **Unity Catalog (UC)**: Governs catalog schemas on cloud object storage. In Databricks mode, agents read/write to UC tables using catalog prefixes (e.g., `workspace.silver.parsed_comments`), with full support for Unity Catalog Volumes for attachments and exports.

### 3. Embedding Backend Strategy
*   In Databricks mode, the pipeline strictly uses the `DatabricksFoundationModelBackend` fronting `databricks-bge-large-en` (1024 dimensions).
*   **Batching Optimization**: We will enforce a default batch size of 16 (down from 32) when using the Foundation Model API to prevent transient serving endpoint hangs.
*   **Idempotency & Checkpointing**: Comments are uniquely identified by `comment_id`. Embeddings are merged using a compound primary key `(comment_id, embedding_model)`. Cache matches are checked via `normalized_text_hash` before calling the FM API, preventing redundant and costly API calls.

### 4. Vector Search Endpoint & Indexing Strategy
To break the local $O(N^2)$ memory wall, we will introduce a native Vector Search candidate retrieval path in `ClusteringAgent`:
1.  **View Generation**: Materialize/filter the embedding slice using the predicates: `embedding_model = 'databricks-bge-large-en'`, `embedding_dim = 1024`, and `backend = 'databricks_foundation_model'`. The target is `astroturf.silver.comment_embeddings_bge_large`.
2.  **Triggered Sync**: Sync the view to `astroturf.silver.comment_embeddings_bge_large_index` on endpoint `astroturf-vs-endpoint`.
3.  **Candidate Retrieval**:
    *   For each comment, instead of calculating all-pairs similarities, we call the Vector Search similarity search endpoint with its dense vector.
    *   Retrieve the top $K$ nearest neighbors (e.g., $K = 100$) that exceed the similarity threshold (e.g., $0.92$).
    *   Insert an edge between the comment and each of its qualified neighbors.
    *   Construct connected components from this sparse graph.
    *   This scales linearly $O(N)$ on the client side, allowing the pipeline to easily cluster 100K+ comments.

```text
Embeddings Table 
  → Filtered View (Model Slice)
  → Vector Search Index Sync
  → Clustering Agent Queries Index (Candidate Retrieval)
  → Sparse Graph Construction
  → Connected Components -> Gold Clusters
```

### 5. Orchestration Strategy
We will introduce a central pipeline runner (`scripts/run_docket_pipeline.py`) that acts as the platform orchestrator.
*   It accepts a unified docket config (`configs/dockets.yaml`) defining rules, dates, APIs, expected scale, and modes.
*   It executes the pipeline stages (`ingest`, `parse`, `embed`, `cluster`, `export`) sequentially.
*   It encapsulates stage sequence logic without embedding business rules, delegating operations to specialized agents.
*   It supports resume capability by leveraging the agents' built-in table checkpoints.

### 6. Failure Recovery Model
*   All external API calls (regulations.gov detail GETs, Databricks FM embeddings, and Vector Search queries) utilize `tenacity` retrying with exponential backoff (`stop_after_attempt=3` or `5`, `wait_exponential`).
*   Recoverable exceptions (HTTP 429 rate limits, HTTP 503 gateway timeouts, network drops) are retried; unrecoverable errors (400 Bad Request, 404 Not Found, authentication failures) abort immediately to prevent infinite loops.

### 7. MLflow Observability & Lineage Model
To ensure auditability, every execution logs a clear hierarchy of runs:
*   **Orchestrator Run**: A parent MLflow run tracking docket metadata, start-end parameters, and stage status.
*   **Agent Runs**: Nested child runs tracking specific metrics:
    *   *Embedding Agent*: token counts, API throughput, server latency, and cache hits.
    *   *Clustering Agent*: similarity threshold, graph edge count, cluster count, largest cluster size, and search mode (`local` vs. `vector_search`).

### 8. UI Hydration & Gold-to-Demo Materialization
*   The final stage denormalizes gold tables into a single UI-ready flat layout `demo.cluster_review_export`.
*   **Local**: Writes a single Parquet file to `./data/exports/cluster_review_export/`.
*   **Databricks**: Performs a high-performance `CREATE OR REPLACE TABLE` (or `MERGE` for incremental updates) directly against the SQL Warehouse. The Next.js frontend connects directly to this table, getting instant updates without complex joins.

---

## Consequences

### Positive
*   **Scalability**: Overcomes the $O(N^2)$ local memory bottleneck, making 100K+ docket sizes computationally feasible.
*   **Repeatability**: New dockets can be added by declaring them in `configs/dockets.yaml` and calling the pipeline runner.
*   **Observability**: Detailed parent-child runs in MLflow provide clear pipeline lineage and audit history.
*   **UI Hydration**: Eliminates on-the-fly SQL joins, providing extremely fast page load speeds in the frontend.

### Negative
*   **Hybrid Dependency**: Databricks mode requires a connection to a live Databricks workspace with active credentials, which must be guarded with clear environment readiness diagnostics.
*   **Triggered Sync Latency**: The manual sync of the Vector Search index introduces a delay during the pipeline run (typically 1–2 minutes). This is a necessary trade-off for consistency.

---

## Alternatives Considered

### 1. materializing Vector Search as Continuous Sync
*   *Rejected for v1*: Continuous sync requires complex setup, tables backed by Delta Change Data Feed, and constantly running pipelines that inflate cloud costs. Triggered sync is clean, deterministic, and cost-efficient.

### 2. Spark-Based All-Pairs Join
*   *Rejected*: Running cross-joins or cosine joins in Spark over large scales still suffers from $O(N^2)$ shuffle overflows. Vector Search indexes use optimized HNSW algorithms that provide sub-second search speeds.
