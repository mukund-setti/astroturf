# Attachment text extraction plan

This plan records the intended design for ParserAgent v2B phase 2: deterministic
text extraction from attachments that have already been downloaded by
AttachmentDownloaderAgent. It is a parked design, not an implementation task.
The near-term active path remains clusters-visible work and the Databricks
integration slice.

## Summary

The extraction path should be:

```text
silver.comment_attachments
-> downloaded local files
-> silver.attachment_texts
-> later reconciliation into silver.parsed_comments
```

ParserAgent v2B phase 2 should introduce a separate
`silver.attachment_texts` table for extracted attachment text. It should not
mutate `silver.parsed_comments`. Reconciliation into `parsed_comments` changes
what embeddings and clustering mean, so it is deferred to a later ADR.

## Non-goals

- OCR for scanned PDFs.
- LLM-assisted extraction.
- Embedding extracted attachment text.
- Clustering extracted attachment text.
- Reconciling attachment text into `silver.parsed_comments`.
- Adding new dependencies.
- Supporting DOCX in v1.
- Supporting legacy DOC files.

## Supported formats for v1

V1 should support deterministic extraction for:

| Format | Support | Library |
| --- | --- | --- |
| PDF | Supported | Existing `pypdf` dependency |
| TXT | Supported | Python standard library |
| HTML | Supported | Existing `beautifulsoup4` dependency |
| DOCX | Deferred | Requires explicit approval for `python-docx` |
| DOC | Unsupported | Legacy binary format; no v1 support |

DOCX is intentionally deferred to avoid dependency churn. If later approved,
`python-docx` is the likely dependency because it provides deterministic text
extraction from paragraphs and tables without invoking OCR, LLMs, or office
conversion tools.

## Proposed table: silver.attachment_texts

`silver.attachment_texts` should be the durable output table for deterministic
attachment extraction. It should be one row per extracted attachment format,
matching the cardinality of `silver.comment_attachments`.

Proposed fields:

| Field | Purpose |
| --- | --- |
| `attachment_id` | Stable primary key from `silver.comment_attachments` |
| `comment_id` | Parent comment ID |
| `docket_id` | Docket scope |
| `format` | Attachment format, normalized lowercase |
| `file_name` | Original attachment title or filename, if known |
| `local_path` | Downloaded file path used for extraction |
| `checksum_sha256` | Download checksum used for provenance |
| `extractor_version` | Deterministic extractor version, for example `v2B_phase2_v1` |
| `extraction_method` | Method such as `pypdf`, `text_decode`, or `beautifulsoup4` |
| `extraction_status` | `extracted`, `empty_text`, `unsupported_format`, or `failed` |
| `raw_text` | Extracted plain text, if any |
| `normalized_text` | Lowercased whitespace-normalized text |
| `normalized_text_hash` | SHA-256 hash of normalized text |
| `char_count` | Character count for raw extracted text |
| `token_estimate` | Approximate token count using the existing project convention |
| `page_count` | PDF page count, nullable for non-PDF formats |
| `extracted_at` | UTC extraction timestamp |
| `extraction_error` | Error summary for failed or unsupported rows |

The v1 primary key should be `attachment_id`. If future runs need multiple
extractor versions to coexist, a later ADR can change or extend the key to
`(attachment_id, extractor_version)`.

## Multiple attachments per comment

Extraction should process each attachment independently. A comment with multiple
attachments produces multiple rows in `silver.attachment_texts`, all linked by
the same `comment_id`.

The extraction phase should not concatenate attachment text into one
comment-level record. A later reconciliation phase can decide how to combine
multiple successful attachment texts, likely using a stable `attachment_id`
ordering and explicit separators that preserve provenance.

## Failure handling

Attachment extraction should be row-tolerant and run-strict:

- Table read, schema, or write failures are unrecoverable and should raise.
- Per-attachment extraction failures should be captured in
  `silver.attachment_texts` without stopping the rest of the run.

Recommended per-row statuses:

| Status | Meaning |
| --- | --- |
| `extracted` | Deterministic extraction produced non-empty text |
| `empty_text` | Extraction succeeded but produced no substantive text |
| `unsupported_format` | Format is not supported by v1 |
| `failed` | File was missing, unreadable, encrypted, corrupt, or raised an exception |

Examples:

- A scanned PDF with no embedded text should become `empty_text`, not a fake
  success.
- A missing `local_path` or missing file on disk should become `failed`.
- A legacy DOC file should become `unsupported_format`.
- A single corrupt attachment should not prevent other attachments from being
  extracted.

## MLflow metrics

Each extraction run should log an MLflow run with inputs, outputs, quality
signals, and timing.

Recommended parameters:

- `docket_id`
- `attachments_table_path`
- `attachment_texts_path`
- `max_attachments`
- `extractor_version`
- `supported_formats`

Recommended metrics:

- `attachments_read`
- `attachments_eligible`
- `attachments_extracted`
- `attachments_empty_text`
- `attachments_failed`
- `attachments_unsupported_format`
- `attachments_skipped_not_downloaded`
- `rows_written`
- `total_chars_extracted`
- `median_chars_per_attachment`
- `pdf_pages_seen`
- `pdf_extracted`
- `txt_extracted`
- `html_extracted`
- `duration_seconds`

## Tests needed

Future implementation should include tests for:

- PDF extraction from a small text PDF.
- PDF with no extractable text producing `empty_text`.
- TXT decoding and whitespace normalization.
- HTML tag stripping with BeautifulSoup.
- Unsupported DOCX in v1 unless dependency approval has happened.
- Unsupported legacy DOC.
- Missing local file recorded as `failed`.
- One bad attachment not stopping other attachments in the same run.
- Delta merge idempotency: reruns update the same `attachment_id` without
  duplicates.
- Pydantic, Arrow, and Spark schema parity for `silver.attachment_texts`.
- MLflow metrics for core counts.

## Future implementation plan

This file list is a future plan only:

- `docs/decisions/0008-attachment-text-extraction-silver-table.md`: ADR for the
  new silver table and deferred reconciliation.
- `shared/schemas/attachment_texts.py`: Pydantic model plus derived Arrow and
  Spark schemas.
- `shared/delta_utils/silver.py`: `merge_attachment_texts(...)`, keyed by
  `attachment_id`.
- `agents/parser/attachment_extractors.py`: pure helpers for PDF, TXT, and HTML
  extraction plus normalization and hashing.
- `agents/parser/attachment_text_agent.py`: phase 2 agent that reads downloaded
  attachments, extracts text, writes `silver.attachment_texts`, and logs MLflow.
- `scripts/extract_attachment_text.py`: thin CLI wrapper.
- `tests/unit/test_attachment_text_extractors.py`: format-specific extractor
  tests.
- `tests/unit/test_attachment_text_agent.py`: Delta idempotency, row failure,
  and MLflow tests.
