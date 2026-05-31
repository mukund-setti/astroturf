# ADR-0017: Spark-native Delta writes on Databricks (replace delta-rs FUSE bypass)

- Status: Accepted
- Date: 2026-05-25

## Context

Per ADR-0002 we use delta-rs (`deltalake`) for local Delta writes to avoid the
JVM friction of running PySpark on Windows. That decision still stands for
local development and unit tests.

When the agents started running on Databricks Serverless against Unity Catalog
volumes (`/Volumes/<catalog>/<schema>/<volume>/...`), delta-rs ran into a
fundamental incompatibility with the FUSE volume layer: `delta-rs` requires
POSIX `rename` semantics that the FUSE mount does not provide for the
`_delta_log/` directory. The previous workaround was
`shared/delta_utils/fuse_bypass.py::local_tmp_delta_path`, a context manager
that, for every Delta MERGE against a FUSE path:

1. `shutil.copytree(fuse_path, /tmp/...)` — copies the entire Delta table out
   of the FUSE volume.
2. Runs the delta-rs mutation against `/tmp/...`.
3. `shutil.rmtree(fuse_path)` — deletes the FUSE table.
4. `shutil.copytree(/tmp/..., fuse_path)` — copies the whole thing back.

A live read-only diagnosis of the production Delta tables on 2026-05-25
(captured by `scripts/diagnose_delta_paths.py`) revealed the operational cost:

- `/Volumes/astroturf/demo/exports/_lakehouse/bronze/raw_comments` had 130
  contiguous versions, with **15 MERGE operations executed in a 4-second
  window**, every one of them reporting zero inserts/zero updates. That
  pattern is a single ingestion run looping through ~15 regulations.gov API
  pages and forcing a full `copytree → rmtree → copytree` round-trip for
  each page even when no new data was present.
- With ~5 MB on disk and 121 files, every page paid ~5 MB of FUSE I/O. At
  100K comments this is the source of the observed ~220 rows/min ECFS
  ingestion rate — an order of magnitude below the steady-state rate the
  upstream APIs can support.

The diagnosis also corrected a misconception: there is no Delta log
corruption on any of the underlying path-based tables; all read clean and
have contiguous version history. The "fix" therefore is purely a *writer*
swap, not a data migration.

A second finding is that every Unity Catalog "table" the agents materialize
under `<catalog>.bronze.*`, `<catalog>.silver.*`, and `<catalog>.gold.*` is
actually a **VIEW** created by
`notebooks/databricks/web_analysis_job.py::_register_delta_view` over a
`delta.``<fuse_path>``` location. Views resolve `SELECT * FROM
delta.``<path>``` on every read, so any writer that targets the same FUSE
path is automatically visible through the existing view layer — no view
changes, no migration to UC-managed tables required.

## Decision

We split the Delta writer layer along a single environment-controlled axis:

- **`delta_rs`**: pure-Python writes via the `deltalake` library. Used for
  local Windows development, unit tests, and any code path with no Spark
  session.
- **`spark`**: JVM-backed writes via `delta-spark` and the active
  `pyspark.sql.SparkSession`. Used inside Databricks notebooks and jobs.
  Writes go to the **same `/Volumes/...` paths** the delta-rs branch writes
  to today; the Unity Catalog views resolve them transparently on read.

The split is governed by `ASTROTURF_DELTA_BACKEND` ∈ `{auto, spark, delta_rs}`,
defaulting to `auto`:

- `auto`: use `spark` when (a) the target path looks Databricks-y
  (`/Volumes/...`, `/dbfs/...`, or `dbfs:/...`) **and** (b) a Spark session
  is active; otherwise use `delta_rs`.
- `spark`: always use Spark. Caller's responsibility to ensure a session
  exists. Used inside the production notebook to make the choice explicit
  and skip the path heuristic.
- `delta_rs`: always use delta-rs. Used for rollback scenarios and for the
  unit-test suite, which forces this value to ensure tests never pick up an
  ambient Spark session.

Dispatch happens at the public-API boundary in
`shared/delta_utils/{bronze,silver,gold,attribution,migration,discovery}.py`.
Call sites do not change. The dispatcher logic is centralised in
`shared/delta_utils/backend.py::should_use_spark(path)`. The Spark
implementations live in `shared/delta_utils/spark_writers.py`.

### Additive schema evolution on the Spark backend

