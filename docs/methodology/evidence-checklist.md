# Evidence checklist — Student Fellows submission

Actionable checklist of every artifact to capture for the Databricks Student
Fellows application. Each item has a status checkbox and a note for what to
capture and where to put it. Adapted from the Evidence checklist section of
`docs/databricks/integration.md` (the canonical Databricks promotion plan)
and the demo narrative in `docs/methodology/demo-story.md`.

Conventions:

- `[ ]` not yet captured. `[x]` captured.
- Capture screenshots as PNGs under `docs/assets/evidence/` with descriptive
  filenames (e.g., `uc-catalog-tree.png`, `mlflow-embedding-run.png`).
- Keep raw exports (Markdown reports, CSVs) under `data/exports/`.
- Every artifact should be reproducible from a single fresh checkout — note
  the CLI command or notebook path used to produce it.

## Unity Catalog

- [ ] **UC catalog tree screenshot** — `astroturf` catalog visible with
  `bronze`, `silver`, `gold`, and `demo` schemas. Capture from the
  Databricks Catalog Explorer left rail.
- [ ] **`astroturf.bronze.raw_comments`** — table page screenshot showing
  schema, row count (≥ promoted sample size), and the `comment_id`
  uniqueness constraint or table comment. Note the source: imported from
  `astroturf.bronze.raw_imports` volume Parquet.
- [ ] **`astroturf.silver.parsed_comments`** — table page screenshot showing
  schema and the `text_source` distribution (substantive vs. cover-note).
- [ ] **`astroturf.silver.comment_embeddings`** — table page screenshot
  showing schema (compound key `comment_id`, `embedding_model`) and at
  least one row with `embedding_model = databricks-bge-large-en` and
  `embedding_dim = 1024`.
- [ ] **`astroturf.silver.comment_embeddings_bge_large`** — model-filtered
  table or materialized view screenshot, showing the filter and the
  fixed-dimension row shape (the source the Vector Search index reads).
- [ ] **`astroturf.gold.comment_clusters`** — table page screenshot showing
  the EPA cluster scope: `docket_id = EPA-HQ-OAR-2021-0317`,
  `embedding_model = databricks-bge-large-en`, `clustering_version =
  v1_threshold_0.92` (or current label), and the 13-cluster row count.
- [ ] **`astroturf.gold.comment_cluster_memberships`** — table page
  screenshot showing 162 memberships for the same scope and the largest
  cluster's 123 rows.
- [ ] **`astroturf.demo.cluster_review_export`** — table page screenshot of
  the dashboard-ready join (clusters + memberships + sample text). This is
  the UI contract.
- [ ] **Volumes** — at minimum `astroturf.bronze.raw_imports` and
  `astroturf.demo.exports` visible in the UC volumes view.

## MLflow

- [ ] **Embedding run** — MLflow run page screenshot showing:
  - `backend = databricks_foundation_model`
  - `embedding_model = databricks-bge-large-en`
  - `batch_size = 16`
  - `embedding_dim = 1024`
  - metrics: request count, retry count, embedded text count, total run
    duration, Foundation Model backend latency.
- [ ] **Clustering run** — MLflow run page screenshot showing candidate
  count (396 for EPA), pair count, edge count, cluster count (13),
  membership count (162), threshold (0.92), and `clustering_version`.
- [ ] **Exact-hash baseline run** — MLflow run page screenshot showing
  candidate count (396), duplicate-hash cluster count (7), membership
  count (16), largest cluster size (4), and `clustering_version =
  v1_exact_hash`.
- [ ] **Experiment list** — MLflow experiments page screenshot showing the
  three runs above grouped under the Astroturf experiment.

## Vector Search

- [ ] **Index detail screenshot** — Vector Search index page for
  `astroturf.silver.comment_embeddings_bge_large_index`, showing:
  - primary key = `comment_id`
  - embedding column = `embedding_vector`
  - dimension = `1024`
  - source = `astroturf.silver.comment_embeddings_bge_large`
  - sync mode = triggered/manual.
- [ ] **One nearest-neighbour query screenshot** — Vector Search query
  output for a representative comment from the 123-member EPA cluster,
  showing the top-K neighbours and their cosine scores. Validates that
  the index reproduces the cluster signal.

## Databricks Workflow

- [ ] **Workflow DAG screenshot** — `astroturf-cfpb-demo` (or rename
  `astroturf-epa-demo` once the lead docket is EPA) showing the four
  tasks:
  1. `load_sample_tables`
  2. `embed`
  3. `cluster`
  4. `export_dashboard_data`
