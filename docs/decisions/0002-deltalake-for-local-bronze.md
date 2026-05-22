# ADR-0002: Use delta-rs (`deltalake`) for local bronze writes

- Status: Accepted
- Date: 2026-05-21

## Context

The IngestionAgent writes public comments to a bronze Delta table. CLAUDE.md specifies a medallion lakehouse and the project will run on Databricks in production, where PySpark + Delta Lake is the obvious choice.

Local development happens on Windows. The initial plan was to use PySpark + `delta-spark` locally as well, on the theory that "we'll need Spark eventually" and one stack is simpler than two. In practice this brings:

- A JVM dependency and ~10s cold-start per process.
- `HADOOP_HOME` + `winutils.exe` requirements on Windows, which routinely break developer setup.
- Slow unit tests (every test that touches storage pays the JVM startup tax).
- A surface area of Hive metastore / catalog config to maintain that we don't need yet.

None of this is fundamental to what IngestionAgent does. The agent stages rows in memory, then performs an idempotent upsert on `comment_id`. That is exactly what `deltalake` (delta-rs, the Rust implementation with Python bindings) handles natively, with no JVM.

## Decision

Use `deltalake` + `pyarrow` for **local** bronze writes (and any other local Delta I/O in development and unit tests). `pyspark` and `delta-spark` remain in `pyproject.toml` and are used for production runs on Databricks.

Concretely:

- `shared/delta_utils/bronze.py` exposes `merge_comments(path, arrow_table, key)` backed by `DeltaTable.merge(...)` from delta-rs.
- `shared/schemas/comments.py` is the single source of truth (Pydantic). It exposes both `raw_comment_arrow_schema()` (used now by the delta-rs writer) and `raw_comment_struct()` (kept for the Databricks/Spark path) — a unit test guards against drift.
- Local bronze table lives at `./data/bronze/raw_comments` as a path-based Delta table (no Hive metastore).

## Consequences

Positive:
- No JVM, no `HADOOP_HOME`, no `winutils.exe`. Tests run in under 10 seconds.
- Unit tests use the real Delta format end-to-end (not a mock), so idempotent-merge behaviour is exercised in CI.
- Lower-friction local dev — new contributors don't need to install Java to run the agent.
- delta-rs writes a Delta Lake table that Databricks/Spark can read directly when we promote.

Negative:
- Two write paths exist (delta-rs locally, PySpark on Databricks). Schemas, partitioning, and table properties have to stay aligned across them. The schema sync test catches the field-level case; partition layout and table properties will need similar guardrails when we add them.
- delta-rs lags Delta Lake feature releases (DVs, column mapping, etc.). We don't use any of those features today, but we should re-check before adopting one.
- Some Delta features (Z-ORDER, complex MERGE conditions) are PySpark-only. Anything we want available locally has to be expressible in delta-rs.

## Alternatives considered

1. **PySpark + delta-spark locally.** Rejected: Windows JVM friction is a real, recurring blocker for development, and IngestionAgent specifically doesn't need any Spark-only capability.
2. **Plain Parquet locally, Delta on Databricks.** Rejected: loses idempotent MERGE locally, which is a project-wide non-negotiable per CLAUDE.md.
3. **A managed local stack (DuckDB, Polars + sqlite).** Rejected: takes us off the Delta format entirely, which complicates the bronze-to-silver handoff and the eventual Databricks promotion.

## Revisit if

- Databricks Connect on Windows becomes a reliable, zero-config experience for local development.
- We need a Delta feature locally that delta-rs doesn't support.
- The two-writer-path maintenance cost outweighs the JVM-friction savings (e.g., once we have many local writers).