**Revised 2026-05-25 after the first H1 smoke gate (run `308263350585017`):**
The first cut of this ADR specified setting
`spark.databricks.delta.schema.autoMerge.enabled = true` per-merge via
`spark.conf.set(...)`. The first hosted FCC `17-108` ECFS smoke failed
in 65 s on the very first `merge_comments` call with:

```
[CONFIG_NOT_AVAILABLE] Configuration
  spark.databricks.delta.schema.autoMerge.enabled
  is not available. SQLSTATE: 42K0I
```

Databricks Serverless restricts which Spark confs can be modified at
runtime; this one is not on the allowlist. The session-conf approach is
therefore not viable for our deployment target. The MERGE never ran and
the bronze table state was unchanged (the failure was at config-set
time, before the write).

We now drive additive evolution explicitly via
`shared/delta_utils/spark_writers.py::spark_ensure_schema`, which the
cross-backend `shared/delta_utils/silver.py::ensure_schema` dispatches to
when `should_use_spark(path)` returns true. The Spark branch:

1. Reads the on-disk Delta schema via
   `spark.read.format("delta").load(path).schema`.
2. Converts the expected PyArrow schema to a Spark `StructType` (prefers
   `pyspark.sql.pandas.types.from_arrow_schema`; falls back to a zero-row
   pandas roundtrip).
3. For fields present in the expected schema but missing on disk, issues
   one `ALTER TABLE delta.``<path>`` ADD COLUMNS (\`col1\` type1, ...)`
   statement (single ALTER, not one per column).
4. For overlapping fields with mismatched types, raises `ValueError` —
   matching the delta-rs branch's destructive-change rejection.
5. For fields present on disk but absent from the expected schema, no
   ALTER is issued and the on-disk column is preserved through subsequent
   MERGEs (`whenMatchedUpdateAll` only touches columns the source
   provides).

`spark_merge` invokes `spark_ensure_schema` itself before MERGE so a
forgetful caller cannot trigger a schema-incompatible MERGE; the call is
cheap (one schema read, no ALTER) when the schemas are already aligned.

This change preserves ADR-0004 verbatim: additive changes evolve, and
destructive changes are refused, on both backends. It also makes the
evolution audit trail explicit — an `ALTER TABLE` line in the job log,
not silent session-conf magic.

Alternatives considered and rejected at this point:

- **`MERGE INTO ... WITH SCHEMA EVOLUTION` SQL clause.** Would work on
  Serverless (DBR 14+ semantics, which Serverless always is) but requires
  switching from the `DeltaTable.merge(...)` Python API to a string-SQL
  MERGE, which loses the typed `whenMatchedUpdateAll`/`whenNotMatchedInsertAll`
  builder. Defensible answer; we picked the explicit-ALTER approach
  because it is also runtime-portable (works on classic DBR clusters
  too) and surfaces evolution events as visible DDL.
- **Table-level `delta.autoMerge.enabled` table property.** Not a real
  Delta property — `ALTER TABLE ... SET TBLPROPERTIES('delta.autoMerge.enabled' = 'true')`
  is silently ignored by Delta; only the *session* conf
  `spark.databricks.delta.schema.autoMerge.enabled` has a code path, and
  that one is denied on Serverless.

### Brand-new path initialization

The very first write to a path that does not yet exist goes through
`spark.write.format("delta").mode("overwrite").save(path)` and reports the
row count as `inserted`. Subsequent calls go through MERGE. This matches
the delta-rs branch which seeds an empty Delta table before merging.

### Empty-source short-circuit

`spark_merge` skips the MERGE call entirely when the source PyArrow table
has zero rows. This avoids the empty-no-op MERGE pattern the IngestionAgent
loop accidentally produced under delta-rs (see Future work).

## Consequences

Positive:

- The 5 MB-per-page FUSE round-trip is gone. Real-world ECFS ingestion of
  `17-108` at 5,000 rows should drop from ~22 minutes to under 8 minutes
  (the H1 acceptance target).
- No data migration. Existing path-based Delta tables continue to receive
  writes at their current FUSE locations.
- No view changes. The Unity Catalog views over `delta.``<path>``` keep
  resolving the same paths and the same data.
- The `ASTROTURF_DELTA_BACKEND=delta_rs` escape hatch gives us a one-flag
  rollback if a Spark-specific issue surfaces in production.

Negative:

- Two writer paths to maintain (already true under ADR-0002; this widens
  the maintenance surface slightly because the Spark path has new code,
  not just configuration). Mitigated by:
  - Shared dispatcher logic in `backend.py`.
  - A `tests/integration/test_spark_writers.py` suite (opt-in via
    `ASTROTURF_RUN_SPARK_TESTS=1`) that exercises the Spark path against
    a local Spark session.
