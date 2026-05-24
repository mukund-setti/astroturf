# ADR-0016: Autopilot monitoring and docket discovery strategy

- Status: Accepted
- Date: 2026-05-24

## Context

Federal rulemaking is large, decentralized, and dynamic. Currently, Astroturf requires manual registration and pipeline execution (`configs/dockets.yaml` and `scripts/run_docket_pipeline.py`) to analyze coordinated public comments. This docket-centric, developer-driven approach represents a high-friction bottleneck that prevents non-technical reviewers from exploring public comments efficiently. 

To transition from a "submit a docket and run a job" tool into a proactive regulatory intelligence platform, we require an Autopilot monitoring framework that:
1. Proactively discovers new rulemakings from Regulations.gov and FCC ECFS.
2. Deterministally classifies discovered dockets into policy domains (topics) and extracts relevant tags.
3. Automatically computes priority scores using multi-factored indicators (volume, recency, user interest).
4. Interfaces cleanly with Databricks Workflows as the compute engine, while supporting a transparent local development fallback.

## Decision

We will implement a unified three-tier discovery and monitoring subsystem comprising python pipeline tasks, Delta Lake schemas, and Next.js control plane interfaces.

### 1. Three-Tier Architectural Support

We define three execution profiles to satisfy local developers, live demo environments, and production schedules:

- **Local Dev Fallback Mode**: Autopilot scripts read/write local filesystem databases (`data/discovery/docket_catalog.json` and `ui/.data/watchlist.json`). API queries gracefully fall back to a deterministic seed directory of highly realistic dockets if credentials or endpoints are unavailable, avoiding failure states.
- **Reviewer / Demo Mode**: Next.js UI queries precomputed fallback JSON files when Databricks SQL is unreachable. Interactive watchlist additions write to local JSON, providing a zero-setup fully interactive mock state for reviewers.
- **Production Databricks Mode**: Scheduled Databricks Workflows run Python scripts directly on Serverless compute. Discovery outputs write directly to Unity Catalog Delta tables (`workspace.discovery.*`) as the lakehouse source of truth. Next.js queries these tables live via Databricks SQL Warehouse.

### 2. Medallion Discovery Schemas

All discovered, monitored, and scheduled states are modeled in `shared/schemas/` as Pydantic models (with PySpark StructTypes derived from them) matching our unified lakehouse architecture:

- `workspace.discovery.docket_catalog`: Schema for discovered/monitored rule dockets.
- `workspace.discovery.watchlist`: Schema for active user-configured monitoring items.
- `workspace.discovery.analysis_requests`: Schema for enqueued and completed analysis pipeline runs.
- `workspace.discovery.autopilot_runs`: Schema for tracking Autopilot orchestration runs, timing, and discovered record counts.

Primary keys (e.g. `docket_id`, `watch_id`) are stable, unique, and enforced via Delta MERGE operations.

### 3. Priority Scoring Formula

Monitored dockets are ranked in the catalog using a deterministic, multi-factor `priority_score` (capped at `100.0`):

$$\text{Priority Score} = \min\left(100.0, \, S_{\text{scale}} + S_{\text{recency}} + S_{\text{watchlist}} + S_{\text{agency}}\right)$$

Where:
- **Estimated Scale ($S_{\text{scale}}$)**: $25 \times \min\left(1.0, \, \frac{\text{comment\_count\_estimate}}{50000}\right)$ (rewards high-volume dockets).
- **Recency ($S_{\text{recency}}$)**: $25 \times \text{decay\_factor}(t)$ where decay is exponential based on days since `last_comment_date` (rewards active proceedings).
- **Watchlist Interest ($S_{\text{watchlist}}$)**: $30 \times \min\left(1.0, \, \frac{\text{user\_requested\_count}}{10}\right) + 15$ if matching active watchlist keywords or agencies (rewards user-driven interest).
- **Agency Priority ($S_{\text{agency}}$)**: $5$ bonus if rulemaking belongs to core monitored agencies (e.g. FCC, EPA).

### 4. Topic Classification Strategy

A production-shaped Python keyword classifier (`scripts/classify_dockets.py`) deterministically maps discovered dockets to our core taxonomy (`telecom`, `oil_and_gas`, `finance`, `ai_regulation`, `privacy`, `healthcare`, `labor`). It extracts semantic tags and computes priority scores. This script is fully decoupled, allowing it to be easily swapped for a Databricks Foundation Model (e.g., Llama-3-70B) embedding classifier in the future without breaking the catalog tables.

### 5. Databricks Jobs Orchestration

Production Autopilot runs as a daily Databricks Workflow:
1. **Discovery Task**: Runs `scripts/discover_dockets.py` to search Regulations.gov and ECFS API.
2. **Classification Task**: Runs `scripts/classify_dockets.py` to tag and prioritize candidates.
3. **Autopilot Orchestrator**: Runs `scripts/run_autopilot.py` to select top-priority dockets, enqueuing them to `workspace.discovery.analysis_requests` and triggering the primary pipeline workflow via the Databricks Jobs API.

## Consequences

### Positive
- **No Ingestion Dead Ends**: Users search broad topics, keywords, or agencies. If no precomputed analysis exists, the UI surfaces monitored dockets and allows adding items to a global watchlist or requesting an automated run.
- **Idempotency**: All writes leverage Delta MERGE on stable keys, preventing duplicate records.
- **Operational Scalability**: Autopilot transitions from local testing to daily production scheduling without code modifications, relying on `--mode` switches.

### Negative
- **Local State Drift**: Local dev mode uses JSON while production uses Delta Lake; we must maintain schema-matching consistency across local and live environments.
- **Job Cap Limits**: Automated jobs must be gated by safety thresholds to prevent runaway API rate limits or excessive Serverless compute charges.
