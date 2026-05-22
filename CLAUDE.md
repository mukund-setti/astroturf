# Astroturf — Claude Code instructions

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
- Any change to the medallion table layout in docs/architecture.md

## Things to just do
- Implement methods marked `raise NotImplementedError`
- Write tests for code you're writing
- Refactor within an agent module
- Improve docstrings and type hints
- Add logging where it would help debugging

## Current status
IngestionAgent implemented end-to-end against regulations.gov v4 (date-window cursoring past the 5000-record cap; tenacity retries; MLflow metrics; idempotent MERGE). Local bronze writes via delta-rs — see docs/decisions/0002-deltalake-for-local-bronze.md. Next task: ParserAgent (bronze -> silver, with LLM extraction for PDF/scanned attachments).
