# ADR-0012: Bronze schema unification across sources

- Status: Accepted
- Date: 2026-05-23

## Context

Until now `bronze.raw_comments` has stored only regulations.gov v4 records.
Phase 1 of the FCC ECFS work introduces a second source: the FCC Electronic
Comment Filing System public API at `publicapi.fcc.gov/ecfs`. We need to decide
whether ECFS rows land in the existing bronze table or somewhere new, and how
the field shape differs.

The two sources overlap heavily on what we actually use downstream
(`comment_text`, `received_date`, `document_type`, attribution fields) but
diverge on identifiers, document organization, and some submitter context:

- regulations.gov uses split `firstName`/`lastName`/`organization`, exposes
  submitter `city`/`state`/`country`, and returns one comment per record with
  an HTML body in `attributes.comment`.
- ECFS returns a `filings` array where each filing has multiple `filers[]`,
  multiple `authors[]`, an array of `documents[]` (PDFs etc.), a multi-valued
  `proceedings[]` (so one filing can be filed under multiple dockets), an
  inline plain-text body in `text_data`, and no submitter geography. The
  submission-type taxonomy is ECFS-specific (`submissiontype.id`,
  `submissiontype.description`), and a boolean-ish `express_comment` field
  distinguishes consumer comments from formal filings.

The semantically identical fields (received/posted/last-modified dates,
document type, submitter name, comment text, has-attachments) dominate. The
divergent fields are either source-specific identifiers we want to keep for
debugging/idempotency (e.g. ECFS `id_proceeding`, `submissiontype.id`) or
context we already plan to stash in `attributes_json` (the per-row JSON escape
hatch the bronze schema already carries).

ADR-0004 governs how schema changes propagate to existing on-disk Delta
tables: only additive, nullable columns are allowed, applied at agent load
time via `shared/delta_utils/silver.py::ensure_schema()` with explicit
`allow_destructive=True`. That constraint shapes the available options.

## Decision

Keep one bronze table, `bronze.raw_comments`, and extend its schema additively
to cover both sources.

### Schema additions

Four new columns, all **nullable in the Arrow / Spark schema** so ADR-0004's
`ensure_schema()` can migrate existing tables in place, and three of the four
**Pydantic-required at write time** so the IngestionAgent cannot insert a row
with a missing source label:

| Column                      | Arrow type              | Pydantic | Notes                                                                                  |
| ---                         | ---                     | ---      | ---                                                                                    |
| `source`                    | `string`                | required | Literal `"regulations_gov"` or `"ecfs"`. Backfilled to `"regulations_gov"` on existing rows. |
| `ecfs_proceeding_id`        | `string`                | nullable | ECFS-internal `proceedings[i].id_proceeding` for the queried docket. NULL for regulations.gov rows. |
| `ecfs_submission_type_id`   | `int64`                 | nullable | `submissiontype.id`. NULL for regulations.gov rows.                                    |
| `ecfs_express_comment`      | `bool`                  | nullable | Coerced from ECFS `express_comment` (0/1 in the raw payload). NULL for regulations.gov rows. |

"Pydantic-required, Arrow-nullable" matches how `comment_id`, `docket_id`, and
`ingested_at` already work: the on-disk column metadata says `nullable=True`
(so `ensure_schema()` can migrate without changing nullability later, which
ADR-0004 rejects as non-additive), and the `RawComment` Pydantic model rejects
any record missing the field at IngestionAgent write time.

This avoids the trap that "make `source` non-nullable going forward" would
otherwise create: `ensure_schema()` explicitly rejects nullability changes
(`shared/delta_utils/silver.py:179-183`). Once a column is added nullable on
disk it stays nullable on disk. Required-ness lives in the Pydantic layer.

### Field mapping

The unified row shape for both sources, with the source of each field. Fields
not listed below keep their existing Pydantic / Arrow definitions and are
populated as today for regulations.gov rows; ECFS rows leave them NULL.

