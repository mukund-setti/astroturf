# ADR 0003: Parser Detail Enrichment Side Tables

## Status
Proposed

## Context
The Regulations.gov API search and list endpoints return high-level comment summaries (such as comment ID, title, and partial summary snippets) but omit:
1. The full body text of the submitted comment (which resides under `attributes.comment` in the detail payload).
2. The nested attachments and document format URLs (which are only accessible when querying the comment detail resource with `?include=attachments`).

Relying exclusively on the initial ingestion list-metadata (Bronze) severely limits downstream campaign detection since:
- Long substantive comments are truncated.
- Duplicate boilerplate letter campaigns cannot be thoroughly checked if text is cropped or missing.
- Discovered attachment documents are completely hidden from downstream text extraction engines.

Therefore, the system requires a robust parser stage (**ParserAgent v2**) to fetch full detail records and map them into the Silver layer.

## Decision
We implement a three-table Medallion Silver schema structure:
1. **`silver.parsed_comments` (Main Text Source Table)**:
   Retains the central, clean, and normalized plain-text bodies of comments. It contains the primary comment text (extracted from HTML using BeautifulSoup) or titles as fallbacks. We append `attachment_count` to this schema.
2. **`silver.comment_details` [NEW]**:
   A side table that stores the raw GET detail comment JSON payload stringified in `raw_detail_json`, providing complete audit provenance and raw replayability. It tracks the enrichment status (success/failed) and heuristic classifications (substantive vs. cover note).
3. **`silver.comment_attachments` [NEW]**:
   A side table that catalogs discovered attachment metadata (compound key: `{attachment_id}_{format}`), including title/filename, source URLs, formats, file size, detection dates, and download states.

**ParserAgent v2A** will catalog these attachments and map all metadata, but **will not download attachment files** at this stage. Downloads and OCR are deferred to the subsequent v2B phase.

## Alternatives Considered

### 1. Unified Schema (Storing everything inside `parsed_comments`)
*Description*: Add string/JSON columns directly to the `parsed_comments` table containing stringified detail payloads and lists of attachment metadata.
*Why Rejected*:
- **Relational Overhead**: Attachment data naturally has a one-to-many cardinality relative to comments. Forcing attachments into stringified JSON blobs in a single table ruins standard SQL queryability, analytical aggregations (e.g. tracking attachment formats), and pipeline step chaining.
- **Table Bloat**: Storing raw stringified JSON detail payloads (which can be several kilobytes per comment) alongside frequently queried text search indices creates unnecessary I/O overhead.

### 2. Immediate Eager Attachment Downloading
*Description*: Download and run text extraction / OCR on all PDFs immediately inside the ParserAgent v2A run loop.
*Why Rejected*:
- **Rate-Limit Vulnerability**: Network GET requests to pull large PDF files are expensive. Combining detail JSON fetches and multiple PDF downloads into a single sequential script greatly increases runtime, rate-limiting exposure, and risk of timeouts.
- **Separation of Concerns**: Metadata cataloging is highly deterministic and fast. PDF text extraction, OCR, and document format parsing represent CPU-intensive operations that belong in a dedicated pipeline stage (v2B).

### 3. Skip Detail Enrichment Entirely
*Description*: Proceed with campaign detection (embeddings, clustering) using only the short summary texts/titles provided by the list endpoints.
*Why Rejected*:
- Completely misses campaigns that submit attachments with short boilerplate cover letters (e.g. "Attached please find our comment").
- Prevents deep content inspection and semantic analysis, leading to high false-negative rates in coordinate campaign identification.

## Consequences

### Positive
- **High Data Provenance**: Complete JSON detail payloads are archived in `silver.comment_details`, allowing retroactive reprocessing or schema migrations without re-fetching from the live API.
- **Clean Relational Modeling**: Separating attachments into a structured table (`silver.comment_attachments`) simplifies analytical queries (e.g., aggregating file size, counting formats).
- **Staged execution**: Deferring raw downloads avoids bloating API queues and allows separate throttling / orchestration of the heavy I/O phase.
- **Efficient Checkpointing**: The `comment_details` table acts as a natural transaction log. We can easily identify already enriched rows, permitting zero-cost checkpoint restarts if the pipeline is interrupted.

### Negative / Risks
- **Increased API Consumables**: Detail enrichment requires one additional API call per comment. Throttling and quota limits must be strictly managed.
- **Safety Mitigations**: We address rate limit exhaustion by implementing Tenacity-based exponential retry handlers and introducing a `max_detail_fetches` parameter to enforce strict, user-defined safety boundaries on active API calls.
