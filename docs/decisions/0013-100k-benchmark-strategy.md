# ADR-0013: 100K Benchmark Strategy for FCC Docket 17-108

- Status: Accepted
- Date: 2026-05-23

## Context

As we scale Astroturf from a local 5,000-comment verification slice into a 100,000+ benchmark, we encounter several severe scaling and physical limits of local file systems, standard CPUs, and in-memory algorithms. In federal rulemaking, proceedings can receive tens of millions of public filings (docket `17-108` alone has 22 million). 

The goal of this benchmark is to produce a reproducible, deterministic 100K dataset that mathematically proves four fundamental claims:
1. **Why exact duplicate detection fails**: Naive hashing of text misses nearly all campaign filings that contain slight modifications, typos, custom prefaces, or signatures.
2. **Why semantic clustering is necessary**: Deep semantic embeddings (like BGE-large) capture the underlying template text across varied paraphrases, identifying the full coordinated footprint.
3. **Why local $O(N^2)$ approaches break**: Local similarity comparison scales quadratically in both CPU time and memory space, hitting a hard wall at scale.
4. **Why distributed vector infrastructure becomes mandatory**: Handling production-scale rulemakings requires distributed compute (Spark) and scalable vector search indexes (Databricks Vector Search) to achieve sub-quadratic $O(N \log N)$ complexity.

---

## Decision

We will design a 100K temporal-stratified benchmark running across the medallion layers, with explicit local/distributed boundaries, deterministic ingestion cursors, and deep MLflow observabilities.

### 1. Sampling Strategy (Temporal Strata & API Bypass)

The FCC ECFS API index enforces a hard ceiling of `index.max_result_window=10000`. Once `offset + limit > 10000`, any offset query fails.
To ingest a reproducible, deterministic 100K sample without hitting this ceiling, we partition the docket's active comment period into **10 daily temporal windows (strata)** from late August 2017 (during the peak Broadband for America and other coordinated campaign bursts).

- **Daily Strata**: August 20 to August 29, 2017.
- **Stratum Cap**: Exactly 10,000 comments fetched per day.
- **Determinism**: The filings are fetched sorted by `date_received,ASC` or `date_submission,ASC`. Since ECFS stores filings in a stable index, retrieving the first 10,000 comments of a given day is 100% deterministic and reproducible without random number generators.
- **Manifest**: Ingestion records the counts and time windows in `data/benchmark_sample_manifest.json` as a stable manifest.

### 2. Physical & Scaling Mathematical Projections

| Dimension | Exact-Hash Baseline | Dense Semantic Clustering (Local) | Dense Semantic (Databricks Vector Search) |
| --- | --- | --- | --- |
| **Complexity (CPU/Time)** | $O(N)$ | $O(N^2)$ | $O(N \log N)$ |
| **Complexity (Memory/Space)**| $O(N)$ (hash map lookup) | $O(N^2)$ (dense pairwise matrix) | $O(N)$ (HNSW graph structure) |
| **1K Comments RAM** | ~1 MB | 4 MB | <5 MB |
| **10K Comments RAM** | ~10 MB | 400 MB | ~50 MB |
| **100K Comments RAM** | ~100 MB | **40 GB** (OOM Boundary) | ~500 MB |
| **1M Comments RAM** | ~1 GB | **4 TB** (Impossible) | ~5 GB |

This shows that **dense local clustering breaks at 100K+ comments**, making a distributed or vector-search approach mandatory.

### 3. Why This Requires Databricks

This local bottleneck is the primary architectural proof for Databricks:
1. **Distributed Embedding Generation**: Spark scales the execution of `EmbeddingAgent` across multiple worker nodes, parallelizing the Foundation Model API requests with adaptive rate limiting.
2. **Distributed Nearest-Neighbor Search (Databricks Vector Search)**: Instead of doing $O(N^2)$ pairwise comparisons in-memory, Databricks Vector Search builds a fully managed, distributed HNSW index. The clustering agent queries the index for the top $K$ neighbors per comment, reducing complexity from $O(N^2)$ to $O(N \log N)$ and eliminating the 40GB RAM threshold entirely.
3. **Unity Catalog & Lineage**: Automatically tracks Delta table input/output lineage, ensuring compliance and reproducibility.
4. **MLflow Tracking**: Logs dockets, configs, timing, and lift ratios directly into a central registry.

---

## Consequences

### Positive
- Surfaces the physical bounds of local single-node compute, creating a compelling sales and engineering narrative for Databricks.
- Ingestion cursors bypass the ECFS API's 9999 offset cap deterministically and safely.
- MLflow logs metrics for exact duplicates and semantic clusters side-by-side, providing immediate visualization of the "semantic lift".

### Negative
- Local semantic clustering runs are constrained to a subsample limit to prevent system OOM crashes. This is a deliberate architectural constraint to showcase scale.
