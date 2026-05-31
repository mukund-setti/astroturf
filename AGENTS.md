# Astroturf Agent Instructions

## Project Summary

Astroturf is a multi-agent regulatory intelligence platform for detecting coordinated public comment campaigns in federal rulemaking and producing caveated evidence packets for human review. It is built around replayable agents over a Delta medallion lakehouse and a Next.js reviewer UI.

## Architecture

Authoritative overview: `docs/architecture/architecture.md`.

Agents communicate through Delta tables:

- `IngestionAgent`: public source APIs -> `bronze.raw_comments`
- `ParserAgent`: bronze -> `silver.parsed_comments` plus optional detail/attachment side tables
- `EmbeddingAgent`: parsed comments -> `silver.comment_embeddings`
- `ClusteringAgent`: embeddings/text hashes -> `gold.comment_clusters` and `gold.comment_cluster_memberships`
- `AttributionAgent`: clusters -> `gold.campaign_attributions`
- `MigrationAgent`: clusters and final-rule text -> `gold.rule_migrations`

## Non-Negotiable Design Rules

1. Idempotency: every agent must be safe to rerun. Writes should use stable primary keys and merge/replacement semantics, not blind appends.
2. No silent failures: unrecoverable errors should raise; recoverable API errors should retry with bounded backoff and then raise.
3. Schemas live under `shared/schemas/`.
4. The orchestrator sequences agents and handles failures; business logic belongs inside agents.
5. Attribution and migration outputs are evidence packets with caveats, not accusations.
6. Keep secrets, private workspace identifiers, generated Delta tables, logs, and local artifacts out of commits.

## Codebase Conventions

- Python 3.11.
- Type hints on public functions.
- Ruff for linting and formatting.
- Tests live under `tests/`.
- Notebooks in `notebooks/` should be thin wrappers around importable modules.
- Production code should use module loggers rather than `print()`.

## Public Configuration

Use `.env.example` and `ui/.env.example` as templates. Real values must be supplied through local env files, Databricks secrets, or deployment-platform secrets and must not be committed.

Important knobs:

- `ASTROTURF_DATA_MODE=mock|live|auto`
- `ASTROTURF_DELTA_BACKEND=auto|spark|delta_rs`
- `ASTROTURF_EXECUTION_MODE=command|local_process|databricks_job`

## Current Public Status

- Local tests and UI build commands are expected to work without Databricks credentials when using mock/local modes.
- Databricks live execution requires user-provided workspace, SQL Warehouse, Jobs API, Unity Catalog, and optional Vector Search configuration.
- Generated runtime artifacts are intentionally ignored; small public sample artifacts under `artifacts/` are retained for review context.