- The Spark `ensure_schema` validator (`spark_writers.spark_ensure_schema`)
  refuses non-additive changes (type mismatch on overlapping columns) the
  same way the delta-rs branch does, so destructive-change rejection now
  lives on both backends. Pydantic remains the upstream source-of-truth;
  the schema gate is the last line of defense if a dynamic Arrow schema
  ever drifts.
- The FUSE-path heuristic is conservative (`/Volumes/`, `/dbfs/`, `dbfs:/`).
  If a future deployment target uses a different path prefix we will need
  to extend `backend.looks_like_databricks_path`.

## Alternatives considered

1. **Switch to UC-managed tables (`saveAsTable("astroturf.bronze.raw_comments")`).**
   Rejected: today's UC entries are views over path-based Delta. Switching
   to managed tables would either collide with the existing views or
   silently fork the data into UC-managed storage. The migration cost is
   non-trivial and the diagnosis showed it isn't required — Spark writes
   to the existing FUSE paths solve the actual problem.
2. **Single-Spark-everywhere (drop delta-rs).** Rejected: local Windows
   tests would need Java + a Spark session per test, taking the test suite
   from ~10s to ~30s+ per run and reintroducing the `HADOOP_HOME` /
   `winutils.exe` friction ADR-0002 explicitly eliminates.
3. **Single-delta-rs-everywhere (keep FUSE bypass).** Rejected: that's the
   problem we're solving.
4. **`MERGE INTO ... WITH SCHEMA EVOLUTION` SQL syntax (DBR 14+ and
   Serverless).** Considered as the schema-evolution mechanism after the
   session-conf approach failed on Serverless. Defensible — Serverless
   is always DBR 14+ by definition — but it forces a switch from the
   typed `DeltaTable.merge(...)` Python API to a string-SQL MERGE,
   losing the `whenMatchedUpdateAll` / `whenNotMatchedInsertAll`
   builder. We picked the explicit `ALTER TABLE ADD COLUMNS` approach
   (see the "Additive schema evolution" section above) because it is
   runtime-portable, surfaces evolution as visible DDL in the job log,
   and aligns literally with ADR-0004's "additive evolution is an
   explicit operation" wording.
5. **Restore the corrupted `bronze.raw_comments` via `RESTORE TABLE`.**
   The diagnosis showed there is no corruption to restore from. Dropped.
6. **Re-ingest existing dockets into a new `bronze.raw_comments_v2`.**
   Dropped for the same reason.

## Future work

1. **Eliminate the empty-MERGE-per-page pattern in `IngestionAgent`.**
   The diagnosis surfaced 15 sequential no-op MERGEs in a 4-second window
   inside a single ingestion run — one per regulations.gov API page, all
   reporting zero inserts and zero updates. After H1 this is a cheap
   transaction (no FUSE round-trip) instead of a 5 MB FUSE round-trip, so
   it is no longer a *crippling* cost. It is still waste. The right fix is
   batched ingestion writes: buffer ~20 API pages (~5,000 rows) before
   calling `merge_comments`. That work belongs in `agents/ingestion/agent.py`
   and is tracked as a follow-up in the production-blocker plan (Tier 3
   architectural work). `spark_writers.spark_merge` already short-circuits
   on empty source tables so the simplest "skip when nothing changed"
   variant is already free on the writer side.
2. **Recalibrate `ui/lib/runtime-estimate.ts` constants.** Today's
   `STAGE_RATES` were calibrated under the FUSE-bound regime and will be
   wrong post-H1. Tracked as S5 in the production-blocker plan.
3. **Promote to UC-managed tables (`saveAsTable`).** Optional future
   improvement: register the medallion tables directly as Unity Catalog
   managed tables instead of via the view-over-FUSE-path indirection. This
   would simplify the operational model and enable Delta features that
   are catalog-aware (e.g. `OPTIMIZE` scheduling via UC). Out of scope for
   H1; would deserve its own ADR.

## Revisit if

- Databricks ships a delta-rs-compatible FUSE rename layer for Unity
  Catalog volumes (would allow collapsing the two backends).
- We need a Delta write feature that delta-rs supports but `delta-spark`
  in our pinned version does not (unlikely but possible).
- We adopt Asset Bundles for the full notebook job spec and gain a
  one-step deploy of writer changes; that would shrink the local/Databricks
  sync gap and might justify revisiting the single-backend question.
