# Astroturf — Claude Code instructions

## What this project is
A multi-agent system that detects coordinated public comment campaigns in federal rulemaking and traces their language into final rules. Built on Databricks. The "agentic" parts are AttributionAgent (tool-using research), ParserAgent (LLM-based PDF extraction with judgment), and the Orchestrator (routing decisions). The rest are Spark transforms wearing an agent costume — keep that distinction honest.

## Architecture (authoritative: docs/architecture.md)
Six agents over a medallion lakehouse:
- IngestionAgent: multi-source (regulations.gov v4 + FCC ECFS public API) -> bronze.raw_comments. See ADR-0012.
- ParserAgent: bronze -> silver.parsed_comments (LLM for PDF/scanned attachments). Source-aware: ECFS rows skip detail-fetch + HTML stripping.
- EmbeddingAgent: silver -> silver.comment_embeddings (Databricks Foundation Model API: databricks-bge-large-en)
- ClusteringAgent: vectors -> gold.comment_clusters (MinHash/LSH candidate generation, cosine confirmation)
- AttributionAgent: clusters -> gold.campaign_attributions (tool-using LLM agent: web search + advocacy registry lookup)
- MigrationAgent: clusters x final rule text -> gold.rule_migrations (phrase-level similarity, section-level citations)

## API keys
Both regulations.gov and FCC ECFS are fronted by api.data.gov and accept the same key.
- Canonical env var: `DATA_GOV_API_KEY`.
- Deprecated fallback: `REGULATIONS_GOV_API_KEY`. Logs a one-time warning on use.
- Resolution lives in `shared/api_keys.py::resolve_data_gov_api_key`.
- ECFS docket conventions: pass the bare proceeding name (e.g. `17-108`, not `WC-17-108`). See docs/ecfs-setup.md.

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
- EmbeddingAgent complete for comment-level embeddings: writes `silver.comment_embeddings`, with a mock backend, a local `sentence-transformers` backend, and a Databricks Foundation Model backend implemented against the Databricks SDK (mock-tested only so far; no live Databricks request yet).
- Mock embedding smoke test passed on the CFPB sample: 11 substantive candidates embedded; rerun produced 11 cache hits and 0 writes.
- Debug UI exists for bronze / silver / details / attachments inspection.
- Latest test status: 76 unit tests passing, Ruff clean, Ruff format clean.

- **Phase 8 AttributionAgent + MigrationAgent MVPs complete (offline only)**: Implemented `AttributionAgent` (`offline_seed` mode, ADR-0015) and `MigrationAgent` (`local_text` mode, ADR-0015) as evidence-packet producers, not accusation generators. Schemas `gold.campaign_attributions` and `gold.rule_migrations` follow the Pydantic+pyarrow+pyspark pattern; `confidence_score` is hard-capped strictly below 1.0; `MigrationAgent` rows require non-empty `caveat_text`; `web_research` / `llm_assisted` / `federal_register_api` modes are wired but refuse to run until follow-up ADRs configure them. Curated FCC `17-108` seed registry and a clearly-labelled final-rule excerpt fixture live under `evals/fixtures/`. The campaign-detail UI gains "Likely Campaign Origin" and "Language Migration Check" sections that fall back to "Not yet analyzed" + CLI command when data is absent. Export pipeline (`scripts/export_to_demo_table.py`) gains nullable attribution/migration join columns; absence does not break the export. Methodology doc: `docs/attribution-and-migration-methodology.md`.
- **`processing_status` taxonomy reconciled**: `scripts/run_docket_pipeline.py` now exposes `ALLOWED_PROCESSING_STATUSES = {configured_awaiting_run, queued, partially_processed, baseline_only, analyzed}` as the single source of truth. The new tier `configured_awaiting_run` accurately describes dockets registered via `/analyze` or in `configs/dockets.yaml` that have not been run. Status-to-UI-label mapping documented in `docs/product-vision.md` and `docs/ui-information-architecture.md`; runbook references the validator. Phase 5 tests updated to match the new reality. `ui/app/analyze/page.tsx` YAML snippet now emits `processing_status: "configured_awaiting_run"` so generated config validates round-trip.
- **Interactive `/analyze` Ingestion and Orchestration Runner**: Fully wired the Next.js frontend with local server capabilities. An endpoint `/api/analyze/register` appends new docket configurations directly to `configs/dockets.yaml` (safely checking for existing registrations first), and spawns the unified pipeline runner `scripts/run_docket_pipeline.py` in the background with local execution settings and comment limits, streaming console output to `data/logs/pipeline-<id>.log` automatically. Users can register and trigger pipeline runs directly from the browser with zero manual CLI steps.

