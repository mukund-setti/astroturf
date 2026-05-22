# ADR 0004: Additive Schema Evolution at Agent Load Time

## Status
Accepted, with a refactor to a shared utility required before a second agent adopts the pattern.

## Context
ParserAgent v2B (the attachment downloader, `agents/downloader/agent.py`) added five new nullable fields to `silver.comment_attachments`:

- `local_path`
- `checksum_sha256`
- `downloaded_at`
- `download_error`
- `size_bytes_actual`

These fields extend the v2A 10-field schema (defined in `shared/schemas/comment_attachments.py`) to 15 fields. Delta tables already on disk from v2A runs hold the old 10-field schema. Without a migration path, opening such a table with the v2B agent would either fail with a schema-mismatch error or silently drop the new columns on subsequent writes.

We chose **automatic in-agent migration** over operator-driven manual migration to keep dev iteration fast: a developer who bumps a schema and re-runs the pipeline should not have to context-switch into a separate migration script.

## Decision
When an agent opens a Delta table and discovers the on-disk schema is missing one or more fields that the agent's canonical schema declares, the agent will:

1. Read the existing table into a PyArrow table.
2. Append a null column for each missing field, typed per the canonical Arrow schema.
3. Cast the table to the canonical schema.
4. Overwrite the Delta table with `write_deltalake(..., mode="overwrite", schema_mode="overwrite")`.

This is permitted **only for purely-additive changes** — adding new nullable columns. The following changes are explicitly NOT covered and require a manual migration:

- Removing columns
- Narrowing types (e.g. `int64` -> `int32`)
- Changing nullability (e.g. nullable -> required)
- Renaming columns

Currently this logic lives inline in `agents/downloader/agent.py` (the block guarded by `missing_fields` at the top of `AttachmentDownloaderAgent.run`). Before a second agent adopts the same pattern, it must move to a shared utility:

```python
# shared/delta_utils/silver.py
def ensure_schema(
    table_path: str | Path,
    expected_arrow_schema: pa.Schema,
    *,
    allow_destructive: bool = False,
) -> None: ...
```

Requirements for the shared utility:

- Log loudly **before** the destructive overwrite, naming the table path, the missing fields being added, and the fact that the operation cannot be undone outside Delta time-travel.
- Require explicit `allow_destructive=True` to perform the overwrite. The default must raise a clear error instructing the operator to either re-run with the flag or migrate manually.
- Reject non-additive diffs (missing columns on the agent side, type changes, nullability changes) regardless of the flag — those require a manual migration.

## Alternatives Considered

### 1. Manual migration scripts (one per schema change)
*Description*: Write a `scripts/migrate_<n>_<desc>.py` for every schema bump; the agent fails fast on schema mismatch until the operator runs it.
*Why Rejected (for v2B)*: Adds friction to every schema change in dev, where the same developer is both bumping the schema and re-running the pipeline. Reconsider for production / Databricks.

### 2. Delta's native `mergeSchema=True` on write
*Description*: Let the writer extend the schema automatically when it writes new fields.
*Why Rejected*: Handles additive changes on **write** but not on **read**. The agent reads the table before writing (to checkpoint already-downloaded rows), so an unmodified read against an old-schema table would still need to be reconciled to the new schema in memory. Additionally, `delta-rs` support for `mergeSchema`-style behavior is less mature than Spark's.

### 3. Fail-fast on any schema mismatch, require operator action
*Description*: Agent raises immediately if the on-disk schema does not exactly match the canonical schema.
*Why Rejected (for v2B)*: Cleanest semantics, but blocks dev iteration on every additive change. Worth revisiting before production deployment, where operator-gated migrations are the safer default.

## Consequences

### Positive
- Dev iteration on schema changes is fast: bump the schema, re-run the agent, done.
- Existing v2A tables on disk continue to work with v2B without manual intervention.

### Negative / Risks
- The overwrite is destructive at the Delta-log level. Time-travel can recover the prior state, but only if someone notices the issue before vacuum. If this policy is ever (incorrectly) extended to non-additive changes, silent data loss becomes possible.
- Schema-migration code currently lives in agent logic, which is the wrong layer. Centralizing into `shared/delta_utils/silver.py::ensure_schema` is a hard requirement before a second adopter — copy-pasting the block into another agent is not acceptable.
- Tests do not currently cover the migration path against a pre-existing table with the old schema; the existing tests create fresh tables in `tmp_path`. The migration code path is exercised in dev runs only. The shared-utility refactor should land with a regression test that builds a v2A-schema table on disk and asserts a v2B agent run upgrades it correctly.

## Revisit when
- A second agent needs schema evolution — refactor to `shared/delta_utils/silver.py::ensure_schema` first, then both adopt it.
- Any non-additive schema change is contemplated — this ADR does not cover it; write a new ADR or add a manual migration.
- Before any production / Databricks deployment — the automatic-overwrite policy may be inappropriate there, and the fail-fast alternative (#3 above) should be reconsidered.
