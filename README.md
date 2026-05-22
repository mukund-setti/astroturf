# Astroturf

Detecting coordinated public comment campaigns in federal rulemaking and tracing their language into final rules.

Built on Databricks. Multi-agent architecture over a medallion lakehouse.

## Quickstart
1. Copy `.env.example` to `.env` and fill in credentials
2. `uv sync`
3. `uv run python -m orchestrator.local --docket EPA-HQ-OAR-2023-0072`

## Architecture
See `docs/architecture.md`.