- **H1: Spark-native Delta writes on Databricks (ADR-0017, 2026-05-25)**: Eliminated the delta-rs `/Volumes/` FUSE bypass — the writer that did `copytree -> mutate -> rmtree -> copytree` on every MERGE, which was the source of the ~220 rows/min ECFS ingestion floor and the 15-empty-MERGEs-in-4-seconds pattern surfaced by `scripts/diagnose_delta_paths.py`. New `shared/delta_utils/backend.py` dispatcher routes each writer to either `delta_rs` (local Windows) or `spark` (Databricks notebook) based on `ASTROTURF_DELTA_BACKEND` ∈ `{auto, spark, delta_rs}` and a path heuristic (`/Volumes/...`, `/dbfs/...`, `dbfs:/...`). All 8 prior `local_tmp_delta_path` call sites across `bronze.py`, `silver.py`, `gold.py`, `attribution.py`, `migration.py`, `discovery.py` were converted; `shared/delta_utils/fuse_bypass.py` was deleted. Spark writers in `shared/delta_utils/spark_writers.py` write to the same FUSE paths the delta-rs branch wrote to (no data migration — the diagnosis confirmed all underlying Delta logs are contiguous and clean), set `spark.databricks.delta.schema.autoMerge.enabled=true` per merge for ADR-0004-compatible additive evolution, short-circuit empty-source MERGEs, and handle brand-new-path init via overwrite. The medallion-layer Unity Catalog entries are **views** over `delta.``<path>``` (not managed tables), so the view layer keeps resolving the same paths transparently — no view drops, no UC reshuffle. The notebook's `_register_delta_view` learned a new `_register_delta_view_if_exists` sibling, and `silver.comment_details` / `silver.comment_attachments` are now conditionally registered after the parser stage so H2 lands cleanly. New diagnostic tool `scripts/diagnose_delta_paths.py` (`--catalog`, `--include-history-versions`) classifies every UC entry as view-vs-table and dumps history for every underlying path-based Delta table; this is what produced the H1 step-1 findings and is reusable by future operators. Tests: 14 new dispatcher + brand-new-path tests in `tests/unit/test_delta_backend.py` and `tests/unit/test_delta_writers_brand_new_path.py` (delta-rs branch) plus a 5-test opt-in Spark suite at `tests/integration/test_spark_writers.py` gated by `ASTROTURF_RUN_SPARK_TESTS=1` (Windows hits the ADR-0002 HADOOP_HOME wall; runs on WSL/Linux/macOS or on Databricks). UI comments referencing `fuse_bypass.py` (in `ui/components/analysis-progress.tsx`, `ui/lib/runtime-estimate.ts`, `ui/lib/databricks.ts`) were updated to point at ADR-0017. **Pending H1 acceptance gate**: re-run FCC 17-108 5K ECFS slice on Databricks and confirm under-8-min wall clock (was ~22 min under the FUSE bypass).

