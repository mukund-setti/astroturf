# ADR-0008: Attachment text extraction silver table

- Status: Proposed
- Date: 2026-05-21

## Context

Most CFPB substantive comment text is expected to live in attachments rather
than inline comment bodies. ParserAgent v2A already catalogs attachment metadata
in `silver.comment_attachments`, and AttachmentDownloaderAgent v2B phase 1
downloads supported files to local storage while recording download provenance.

The next attachment step is deterministic text extraction from already
downloaded files. This must be kept separate from OCR, LLM extraction,
embeddings, and clustering. It must also avoid changing
`silver.parsed_comments` immediately, because that table currently defines the
comment text used by embeddings and clustering. Mutating it would change
downstream semantics and requires its own reconciliation decision.

ADR-0007 is reserved for the Databricks promotion path. This attachment
extraction decision is therefore ADR-0008.

## Decision

Introduce a future `silver.attachment_texts` Delta table as the durable output
of ParserAgent v2B phase 2.

The phase 2 flow is:

```text
silver.comment_attachments
-> downloaded local files
-> silver.attachment_texts
```

Do not mutate `silver.parsed_comments` in this phase. Reconciliation of
attachment text into `parsed_comments` is deferred to a later ADR.

V1 supported formats:

- PDF through the existing `pypdf` dependency.
- TXT through the Python standard library.
- HTML through the existing `beautifulsoup4` dependency.

V1 deferred or unsupported formats:

- DOCX is deferred pending explicit dependency approval for `python-docx` or an
  equivalent deterministic extractor.
- Legacy DOC is unsupported.

The proposed `silver.attachment_texts` table should hold one row per attachment
format, keyed by `attachment_id` for v1. It should include comment and docket
IDs, file provenance, extractor version, extraction method, status, raw and
normalized text, normalized text hash, counts, timestamps, and extraction error
details.

Per-attachment extraction failures should be recorded as rows rather than
silently skipped. Unrecoverable table read, schema, or write failures should
raise.

## Consequences

### Positive

- Keeps attachment text queryable without overloading `silver.comment_attachments`
  or prematurely changing `silver.parsed_comments`.
- Preserves one-to-many comment-to-attachment cardinality.
- Makes extraction idempotent and replayable through a stable attachment-level
  key.
- Allows downstream review of extracted text before it becomes embedding input.
- Avoids dependency churn by limiting v1 to libraries already present.

### Negative / Risks

- Embeddings and clustering will not benefit from attachment text until a later
  reconciliation phase updates the canonical comment text path.
- DOCX attachment content remains unavailable in v1.
- Scanned PDFs will produce `empty_text` until OCR is explicitly designed.
- A future reconciliation ADR must decide how to combine multiple attachment
  texts with inline comment text without obscuring provenance.

## Alternatives Considered

### Write extracted text directly into `silver.parsed_comments`

Rejected for this phase. It would change what downstream embeddings and
clusters mean, especially for comments that currently contain only cover notes.
That change needs a separate ADR and a careful backfill/re-embedding plan.

### Store extracted text on `silver.comment_attachments`

Rejected. `comment_attachments` is a metadata and download-provenance table.
Adding large text fields would bloat the table and mix file-state tracking with
content extraction outputs.

### Store only text sidecar files and keep paths in Delta

Deferred. Sidecar files may be useful later for very large extracted texts, but
the first analytical surface should be a Delta table that is easy to join,
inspect, test, and replay.

### Support DOCX in v1

Deferred. DOCX support likely requires `python-docx`, and this project requires
explicit approval before adding dependencies. The first extraction slice should
avoid dependency churn and prove the table/agent shape with PDF, TXT, and HTML.

### Add OCR or LLM fallback now

Rejected. OCR and LLM extraction are intentionally separate phases with
different cost, quality, and provenance concerns.

## Future Implementation Notes

Future implementation should add:

- `shared/schemas/attachment_texts.py`.
- `merge_attachment_texts(...)` in `shared/delta_utils/silver.py`.
- Pure PDF/TXT/HTML extraction helpers under `agents/parser/`.
- A ParserAgent v2B phase 2 runner that reads downloaded rows from
  `silver.comment_attachments`, writes `silver.attachment_texts`, and logs
  MLflow metrics.
- Unit tests for supported formats, unsupported formats, row-level failures,
  schema parity, idempotent Delta writes, and MLflow counts.

