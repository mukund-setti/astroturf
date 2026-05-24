# Architecture

## Agents
- IngestionAgent: multi-source -> bronze Delta. Sources: regulations.gov v4 and
  FCC ECFS public API (see ADR-0012).
- ParserAgent: bronze to silver (text normalization, PDF extraction).
  Source-aware: ECFS rows skip the detail-API fetch and HTML stripping because
  ECFS `text_data` is already plain text.
- EmbeddingAgent: silver to vector index.
- ClusteringAgent: vectors to gold clusters (MinHash + cosine).
- AttributionAgent: clusters to candidate campaign origin. MVP runs in
  `offline_seed` mode against a curated registry of known sources per docket.
  Outputs are evidence packets with confidence labels, not accusations
  (ADR-0015).
- MigrationAgent: clusters x final rule text to phrase-level language
  overlap findings. MVP runs in `local_text` mode against a labelled local
  fixture. Outputs always carry an explicit caveat; the agent never claims
  causality (ADR-0015).

## Data flow
regulations.gov v4 API + FCC ECFS public API
  -> bronze.raw_comments (Delta, unified schema, `source` discriminator column)
  -> silver.parsed_comments (Delta, with normalized text)
  -> silver.comment_embeddings (Delta + Vector Search index)
  -> gold.comment_clusters (Delta, with template + size + confidence)
  -> gold.campaign_attributions (Delta, evidence packets with candidate
     entity, matched phrase, confidence label, manual-review status —
     ADR-0015)
  -> gold.rule_migrations (Delta, phrase-overlap findings with mandatory
     caveat_text and claim_scope; never claims causality — ADR-0015)

## Discovery & Control Plane Data Flow
Autopilot crawler sweeps
  -> workspace.discovery.docket_catalog (Delta, discovered rulemaking catalog)
  -> workspace.discovery.watchlist (Delta, active keyword/agency monitoring)
  -> workspace.discovery.analysis_requests (Delta, enqueued/historical job run history)
  -> workspace.discovery.autopilot_runs (Delta, orchestration run statistics and health logs)

## Bronze schema unification
Both sources land in a single `bronze.raw_comments` table. The `source` column
(`"regulations_gov"` or `"ecfs"`) is required at the Pydantic layer and
Arrow-nullable on disk so ADR-0004's `ensure_schema()` can migrate older
tables. ECFS-specific discriminators (`ecfs_proceeding_id`,
`ecfs_submission_type_id`, `ecfs_express_comment`) are nullable. Per-source
field mapping lives in ADR-0012; per-source ingestion modules live under
`agents/ingestion/sources/`.

## Orchestration
- Local dev: `scripts/run_docket_pipeline.py` coordinates multi-stage agent runs with checkpointing.
- Production: Databricks Workflows (infra/workflows/main.yml) with task dependencies over Serverless compute.
- Autopilot Scheduler: `scripts/run_autopilot.py` coordinates broad crawler sweeps, deterministic topic classification, priority-scoring decays, and invokes analysis requests. Scheduled to run daily on Databricks Serverless compute.
