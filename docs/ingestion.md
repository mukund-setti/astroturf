# Public Comments Ingestion Layer (`IngestionAgent`)

The Ingestion Layer is the foundational stage of the AstroTurf detection engine. It is responsible for robustly fetching public submission metadata from the Regulations.gov v4 API, merging it idempotently into a local Delta Lake bronze table (`data/bronze/raw_comments`), and enabling downstream agents (e.g. `ParserAgent`, `DetectionAgent`) to operate on replayable, durable states.

---

## 1. How IngestionAgent Works

The `IngestionAgent` takes a Regulations.gov docket ID (e.g., `FDA-2023-N-2177`), paginates through the list of public comments, processes the metadata into a flat PyArrow schema, and writes it to a bronze Delta table using a Delta merge operation.

### Component Flow:
1. **Fetch Pages (`_iter_pages`)**: Under a single cursor window, hits `/comments` at up to 250 records per page.
2. **Standardize and Parse (`_to_raw_comment`)**: Extracts attributes (such as dates, title, document type, agency ID, has attachments) into the standard `RawComment` schema.
3. **Write & Deduplicate (`merge_comments`)**: Performs an upsert (merge) onto the local Delta table using `comment_id` as the primary merge key. This ensures that duplicate records are updated in place rather than appended.

---

## 2. Advanced Pagination & Cursoring

### The >5,000 Comment Challenge (Date-Window Cursoring)
The Regulations.gov v4 API limits standard pagination to **5,000 records** per query (a maximum of 20 pages of 250 items each). Attempting to request `page[number]=21` or higher throws a `400 Bad Request` error.

To ingest dockets exceeding 5,000 comments, the `IngestionAgent` uses **date-window cursoring**:
1. **Initial Request**: Sorts all comments in ascending order by `lastModifiedDate` and `documentId`.
2. **Advancing the Window**: At the 5,000-comment cap (page 20), it extracts the raw `lastModifiedDate` of the very last record retrieved in that window.
3. **Shifting the Cursor**: It starts a new query window with a `filter[lastModifiedDate][ge]` filter set to this cursor date. The sorting ensures we pick up exactly where the last window left off.
4. **Boundary Deduplication**: Since the `[ge]` (greater than or equal to) operator is inclusive, overlapping comments at the exact boundary timestamp will be fetched again in the new window. The Delta Lake merge key (`comment_id`) handles this gracefully by deduplicating them.

### Eastern Time Zone Filter Requirement
A major "gotcha" of the Regulations.gov v4 API is that although date attributes returned in response JSON payloads are formatted in **UTC ISO-8601** (e.g. `2023-12-22T18:49:34Z`), the `filter[lastModifiedDate]` query parameter **only accepts US/Eastern Time** formatted as `YYYY-MM-DD HH:MM:SS`. 

Passing a UTC T/Z string to the filter returns a `400 Bad Request`. To solve this, `IngestionAgent` parses the UTC cursor, converts it to the `America/New_York` timezone, and formats it to the required style before making the next request.

### Dual-Pagination Continuation Signalling
The Regulations.gov API uses different ways to signal whether another page exists:
* Standard paging libraries might expect a populated `links.next` URL block.
* However, on some live Regulations.gov endpoints, `links.next` is returned as `null` or absent, and instead, the `meta.hasNextPage` boolean field is set to `true`.
* `IngestionAgent` robustly handles both indicators to prevent premature termination on live endpoints:
  ```python
  meta = page.get("meta") or {}
  has_next = meta.get("hasNextPage", False) or bool((page.get("links") or {}).get("next"))
  ```

---

## 3. Operational CLI Wrapper & Testing Parameters

Three operational CLI wrappers (`scripts/run_ingestion.py`, `scripts/inspect_docket.py`, `scripts/benchmark_ingestion.py`) are provided to run and benchmark the pipeline.

### The `max_comments` Parameter
The `--max-comments` option allows developers to set a ceiling on the number of comments fetched. This is useful for:
* Limiting API key quota consumption during testing.
* Running rapid integration checks.
* Forcing early termination conditions across page/window boundaries.

---

## 4. How to Run Ingestion & Benchmarking (PowerShell)

Ensure the virtual environment is active first:
```powershell
.venv\Scripts\Activate.ps1
```

### A. Tiny Docket Sanity Check
Runs a rapid sanity check of 1 comment to verify endpoint connectivity and schema writing:
```powershell
python scripts/run_ingestion.py --docket FDA-2013-S-0610 --max-comments 1
python scripts/inspect_docket.py --docket FDA-2013-S-0610
```

### B. Medium Docket Throughput Test
Validates pagination over multiple pages (exceeding the 250 record page limit) up to 500 comments:
```powershell
python scripts/run_ingestion.py --docket EPA-HQ-OAR-2021-0317 --max-comments 500
python scripts/inspect_docket.py --docket EPA-HQ-OAR-2021-0317
python scripts/benchmark_ingestion.py --docket EPA-HQ-OAR-2021-0317 --max-comments 1000
```

### C. Large Docket Date-Window Cursoring Test
Verifies that date-window shifting successfully crosses the 5,000 comment threshold without hitting 400 Bad Requests:
```powershell
python scripts/run_ingestion.py --docket FDA-2023-N-2177 --max-comments 5500
python scripts/inspect_docket.py --docket FDA-2023-N-2177
python scripts/benchmark_ingestion.py --docket FDA-2023-N-2177 --max-comments 1000
```

---

## 5. Known Limitations

* **No Comment Body in List Response**: The Regulations.gov `/comments` list endpoint retrieves only comment metadata (e.g. title, poster, dates). The raw, full comment body text is returned as `null` or `"not available"`.
* **Deferred Body/PDF Extraction**: Fetching the full comment text and extracting PDF attachments requires hitting individual comment detail endpoints (`/comments/{id}`). This is deferred to the downstream **`ParserAgent`** stage to avoid overwhelming list throughput.
* **Unavailable Retry Metrics**: Tenacity retries are managed internally and are currently printed as `"not available"` in benchmarks since the agent does not expose retry counters publicly.
* **Large Docket Precaution**: Very large dockets (e.g. >10,000 comments) should always be verified with a bounded `--max-comments` limit first to avoid unnecessary API quota utilization.