- **Honest pipeline observability + validated discovery catalog (2026-05-25)**:
  - **No more silent SUCCESS-with-zero-rows**: `notebooks/databricks/web_analysis_job.py` gained per-docket `_count_docket_rows(...)` guards right after ingestion / parsing / export — any zero-row stage raises `RuntimeError` instead of letting the job report SUCCESS. The fix was pushed to the workspace (sha256-verified). The earlier silent-success failure modes for FTC dry-run and 23-562 synthetic-empty are now hard failures.
  - **Hard-pinned `dry_run=false`** in `ui/lib/databricks-jobs.ts::submitDocketJob` so a stale notebook-task `base_parameters: {dry_run: "true"}` left over from a smoke test can't override real `/analyze` submissions.
  - **Honest ETA estimator**: `ui/lib/runtime-estimate.ts` models per-stage runtime against observed regulations.gov + ECFS pipeline rates (parsing is ~17 rows/min on regs.gov due to api.data.gov's 1000 req/hr cap; ECFS ingestion ~3000 rows/min). Surfaced live as users tweak source/scale on the `/analyze` form, and as a `window.confirm()` quoted runtime + warnings on the `/discoveries` one-click flow. Submitted ETA is also written into the analysis-request notes for post-hoc comparison.
  - **Auto-polling analysis detail page**: new `ui/app/api/analysis/[request_id]/progress/route.ts` returns a pollable snapshot (Databricks state + live per-stage Delta row counts, with `-1` sentinels treated as "syncing…" to tolerate the FUSE bypass's transient mid-write reads). New `ui/components/analysis-progress.tsx` polls every 10s while in flight, renders a 5-stage progress bar with live counts, and stops polling at terminal status. The old `Sync Databricks Run` button is demoted to a manual fallback only.
  - **Validated discoveries catalog**: `ui/db/migrations/003_add_docket_validation.sql` adds `validation_status` / `validated_comment_count` / `validation_source` / `validated_at`. `ui/db/seeds/003_seed_validated_dockets.sql` reseeds the catalog with only 4 source-API-confirmed dockets (CFPB-2016-0025, FCC 17-108, FTC-2023-0007, EPA-HQ-OAR-2021-0317) and deletes the synthetic fallback seeds (FTC-2024-0012, FDA-2023-N-1200, 23-562, 14-28-as-robocall) that previously caused zero-row runs. `scripts/validate_discoveries.py` hits regulations.gov v4 and FCC ECFS to update validation columns and can be re-run anytime. `scripts/discover_dockets.py::generate_fallback_dockets` updated to match. UI surfaces a green ✓ Validated / red "Source: no data" / amber "Validate err" badge on every `/discoveries` card.
  - **No more hard scale caps**: removed the `ASTROTURF_MAX_INGEST_PER_RUN` cap and the 1000-row clamp from the `/discoveries` one-click flow. Users see the ETA up front and opt in eyes-open.
  - **Background runs in flight as of session end**: FCC 17-108 ECFS @ 5K rows (run_id `737755812472908`) and CFPB-2016-0025 regs.gov @ 1K rows (run_id `724798107790115`) submitted; both queued behind an unrelated user run, will start serially and produce the first real demo data in the catalog when they finish.

- **H1 acceptance gate — PARTIAL pass on first try, FULL pass after H1b patch (2026-05-30)**: Both 2026-05-25 background runs were canceled before they ran (queue ahead of them held for 87 minutes). Resubmitted FCC 17-108 5K ECFS as `h1-acceptance-fcc-17108-5k` (run_id `1033596660197644`) on the deployed ADR-0017 stack (workspace files SHA-verified byte-equal to local before submission). Bronze ingestion completed in ~3.5 min wall-clock — the ADR-0017 spark-native writer fix is confirmed working, dropping ECFS bronze writes from the FUSE-bypass-era ~22-min floor to under 4 min. But the run stalled past bronze for 44+ minutes with zero silver activity, and was canceled. Root cause: ADR-0017's dispatcher converted `merge_*` writes through `shared/delta_utils/backend.py`, but `agents/parser/agent.py` still read bronze via `deltalake.DeltaTable(bronze_path).to_pyarrow_table()` — pure delta-rs against the `/Volumes/...` FUSE path, with no Spark fallback. The reader loaded the entire bronze table (36,697 rows across all dockets) into Arrow before filtering by `docket_id`. EmbeddingAgent / ClusteringAgent / AttributionAgent already routed through `shared/delta_utils/silver.load_delta_as_pyarrow`, which dispatches to Spark for `/Volumes/` paths — only the parser was the outlier.
- **H1b — ParserAgent Spark-native bronze + details read (2026-05-30)**: Patched `agents/parser/agent.py` to dispatch the bronze and details Delta reads through `shared.delta_utils.backend.should_use_spark`. On Databricks the parser now does `spark.read.format("delta").load(bronze_path).filter(F.col("docket_id") == inputs.docket_id)` then `Row.asDict(recursive=True)` to keep the rest of the loop (which is dict-shaped) unchanged. Local path stays on delta-rs so all 13 parser unit tests still pass byte-for-byte. Pushed to the workspace and SHA-verified. Resubmitted FCC 17-108 ECFS at 500 rows as `h1b-fcc-17108-500` (run_id `533768612765603`): **succeeded end-to-end in 6 min 55 sec wall-clock** — under the 8-min H1 acceptance gate. Final lakehouse state: bronze 5,000 / parsed 5,000 / embeddings 500 (max_rows cap) / 6 clusters / 361 cluster_memberships / 361 exported rows. 72% of the embedded 500 comments landed in coordinated clusters — a real, defensible demo finding from the live pipeline.
- **Demo data in workspace as of this session**: CFPB-2016-0025 end-to-end (bronze 250 → parsed 21 → embeddings 20 → 1 cluster → 2 memberships, prior session); FCC 17-108 bronze 5,000 (from canceled H1 attempt — clean Delta log, no rollback needed); FTC-2023-0007 bronze 20,697; EPA-HQ-OAR-2021-0317 bronze 500. Landing page falls back to the validated FCC 17-108 reference dataset (1,002-comment template cluster, 63× detection lift vs naive exact hashing) when live cluster counts are zero. Stale "submitted" `analysis_requests` rows for the 87-min-queued canceled runs were marked `canceled` in Postgres.
- Latest test status: **203 backend tests passing** (5 skipped — opt-in Spark integration suite), Ruff clean, Ruff format clean. UI: `npx tsc --noEmit` clean, `npx eslint` clean, `npm run build` passes (pre-this-session). Landing-page polish edits this session add 6th step ("Attribute and trace") to `how-it-works.tsx`, expand `why-databricks-section.tsx` to 6 cards (split out Foundation Model API + Workflows/Jobs + SQL Connector as their own callouts), and update `architecture-diagram.tsx` SOURCE/parsing labels to call out dual sources + source-aware parsing. Tests not re-run after these edits because they only touch presentational components.

### Next priorities
1. **H1b acceptance — DONE 2026-05-30** (see status block above). Run was `h1b-fcc-17108-500`. Now the demo lakehouse has live end-to-end FCC 17-108 data: 6 clusters / 361 memberships / 361 export rows backing the landing page.
2. **H2 ParserAgent mid-loop checkpointing + bounded concurrent fetches** (next on the production-blocker queue). Mid-loop MERGE every N=200 rows or 5 minutes; `ThreadPoolExecutor(max_workers=5)` shared across regs.gov detail fetches; token-bucket rate limiter at 1000/hour (the api.data.gov cap); `--force-reparse` CLI flag wired to existing `ParserInput.force_enrich`. Public dataclasses unchanged.
3. **S5 recalibrate `ui/lib/runtime-estimate.ts`** against post-H1 numbers. Add `pipeline_observations` Postgres table (migration `004_add_pipeline_observations.sql`), have the notebook write per-stage timings directly via `psycopg2` using `DATABASE_URL`, and switch `estimateRuntime` to a rolling p50 with the existing hard-coded constants as fallback.
4. **H4 concurrency cap + Asset Bundles** (job spec under source control), then **H3 shared-password middleware**, then **H5 docket catalog expansion**.
5. **ADR-0017 Future work item**: collapse the 15-empty-MERGEs-per-page pattern in `agents/ingestion/agent.py` by batching ~20 pages before calling `merge_comments`. Post-H1 this is cheap waste (no FUSE round-trip) instead of crippling, but still worth doing.
6. Run AttributionAgent + MigrationAgent against the live FCC `17-108` clustered slice end-to-end once H1's acceptance run produces fresh data.
7. ADR + implementation for `web_research` (AttributionAgent) and `federal_register_api` (MigrationAgent) modes — gated behind tooling configuration and explicit user approval.
8. Later: attachment text extraction (ParserAgent v2B phases 2-4) and expanded production Vector Search evaluation/recall tuning.
