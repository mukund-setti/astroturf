# Astroturf: Product Vision & Scaling Strategy

Astroturf is a semantic intelligence platform designed to trace organized influence campaigns (astroturfing) across federal rulemaking. While flagship investigations like the FCC's 2017 Net Neutrality proceeding serve as high-fidelity showcases of the platform's analytical lift, the underlying codebase and medallion lakehouse architecture are fully generalized to support horizontal scaling across any topic, agency, or docket.

---

## 1. Core Architectural Generalization

Astroturf separates the data orchestration and machine learning pipeline from front-facing product exploration. Instead of hardcoding specialized rules for specific agencies, the platform models public participation using four generalized entities:

```
  ┌───────────────┐
  │     Topic     │ (Broad policy domains, e.g. Telecom, Oil & Gas)
  └───────┬───────┘
          │ 1
          │ *
  ┌───────▼───────┐
  │    Docket     │ (Monitored rulemakings under a specific Topic)
  └───────┬───────┘
          │ 1
          │ *
  ┌───────▼───────┐
  │   Campaign    │ (Identified clusters of highly similar comments)
  └───────┬───────┘
          │ 1
          │ *
  ┌───────▼───────┐
  │    Comment    │ (Individual public filings submitted by citizens)
  └───────────────┘
```

These entities correspond directly to partitions and indices within our **Databricks Medallion Lakehouse**:

1. **Bronze (Raw Ingestion)**: `bronze.raw_comments` maps incoming ECFS and Regulations.gov API payloads to a unified schema partitioned by `docket_id`.
2. **Silver (Cleaned & Parsed)**: `silver.parsed_comments` extracts comment bodies, strips HTML noise, and computes temporal windows, remaining source-agnostic.
3. **Silver (Embeddings Index)**: `silver.comment_embeddings` serves as our vector search source, storing 1024-dimensional semantic arrays generated via the Databricks Foundation Model API (`databricks-bge-large-en`).
4. **Gold (Analytical Dossiers)**: `gold.comment_clusters` and `gold.campaign_attributions` group comments using MinHash/LSH candidate generation and confirm membership via cosine similarity thresholds.

---

## 2. Generalizing Beyond Net Neutrality

To scale from one flagship demo to hundreds of active dockets, Astroturf handles data hydration at different maturity tiers:

| Tier | Status | Data Support | Example |
| :--- | :--- | :--- | :--- |
| **Tier 1: Analyzed (Flagship)** | Full Semantic Dossier | Deep learning clustering, repeated boilerplate phrases, submission velocity histogram, medoid template mutations. | FCC `17-108` (Net Neutrality) |
| **Tier 2: Partially Processed** | Baseline-Only | Character-level exact-hash deduplication and simple string match metrics. Awaiting distributed Vector Search clustering. | EPA `EPA-HQ-OAR-2021-0317` (Methane) |
| **Tier 3: Ingestion Ready** | Configured, Awaiting Run | Metadata can be registered and converted into pipeline commands, but it is not presented as an analyzed dashboard until clustering/export evidence exists. | CFPB `CFPB-2016-0025` (Payday Loans) |

---

## MVP Coverage Policy

Astroturf's public product should never send a reviewer to a polished page that
basically says "nothing here." Coverage is therefore governed by four explicit
states:

| State | Product Treatment | Current Examples |
| :--- | :--- | :--- |
| **Analyzed** | Appears prominently in primary browsing with semantic campaign evidence, validation status, and links to dockets/campaigns. | Telecom / Net Neutrality, FCC `17-108` |
| **Baseline Only** | Appears in primary browsing with exact-hash metrics, partial-processing labels, and the next semantic command. | Climate / Oil & Gas / Methane, EPA `EPA-HQ-OAR-2021-0317` |
| **Ingestion Ready** | Appears as an action path or template that generates `configs/dockets.yaml` snippets and pipeline commands. It does not show zero campaigns as a failure state. | Analyze a docket, CFPB/SEC/FTC templates |
| **Hidden** | Excluded from primary navigation until a real docket is registered or useful ingestion action exists. Direct routes should point to the Analyze workflow. | Healthcare, Labor, unsupported future sectors |

Future coverage expands by registering a docket, running ingestion/parsing,
embedding, clustering, and exporting review data. Until those steps produce
evidence, the UI treats the topic as an ingestion template rather than a fake
dashboard.

### Backend processing_status values

Each docket entry in [`configs/dockets.yaml`](../configs/dockets.yaml) carries
a `processing_status`. The allowed values are enforced by
[`scripts/run_docket_pipeline.py`](../scripts/run_docket_pipeline.py)
(`ALLOWED_PROCESSING_STATUSES`):

| `processing_status` | UI label | Meaning |
| :--- | :--- | :--- |
| `configured_awaiting_run` | "Configured, awaiting run" | Registered in `configs/dockets.yaml` or via the `/analyze` workflow; pipeline has not run yet. |
| `queued` | "Queued" | Registered and scheduled for an upcoming run. |
| `partially_processed` | "Partially processed" | Some stages have completed; full dossier not yet available. |
| `baseline_only` | "Baseline only" | Exact-hash baseline is available; semantic clustering not yet promoted. |
| `analyzed` | "Analyzed" | Full semantic dossier available end-to-end. |

The MVP coverage tiers above are UI-facing summaries that map onto these
backend statuses; the UI's `CoverageStatus` enum is documented in
[`docs/ui-information-architecture.md`](ui-information-architecture.md).

---

## 3. How Future Topics & Dockets Are Ingested

Adding a new docket to the active analysis pipeline is fully automated via the Autopilot active discovery loop and multi-agent DAG sequence:

0. **Discovery & Classification**: The Autopilot crawler (`scripts/discover_dockets.py`) continuously sweeps source endpoints, classifications dockets into topics (`scripts/classify_dockets.py`), and calculates a multi-factor `priority_score` (representing volume, recency decay, and watchlist matching). High-priority or watched candidates are enqueued for runs. Developers retain manual registry overrides at `/analyze`.
1. **Registration**: The docket ID and agency target are registered under a specific **Topic** sector.
2. **Ingestion**: The `IngestionAgent` reads from the Regulations.gov v4 or ECFS public API, dumping raw comments into `bronze.raw_comments` via parallel Spark partitions.
3. **Parsing**: The `ParserAgent` extracts structural details and attachment text (e.g. PDFs, DOCX) to write to `silver.parsed_comments`.
4. **Embedding**: The `EmbeddingAgent` generates vectors using Serverless Databricks Foundation Model APIs, writing to `silver.comment_embeddings`.
5. **Clustering**: The `ClusteringAgent` runs high-scale cosine grouping, saving resulting campaign templates to `gold.comment_clusters`.
6. **Attribution & Migration (evidence layer)**: The `AttributionAgent` (offline seed registry) emits *candidate* campaign-origin rows to `gold.campaign_attributions`; the `MigrationAgent` emits phrase-level *language overlap* rows between clusters and final rule text into `gold.rule_migrations`. Both produce **evidence packets**, not accusations, and never claim causality — see [ADR-0015](decisions/0015-attribution-and-migration-agents.md) and [`docs/attribution-and-migration-methodology.md`](attribution-and-migration-methodology.md).
7. **Frontend Hydration**: The public Next.js UI automatically queries these Delta Tables through the Databricks SQL Warehouse, dynamically rendering the new dossiers. Absence of attribution/migration data renders as "Not yet analyzed" with a runnable command — never as a false negative.
