# Astroturf — Codex instructions

## What this project is
A multi-agent system that detects coordinated public comment campaigns in federal rulemaking and traces their language into final rules. Built on Databricks. The "agentic" parts are AttributionAgent (tool-using research), ParserAgent (LLM-based PDF extraction with judgment), and the Orchestrator (routing decisions). The rest are Spark transforms wearing an agent costume — keep that distinction honest.

## Architecture (authoritative: docs/architecture.md)
Six agents over a medallion lakehouse:
- IngestionAgent: regulations.gov v4 API -> bronze.raw_comments
- ParserAgent: bronze -> silver.parsed_comments (LLM for PDF/scanned attachments)
- EmbeddingAgent: silver -> silver.comment_embeddings (Databricks Foundation Model API: databricks-bge-large-en)
- ClusteringAgent: vectors -> gold.comment_clusters (MinHash/LSH candidate generation, cosine confirmation)
- AttributionAgent: clusters -> gold.campaign_attributions (tool-using LLM agent: web search + advocacy registry lookup)
- MigrationAgent: clusters x final rule text -> gold.rule_migrations (phrase-level similarity, section-level citations)

Agents communicate via Delta tables, not in-memory message passing. Each agent is idempotent on its primary key and independently replayable.

## Non-negotiable design rules
1. Idempotency: every agent must be safe to re-run. Writes go through Delta MERGE on a stable primary key, never blind appends.
2. No silent failures: agents raise on unrecoverable errors. Recoverable errors (rate limits, transient HTTP) get exponential backoff via tenacity, then raise.
3. Schemas live in shared/schemas/ as Pydantic models AND PySpark StructTypes. Source of truth is the Pydantic model; the StructType is derived from it.
4. All LLM calls go through shared/llm_client.py so we can swap providers and add MLflow tracing in one place.
5. Every agent run emits an MLflow run with inputs (docket_id, config), outputs (row counts, quality metrics), and timing.
6. The Orchestrator never embeds business logic. It sequences agents and handles failures. If you're tempted to put logic in the orchestrator, it belongs in an agent.

## Architecture decisions
Captured in docs/decisions/NNNN-kebab-title.md, numbered sequentially. Each ADR covers one decision with Context / Decision / Consequences / Alternatives. Write a new one whenever we make a non-obvious or non-trivially-reversible call.

## Codebase conventions
- Python 3.11, type hints required on all public functions
- Ruff for linting/formatting (config in pyproject.toml)
- Tests live in tests/ mirroring the source tree
- Notebooks in notebooks/ are thin wrappers that import from agents/ — never define logic in a notebook
- No print() in production code; use the module logger

## Things to ask me about before doing
- Adding a new dependency (tell me what and why)
- Changing an agent's public contract (Input/Output dataclasses)
- Creating a new Delta table or schema
- Touching Delta table schemas (adding/removing/renaming fields, or changing types) on existing tables. See ADR-0004.
- Any change to the medallion table layout in docs/architecture.md

## Things to just do
- Implement methods marked `raise NotImplementedError`
- Write tests for code you're writing
- Refactor within an agent module
- Improve docstrings and type hints
- Add logging where it would help debugging

## Session discipline
- When asked for a plan first, stop after the plan and wait for approval. Do not start implementing.
- Do not implement, run tests, stage files, or commit after saying you are waiting for approval. "Waiting for approval" means waiting.
- At the end of every substantial session, update the Current status section below if the project state changed. Treat it as the single source of truth for where the project is.