| Bronze field                | regulations.gov source                 | ECFS source                                                                | Notes                                                                              |
| ---                         | ---                                    | ---                                                                        | ---                                                                                |
| `comment_id`                | `data[i].id`                           | `filing[i].id_submission`                                                  | Unique within each source; uniqueness across sources guaranteed because the prefix spaces don't overlap (regulations.gov is `<agency>-<docket>-NNNN` style, ECFS is a long numeric). |
| `docket_id`                 | the docket we queried                  | the proceeding name we queried (e.g. `"17-108"`)                           | Always pinned to the queried docket, **not** `proceedings[0].name`, so re-runs are stable for filings cross-listed to multiple proceedings. |
| `source`                    | literal `"regulations_gov"`            | literal `"ecfs"`                                                            | New column; see "Schema additions" above.                                          |
| `document_type`             | `attributes.documentType`              | `submissiontype.description`                                               | `"COMMENT"`, `"LETTER"`, `"PUBLIC NOTICE"`, etc.                                   |
| `title`                     | `attributes.title`                     | NULL                                                                        | ECFS filings don't carry a title.                                                  |
| `posted_date`               | `attributes.postedDate`                | `date_disseminated`                                                         | "Made publicly visible" date in both systems.                                      |
| `received_date`             | `attributes.receivedDate`              | `date_received`                                                             | Direct analog.                                                                     |
| `last_modified_date`        | `attributes.lastModifiedDate`          | `date_last_modified` if present else `date_submission`                      | Many ECFS records omit `date_last_modified`; falling back to `date_submission` preserves a non-null watermark for incremental ingestion. |
| `comment_text`              | `attributes.comment` (HTML)            | `text_data` (plain text)                                                   | ECFS text is already plain, not HTML. ParserAgent will need to skip the BS4 strip step for `source == "ecfs"` rows — handled when ParserAgent is taught about the new source. |
| `submitter_name`            | `attributes.submitterName`             | `"; ".join(f["name"] for f in filers if f.get("name"))`, empty → None      | ECFS routinely has multiple filers; joined here for compact display while the full array survives in `attributes_json`. |
| `first_name`, `last_name`   | `attributes.firstName`, `attributes.lastName` | NULL                                                                 | ECFS doesn't split filer names.                                                    |
| `organization`              | `attributes.organization`              | `lawfirms[0].name` if present, else NULL                                   | Best-effort; full info in `attributes_json`.                                       |
| `city`, `state_province_region`, `country` | `attributes.city`, `attributes.stateProvinceRegion`, `attributes.country` | NULL                            | ECFS doesn't expose submitter location on the public API.                          |
| `agency_id`                 | `attributes.agencyId`                  | literal `"FCC"`                                                             |                                                                                    |
| `has_attachments`           | `attributes.hasAttachments`            | `len(documents) + len(attachments) > 0`                                    |                                                                                    |
| `attributes_json`           | `json.dumps(attributes, default=str, sort_keys=True)` | `json.dumps(filing, default=str, sort_keys=True)` with `_index`, `@timestamp`, `@version` stripped | Raw escape hatch; preserves everything we didn't promote to a column. |
| `ingested_at`               | `datetime.now(UTC)` at write time      | same                                                                        |                                                                                    |
| `ecfs_proceeding_id`        | NULL                                   | `proceedings[i].id_proceeding` where `name == queried docket`              |                                                                                    |
| `ecfs_submission_type_id`   | NULL                                   | `submissiontype.id`                                                         |                                                                                    |
| `ecfs_express_comment`      | NULL                                   | `bool(filing.express_comment)`                                              |                                                                                    |

### Backfill of existing rows

A one-time idempotent script, `scripts/backfill_source_field.py`, runs
`ensure_schema()` on `bronze.raw_comments` to add `source` (and the three
`ecfs_*` columns) as nullable, then sets `source = "regulations_gov"` on every
row where it is NULL. Idempotent because a second invocation finds zero NULL
`source` rows and writes nothing. The script targets local Delta by default
and the Databricks Unity Catalog table under `--target databricks`.