- [ ] **Successful run screenshot** — Workflow run page with all four
  tasks green and a total duration. Link the MLflow runs from each task.

## UI screenshots

- [ ] **Debug UI — bronze tab** — Streamlit debug app at `debug_ui/app.py`
  showing `bronze.raw_comments` row counts and schema for the EPA docket.
  Internal tool; capture but label as "engineering inspection."
- [ ] **Debug UI — silver tab** — `silver.parsed_comments` with
  `text_source` distribution for EPA.
- [ ] **Debug UI — clusters tab** — full cluster evidence panel for the
  123-member EPA cluster: representative text, sample members with
  similarity scores, campaign-style classification
  (`embedding/paraphrase-driven`).
- [ ] **Debug UI — exact-hash baseline tab** — the 7-cluster, 16-membership
  view of literal duplicates on EPA, shown next to the embedding clusters
  so the lift is visible.
- [ ] **Demo UI — cluster list** — (when built) the reviewer-facing
  Streamlit / Databricks App listing clusters with size, threshold, and a
  one-line snippet.
- [ ] **Demo UI — cluster detail** — (when built) one cluster on the
  screen: size, threshold, representative template, three sample
  comments side-by-side, submission timeline spike.

## GitHub artifacts

- [ ] **Repository link** — public GitHub URL of the Astroturf repo.
- [ ] **README** — README at the repo root introduces the project, points
  to `docs/architecture/system-map.md`, `docs/methodology/demo-story.md`,
  `docs/databricks/integration.md`, and this checklist.
- [ ] **Architecture docs** — `docs/architecture/architecture.md`,
  `docs/architecture/system-map.md`, `docs/methodology/demo-story.md`,
  `docs/databricks/integration.md`, `docs/databricks/vector-search.md`,
  `docs/operations/attachment-extraction-plan.md`,
  `docs/operations/test-dockets.md` all present and current.
- [ ] **ADRs present** — `docs/decisions/` contains:
  - ADR-0001 multi-agent durable stages
  - ADR-0002 deltalake for local bronze
  - ADR-0003 parser detail enrichment side tables
  - ADR-0004 additive schema evolution
  - ADR-0005 embedding backend and model
  - ADR-0006 cluster identity and gold table layout
  - ADR-0007 Databricks promotion path
  - ADR-0008 attachment text extraction silver table
  - ADR-0009 cluster review export table
- [ ] **Commit log highlight** — link to the GitHub compare or commits view
  showing the path from `IngestionAgent` → `ClusteringAgent` →
  `ExactHashBaseline` → `DatabricksFoundationModelBackend`. The point is
  that the Databricks promotion path was intentional, not improvised.
- [ ] **Tests green** — CI badge or local `pytest` screenshot showing 92+
  unit tests passing, Ruff clean, Ruff format clean.

## Data exports

- [ ] **EPA cluster evidence Markdown** —
  `data/exports/cluster_evidence_EPA-HQ-OAR-2021-0317.md` (already
  generated). Confirm it shows 13 clusters, 162 memberships, primary
  cluster size 123, and campaign-style classifications.
- [ ] **CFPB pipeline-shape note** — short note (in the demo or system map)
  acknowledging that the CFPB sample yields only 11 substantive in-line
  embeddings because most content lives in attachments, and that v2B
  attachment extraction is the next milestone.

## Narrative artifacts

- [ ] **60-second demo script** — present in `docs/methodology/demo-story.md` Act 1,
  rehearsed.
- [ ] **Reviewer pitch paragraph** — present in `docs/methodology/demo-story.md`,
  copy-paste-ready for the application form.
- [ ] **Cut list and stretch goals** — present in `docs/methodology/demo-story.md`, so
  the submission is honest about what is in v1 vs. what is aspirational.

## Final submission package

- [ ] **Application form filled** — Student Fellows form completed with
  the reviewer pitch paragraph from `docs/methodology/demo-story.md`.
- [ ] **Screenshots bundled** — all `docs/assets/evidence/*.png` referenced
  from the application or attached.
- [ ] **Repo link verified** — public, clean main branch, README front and
  centre.
- [ ] **Sanity pass** — re-read `docs/architecture/system-map.md` and
  `docs/methodology/demo-story.md` end-to-end to make sure no claim contradicts what
  the screenshots actually show.