## Current status
- IngestionAgent complete and validated locally against delta-rs / Delta tables.
- CFPB-2016-0025 ingested into bronze: 211,885 unique comments, 0 duplicate `comment_id`s.
- ParserAgent v1 complete: deterministic title / body / missing parsing into `silver.parsed_comments`.
- ParserAgent v2A complete: fetches per-comment regulations.gov detail JSON, enriches parsed comments, writes `silver.comment_details` and `silver.comment_attachments`, gated by a `max_detail_fetches` safety cap.
- AttachmentDownloaderAgent complete for v2B phase 1: downloads attachment binaries, computes checksums, updates download metadata. PDF / DOCX text extraction, reconciliation back into `parsed_comments`, OCR, and LLM extraction are still deferred.
- EmbeddingAgent complete for comment-level embeddings: writes `silver.comment_embeddings`, with a mock backend, a local `sentence-transformers` backend, and a Databricks Foundation Model backend implemented against the Databricks SDK and live-validated on Databricks Serverless.
- `docs/system-map.md` and `docs/demo-story.md` drafted to make the architecture, demo scope, and project narrative legible end-to-end.
- Local real-embedding smoke test passed on the CFPB sample: 11 substantive candidates re-embedded with `BAAI/bge-large-en-v1.5` via the local `sentence-transformers` backend; `silver.comment_embeddings` now has 11 real local vectors and no remaining mock vectors for that sample.
- ClusteringAgent v1 complete for local single-docket / single-model runs: pairwise cosine over non-mock embeddings by default, connected components above threshold, scoped replacement into `gold.comment_clusters` and `gold.comment_cluster_memberships`, MLflow metrics, and ADR-0006 covering cluster identity / gold layout.
- CFPB real-embedding clustering smoke test passed at threshold 0.92: 11 candidates, 55 pairs, 1 edge, 1 cluster, 2 memberships.
- Exact normalized-text-hash baseline complete: writes literal duplicate clusters into existing gold tables with `clustering_version="v1_exact_hash"`, `embedding_model="normalized_text_hash"`, and `embedding_backend="exact_hash"`.
- EPA-HQ-OAR-2021-0317 exact-hash baseline smoke test passed: 396 candidate `detail_comment_text` rows, 7 duplicate-hash clusters, 16 memberships, largest cluster size 4.
- Debug UI expanded to include exact-hash baseline, cluster campaign style classification, and comprehensive cluster evidence inspection.
- Evidence export CLI added: `scripts/export_cluster_evidence.py` writes bounded Markdown cluster-review reports from existing gold/silver Delta tables; EPA-HQ-OAR-2021-0317 report generated under `data/exports/`.
- Databricks demo workflow scaffolding added: `notebooks/databricks/workflow_tasks.py` plus `docs/databricks-workflow.md` cover `load_sample_tables -> embed -> cluster -> export_dashboard_data` for the CFPB/EPA demo.
- Databricks Vector Search v1 reviewer-only setup added: `notebooks/databricks/vector_search_setup.py` plus `docs/databricks-vector-search.md` create the BGE-large filtered source and manual-sync index runbook, without wiring Vector Search into `ClusteringAgent`.
- **Live Databricks Workflow Execution SUCCESS**: Run ID `864884109927694` successfully executed the full four-task multi-task pipeline (`load_sample_tables` -> `embed` -> `cluster` -> `export_dashboard_data`) for the EPA docket `EPA-HQ-OAR-2021-0317` on Serverless compute. Final Unity Catalog row counts verified: bronze/silver comments (1,000), BGE embeddings (396), gold clusters (13), gold memberships (162), review export (162).
- **Live Databricks Vector Search Setup SUCCESS**: Run ID `162858305180109` created the BGE-filtered table and synced it to `workspace.silver.comment_embeddings_bge_large_index` on `astroturf-vs-endpoint`. Directly verified index state as `ONLINE_NO_PENDING_UPDATE` with exactly 396 rows synced in ~61 seconds, and live nearest-neighbor queries returning high-fidelity matches.
- Full cell-by-cell execution outputs and HTML run views saved locally in `data/exports/` for verification.
- **Phase 1 FCC ECFS Ingestion & Bronze Schema Unification SUCCESS**: Unified bronze comments schema across regulations.gov and FCC ECFS data sources. Backfilled legacy local Delta table and Databricks schemas successfully. Ingested 5K comments from FCC docket `17-108`, parsed, and ran exact-hash duplicate clustering. Verified using direct diagnostic query against the ECFS API that Broadband for America (BFA) campaign comments are successfully present under 17-108, validating the ingestion client and parsing integration end-to-end.
- **Phase 2 FCC ECFS 100K+ Scale Benchmark SUCCESS**: Completed a reproducible temporal-stratified ECFS scale benchmark runner. Evaluated exact duplicate hashing vs. capped semantic connected-components clustering under Net Neutrality proceeding 17-108. Successfully modeled the local $O(N^2)$ memory wall (~37.25 GB matrix for 100K comments) as a theoretical failure demonstration. Generated detailed Comparative Benchmark Reports and logged metrics directly to MLflow.
- Latest test status: 140 tests passing, Ruff clean, Ruff format clean. Verified locally with `.uv-test-venv\Scripts\python.exe`.
- **Phase 4 UI Multi-Topic Information Architecture Redesign SUCCESS**: Evolved the public Next.js UI from a single-docket Net Neutrality showcase into a comprehensive multi-topic, multi-agency regulatory intelligence platform. Added routes for `/topics`, `/topics/[id]`, `/agencies`, `/agencies/[id]`, and `/dockets/[id]`, and wired campaigns back to parents via hierarchical breadcrumbs. Implemented a global multi-entity autocomplete search in the masthead. Deployed honest "baseline-only / partially processed" labeling for the EPA Methane docket. All Next.js TypeScript build optimizations and the 140 backend pytests completed with 100% passes.
- **Phase 5 Databricks production path hardening complete and Phase 6 live validation SUCCESS**: A 500-comment controlled FCC `17-108` slice was uploaded to `workspace` UC volumes, loaded into `workspace.bronze.raw_comments` / `workspace.silver.parsed_comments`, embedded live with `databricks-bge-large-en`, synced into `workspace.silver.comment_embeddings_bge_large_index` on `astroturf-vs-endpoint`, clustered with `clustering_mode="vector_search"`, and exported to `workspace.demo.cluster_review_export`. Verified row counts: raw/parsed (500), BGE embeddings (500), Vector Search source (500), gold clusters (1), gold memberships (500), review export (500). Key run IDs: load `916653215561127`, embed `546125942192140`, cluster `1028362756517371`, export `156035613634033`. One workspace-code drift issue was found and corrected by syncing local Phase 5/ECFS modules into the Databricks workspace repo before validation.
- **Phase 7 Databricks validation documentation and UI data-mode switch complete**: Added live validation, production setup, and end-to-end runbook docs documenting the Serverless notebook/job production path, run IDs, row counts, readiness checks, and Windows local `/Volumes/...` limitation. Next.js now supports `ASTROTURF_DATA_MODE=mock|live|auto`; FCC `17-108` is no longer hardcoded to offline artifacts, fallback mode remains available, and the UI displays a visible data-source label plus a subtle reviewer diagnostics popover showing mode, resolved SQL/fallback source, docket, catalog/table, row count, and last query/error status. UI production build passes in live/auto environment and forced mock mode. After Turbopack dev crashed natively on Windows in mock mode, `npm run dev` was switched to `next dev --webpack`, `npm run dev:turbo` was retained for explicit Turbopack testing, and a mock-mode webpack dev smoke test returned HTTP 200 for `/`.
- **Phase 8 MVP product hardening complete**: Removed placeholder-feeling primary UI surfaces. Topic/agency browsing now shows only FCC analyzed coverage, EPA baseline-only coverage, and an actionable `/analyze` docket-ingestion workflow. Future topics and supported-source agencies route to config generation instead of empty dashboards; search now returns Analyze CTAs for unsupported or unknown queries.
- **Phase 8 influence-tracing AttributionAgent + MigrationAgent MVPs complete (offline only)**: Implemented `AttributionAgent` (`offline_seed` mode, ADR-0015) and `MigrationAgent` (`local_text` mode, ADR-0015) as evidence-packet producers, not accusation generators. Schemas `gold.campaign_attributions` and `gold.rule_migrations` follow the Pydantic+pyarrow+pyspark pattern; `confidence_score` is hard-capped strictly below 1.0; `MigrationAgent` rows require non-empty `caveat_text`; `web_research` / `llm_assisted` / `federal_register_api` modes refuse to run until follow-up ADRs configure them. Curated FCC `17-108` seed registry and a clearly-labelled final-rule excerpt fixture live under `evals/fixtures/`. The campaign-detail UI gains "Likely Campaign Origin" and "Language Migration Check" sections that fall back to "Not yet analyzed" + CLI command when data is absent. Export pipeline gains nullable attribution/migration columns; absence does not break the export. Methodology doc: `docs/attribution-and-migration-methodology.md`.
- **`processing_status` taxonomy reconciled**: `scripts/run_docket_pipeline.py` exposes `ALLOWED_PROCESSING_STATUSES = {configured_awaiting_run, queued, partially_processed, baseline_only, analyzed}` as the single source of truth. The new `configured_awaiting_run` tier accurately describes dockets registered via `/analyze` or in `configs/dockets.yaml` that have not been run. Status-to-UI-label mapping is documented in `docs/product-vision.md` and `docs/ui-information-architecture.md`; the `/analyze` page's YAML snippet now emits the canonical status so generated config validates round-trip.
- **Interactive `/analyze` Ingestion and Orchestration Runner**: Fully wired the Next.js frontend with local server capabilities. An endpoint `/api/analyze/register` appends new docket configurations directly to `configs/dockets.yaml` (safely checking for existing registrations first), and spawns the unified pipeline runner `scripts/run_docket_pipeline.py` in the background with local execution settings and comment limits, streaming console output to `data/logs/pipeline-<id>.log` automatically. Users can register and trigger pipeline runs directly from the browser with zero manual CLI steps.
- **Hosted Databricks web analysis entrypoint added**: `notebooks/databricks/web_analysis_job.py` now handles production `/analyze` requests without relying on pre-uploaded `bronze.raw_imports` Parquet samples. The UI submits request parameters plus `DATABRICKS_CATALOG`, `DATABRICKS_DATA_ROOT`, `DATABRICKS_REPO_PATH`, and optional Vector Search config to the Databricks Jobs API; the notebook creates required UC schemas/volume, ingests from the public source API, parses, embeds with `databricks-bge-large-en`, clusters, and exports to `demo.cluster_review_export`. The old sample-loader workflow remains for demos and now fails clearly if invoked with a hosted `request_id`.
- Latest test status: **173 backend tests passing**, Ruff clean, Ruff format clean. Verified locally with `.uv-test-venv\Scripts\python.exe`. UI lint has 0 errors with existing warnings; UI production build passes via `npm.cmd run build` after allowing Google Fonts network fetch.

### Next priorities
1. Run AttributionAgent + MigrationAgent against the live FCC `17-108` clustered slice end-to-end and capture a reviewer dossier.
2. ADR + implementation for `web_research` (AttributionAgent) and `federal_register_api` (MigrationAgent) modes — gated behind tooling configuration and explicit user approval.
3. Later: attachment text extraction (ParserAgent v2B phases 2-4) and expanded production Vector Search evaluation/recall tuning.