Pydantic-required-ness on `source` is enforced **from the moment the new
`RawComment` model lands**. The window where an unbackfilled local Delta table
exists (after pulling the new schema but before running the backfill) is
acceptable because no agent will refuse to *read* such a table — only writes
go through the Pydantic-validated path. The backfill script is the gate
between schema bump and any new write activity.

### Env var: `DATA_GOV_API_KEY`

Both sources are fronted by the api.data.gov gateway and accept the **same**
key. The existing `REGULATIONS_GOV_API_KEY` env var is misnamed for a
multi-source world. Going forward:

- The canonical env var is `DATA_GOV_API_KEY`.
- For backward compatibility during the transition, the IngestionAgent and
  any script that reads the key falls back to `REGULATIONS_GOV_API_KEY` when
  `DATA_GOV_API_KEY` is unset, and emits a `WARNING`-level deprecation log
  line ("REGULATIONS_GOV_API_KEY is deprecated; rename to DATA_GOV_API_KEY in
  your .env"). Removal of the fallback is scheduled for the next ADR in this
  area, no earlier than after the Phase 2 ingestion work completes.
- ECFS still authenticates via the `api_key=...` query-string parameter (not
  a header); regulations.gov v4 still uses the `X-Api-Key` header. Same
  underlying key, different transport.

This is a deliberately soft rename — the existing CFPB ingestion artifacts
and the EPA Databricks Workflow run rely on the old name. The fallback gives
those a runway without immediate breakage.

## Consequences

### Positive

- Downstream agents (ParserAgent, EmbeddingAgent, ClusteringAgent,
  AttributionAgent, MigrationAgent) read from a single bronze table and don't
  need source-aware query branching for the source-agnostic majority of their
  work. They can optionally `WHERE source = 'ecfs'` when source-specific
  behavior is needed (e.g. ParserAgent skipping HTML stripping).
- ADR-0004's existing `ensure_schema()` machinery does the migration; no new
  schema-evolution policy is needed.
- The `attributes_json` escape hatch already established for regulations.gov
  extends naturally to ECFS, preserving raw provenance without inflating the
  structured schema.
- The `source` column lets us count, filter, and partition by data source
  without parsing IDs.

### Negative / Risks

- The unified row carries NULLs for source-specific submitter fields
  (`first_name`, `last_name`, `city`, etc. are always NULL for ECFS;
  `ecfs_*` are always NULL for regulations.gov). Storage is cheap and queries
  ignore NULLs cleanly, but reviewers reading the table by eye will see a
  "wide and sparse" shape. Mitigated by `source`-aware UI rendering when that
  matters.
- ParserAgent currently assumes `comment_text` is HTML. It must be taught to
  branch on `source` for the text-extraction step. The ParserAgent change
  ships in this Phase 1 work; downstream agents need no change.
- One-filing-multiple-proceedings means a single ECFS filing can legitimately
  land in `bronze.raw_comments` under more than one `docket_id` if we ingest
  multiple proceedings. The unique key is `(source, comment_id, docket_id)`
  in spirit, but the current Delta MERGE key is `comment_id` alone
  (`shared/delta_utils/bronze.py:25`). For Phase 1 this is fine — we ingest
  one docket — but Phase 2 must revisit the MERGE predicate before ingesting
  overlapping proceedings. Captured here so the constraint isn't lost.
- `comment_id` uniqueness across sources is currently asserted by inspection
  of the actual ID spaces (regulations.gov is e.g. `EPA-HQ-OAR-2021-0317-NNNN`,
  ECFS is a long numeric like `10827765714655`). We don't enforce it
  structurally. If a collision is ever observed in practice, the MERGE key
  must include `source`.
- The `DATA_GOV_API_KEY` rename adds a small surface of confusion during the
  fallback window. Mitigated by a loud deprecation log line on every use of
  the old name.

## Alternatives considered

### 1. Separate bronze tables per source (`bronze.raw_comments_regulations_gov`, `bronze.raw_comments_ecfs`)

Rejected. Splitting the bronze layer forces every downstream agent
(ParserAgent, EmbeddingAgent, ClusteringAgent, AttributionAgent,
MigrationAgent) to do a `UNION ALL` across two tables for the common case
where source doesn't matter — which is the case for embeddings, clustering,
and most attribution work. The medallion architecture in
`docs/architecture.md` treats bronze as a single physical surface; a per-source
split would cascade into per-source splits at every later layer or force a
silver-level union we'd rather not have. Per-source tables also doubles the
schema-migration surface for additive changes that apply to both
(e.g. adding a new attribution-relevant field next quarter).

### 2. Source-prefixed field names (`regulations_first_name`, `ecfs_id_submission`, etc.)

Rejected. The semantically identical fields — `received_date`, `posted_date`,
`document_type`, `submitter_name`, `comment_text`, `has_attachments` — are
the majority of what downstream agents touch. Prefixing each of those
duplicates columns for the shared case and obscures the source-agnostic
contract. We keep prefixing **only for genuinely source-specific concepts**
(`ecfs_proceeding_id`, `ecfs_submission_type_id`, `ecfs_express_comment`),
where the prefix signals "expect NULL for the other source."

### 3. Normalize to a lowest-common-denominator schema (drop any field not present in both sources)

Rejected. We'd lose `first_name`/`last_name`/`city`/`state`/`country` (only
in regulations.gov) and `ecfs_*` discriminators (only in ECFS). The
`first_name`/`last_name` split is used today by the debug UI and may matter
for attribution. The `ecfs_express_comment` flag distinguishes the 24M
consumer-comment firehose from the 30K formal filings — a critical filter
for any FCC-flavored downstream analysis. Reducing to a common subset
throws away signal that costs nothing to keep.

