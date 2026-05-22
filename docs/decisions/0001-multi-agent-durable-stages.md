# ADR-0001: Use multi-agent stages communicating through Delta tables, not in-memory agent handoffs

- Status: Accepted
- Date: 2026-05-21

## Context

The system consists of six agentic/analytical stages over a medallion lakehouse. A naive or traditional agent architecture might pass large payloads (raw data, parsed text, embeddings, clusters, attributions) in memory between agents or via direct API calls/in-memory queues.

Passing large payloads in memory or as transient message states has major drawbacks:
1. **Lack of inspectability**: If a downstream agent fails, we cannot easily inspect the inputs/outputs of the upstream agent without logging/tracing overhead.
2. **No replayability/resilience**: If a late stage fails, we have to re-run the entire pipeline from scratch, incurring high LLM/API costs.
3. **Tight coupling**: Stages cannot be developed, run, or unit-tested in isolation without mocking the entire chain.
4. **Scale limits**: Large volumes of data (thousands of comments, heavy embeddings) can exceed memory limits or lead to complex buffer management.

## Decision

Agents communicate through durable Delta tables across bronze/silver/gold layers instead of passing large payloads in memory. This makes every stage replayable, inspectable, and independently testable. The orchestrator sequences stages but does not own business logic or transient state.

Delta tables serve both as the inter-agent communication boundary and as the durable audit trail of intermediate system state.

Specifically:
- Every agent consumes from one or more durable Delta tables and writes to a durable Delta table.
- Each agent must be idempotent on its primary key, performing Delta MERGE writes rather than blind appends.
- The Orchestrator sequences execution and handles tasks/retries but does not pass data or state. It only triggers the agent execution, which queries the upstream tables.

## Consequences

Positive:
- **High Inspectability**: Anyone can query Delta tables at any medallion layer to verify intermediate agent states.
- **Independent Testability & Replayability**: Individual agents can be re-run safely over existing Delta tables without re-executing upstream stages.
- **Robustness/Resilience**: If a stage fails mid-process, it can be resumed or retried without losing already-processed records from earlier stages.
- **Low Memory Overhead**: Agents stream/load data batch-wise as needed rather than holding massive message payloads in memory.

Negative:
- **I/O Overhead**: Disk/storage writes and reads at every stage boundary. For our analytical scale, this is a minor cost compared to LLM latency and API calls.
- **Schema Management**: Upstream changes require schema validation and potentially schema migration/evolution on the Delta tables. Pydantic-to-Spark schema mapping guards help mitigate this.
- **Higher Storage Footprint**: Persisting every intermediate stage increases storage usage, but the tradeoff is accepted in exchange for reproducibility and auditability.

## Alternatives considered

1. **In-memory queue / LangChain/LangGraph-style state management.** Rejected: introduces additional orchestration state management complexity without improving replayability or inspectability for this workload.
2. **Plain JSON/CSV/Parquet files on disk.** Rejected: Lacks ACID transactions, schema enforcement, and idempotent MERGE capability out-of-the-box, which are critical for reliability.
