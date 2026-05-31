# Architecture

Astroturf is a replayable multi-agent system over a Delta medallion lakehouse.
Agents read and write durable tables rather than passing in-memory messages.
This keeps each stage independently replayable, inspectable, and recoverable.

## Agents

- IngestionAgent: multi-source -> bronze Delta. Sources: regulations.gov v4 and
  FCC ECFS public API (see ADR-0012).
- ParserAgent: bronze to silver (text normalization, detail enrichment, and
  deferred attachment extraction). Source-aware: ECFS rows skip the detail-API
  fetch and HTML stripping because ECFS `text_data` is already plain text.
- EmbeddingAgent: silver to vector embeddings. Supports mock, local
  sentence-transformers, and Databricks Foundation Model backends.
- ClusteringAgent: vectors or normalized text hashes to gold clusters. Supports
  exact-hash baselines, local cosine connected components, and Databricks Vector
  Search review paths.
- AttributionAgent: clusters to candidate campaign-origin evidence. MVP runs in
  `offline_seed` mode against a curated registry of known sources per docket.
  Outputs are evidence packets with confidence labels, not accusations
  (ADR-0015).
- MigrationAgent: clusters x final rule text to phrase-level language-overlap
  findings. MVP runs in `local_text` mode against a labelled local fixture.
  Outputs always carry an explicit caveat; the agent never claims causality
  (ADR-0015).

## Data Flow

regulations.gov v4 API + FCC ECFS public API
  -> `bronze.raw_comments` (Delta, unified schema, `source` discriminator)
  -> `silver.parsed_comments` (Delta, normalized text)
  -> `silver.comment_details` / `silver.comment_attachments` (optional enrichment)
  -> `silver.comment_embeddings` (Delta embeddings)
  -> `gold.comment_clusters`
  -> `gold.comment_cluster_memberships`
  -> `gold.campaign_attributions`
  -> `gold.rule_migrations`
  -> `demo.cluster_review_export`

## Discovery & Control Plane Data Flow

Autopilot crawler sweeps
  -> `<catalog>.discovery.docket_catalog`
  -> `<catalog>.discovery.watchlist`
  -> `<catalog>.discovery.analysis_requests`
  -> `<catalog>.discovery.autopilot_runs`

The hosted Next.js app stores its production control-plane state in PostgreSQL.
Local/demo mode can run with mock or fallback data and does not require
Databricks credentials.

## Bronze Schema Unification

Both public sources land in a single `bronze.raw_comments` table. The `source`
column (`"regulations_gov"` or `"ecfs"`) is required at the Pydantic layer and
Arrow-nullable on disk so ADR-0004's `ensure_schema()` can migrate older tables.
ECFS-specific discriminators (`ecfs_proceeding_id`, `ecfs_submission_type_id`,
`ecfs_express_comment`) are nullable. Per-source field mapping lives in ADR-0012;
per-source ingestion modules live under `agents/ingestion/sources/`.

## Orchestration

- Local dev: `scripts/run_docket_pipeline.py` coordinates multi-stage agent runs.
- Production: Databricks Workflows/Jobs run notebook entry points on Serverless
  compute.
- Autopilot: `scripts/run_autopilot.py` coordinates broad crawler sweeps,
  deterministic topic classification, priority scoring, and optional analysis
  requests.

## Evidence Posture

Attribution and migration outputs are caveated evidence packets, not accusations.
Confidence scores, source-method labels, representative text, and caveats are
part of the output contract so reviewers can inspect the basis for every claim.