### 4. Single source-tagged "extra attributes" JSON column (no source-specific columns, everything not in the shared subset goes in JSON)

Rejected. We already have `attributes_json` for the raw-payload escape hatch.
But hiding *commonly queried* discriminators like `express_comment` and
`submission_type_id` inside an opaque JSON blob forces every reader to do
JSON extraction for routine filtering ("just show me express comments from
docket 17-108"). The current decision keeps `attributes_json` for raw
provenance and promotes only the small set of repeatedly useful ECFS
discriminators to structured columns.

### 5. Make `source` non-nullable in the on-disk Arrow / Spark schema

Rejected — not because the goal is wrong but because the mechanism is closed.
ADR-0004's `ensure_schema()` rejects nullability changes on existing columns.
Adding `source` as `nullable=False` at the Arrow level would mean either
(a) a destructive table rebuild outside `ensure_schema()`, which contradicts
ADR-0004's policy, or (b) carrying the column as nullable forever even though
we want it required. We chose (c): "Pydantic-required, Arrow-nullable" —
required at the IngestionAgent's write boundary (where the Pydantic model
validates), nullable in the on-disk column metadata. This matches how
`comment_id`, `docket_id`, and `ingested_at` already work.

### 6. Hard rename of `REGULATIONS_GOV_API_KEY` to `DATA_GOV_API_KEY` with no fallback

Rejected for Phase 1. The old name is referenced by the live CFPB ingestion
runs, the EPA Databricks Workflow run, and any team `.env` files. A hard
rename breaks those without warning. The fallback-with-deprecation-log lets
us land the rename now and harvest the cleanup in a follow-up after Phase 2.

## Revisit when

- Phase 2 ingestion ingests overlapping ECFS proceedings (one filing in
  multiple dockets), forcing a `(source, comment_id, docket_id)` MERGE key in
  `shared/delta_utils/bronze.py`.
- A third source (state-level rulemaking portals, EU/UK equivalents) is
  added — if that source's required fields don't fit the current additive
  pattern, this ADR's "one wide table" approach may need a revisit against
  Alternative 1.
- A real `comment_id` collision is observed between regulations.gov and ECFS
  — forces the MERGE-key fix above immediately.
- The `REGULATIONS_GOV_API_KEY` deprecation fallback is removed. A
  follow-up ADR (or amendment) will land then.
