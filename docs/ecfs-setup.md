# ECFS ingestion setup

Phase 1 of the FCC ECFS work plugs the public Electronic Comment Filing System
API at `publicapi.fcc.gov/ecfs` into the existing `IngestionAgent` and the
unified bronze schema (ADR-0012). This page covers the operator-facing setup.

## API key — no separate registration required

The FCC ECFS public API is fronted by the same api.data.gov gateway as
regulations.gov. The **same key works for both sources**. If you already have
`REGULATIONS_GOV_API_KEY` set (the legacy name), nothing new is required for
ECFS access — the IngestionAgent reads the key under the canonical
`DATA_GOV_API_KEY` name and falls back to the legacy name with a deprecation
warning.

If you don't have a key yet:

1. Request one at <https://api.data.gov/signup/>. Free, instantaneous.
2. Add it to `.env` at the repo root:

   ```env
   DATA_GOV_API_KEY=YOUR_KEY_HERE
   ```

3. The IngestionAgent and ParserAgent both resolve the key via
   `shared/api_keys.py::resolve_data_gov_api_key`. No code changes needed
   beyond `.env`.

ECFS authenticates via the `api_key=...` query-string parameter (not a header).
Regulations.gov v4 uses the `X-Api-Key` header. Both use the same key value;
only the wire format differs. The clients handle this internally.

## Running an ECFS ingestion

```powershell
python -m scripts.run_ingestion `
    --source ecfs `
    --docket 17-108 `
    --start-date 2017-08-28 `
    --end-date 2017-08-30 `
    --max-comments 5000 `
    --bronze-path ./data/bronze/raw_comments
```

- `--docket` is the ECFS proceeding name, **without** any prefix
  (e.g. `17-108`, not `WC-17-108`).
- `--start-date` / `--end-date` are inclusive bounds on `date_received`.
- `--max-comments` is a hard ceiling enforced client-side; useful for the
  Phase 1 5K validation slice.
- `--ecfs-page-size` (default 100) and `--ecfs-rate-limit-qps` (default 1.0)
  control pagination and the client-side rate limit.

The regulations.gov flow is unchanged when `--source` is omitted.

## Observed API quirks (from gate-1 exploration)

These quirks were discovered against the live API during gate-1 exploration
and informed the client design (`agents/ingestion/sources/ecfs.py`).

### 1. Date filtering only works through Lucene `q=`

Intuitive query parameters like `received_from`, `date_received_from`,
`date_received=[FROM TO]` either return HTTP 400 or — worse — return HTTP 200
with *unfiltered* results, silently ignoring the filter. The only working
syntax is the Elasticsearch `q=` Lucene passthrough:

```
q=date_received:[2017-08-28T00:00:00Z TO 2017-08-30T23:59:59Z]
```

The client emits this form automatically when `--start-date` and/or
`--end-date` are supplied.

### 2. Offset > 9999 silently fails

The underlying Elasticsearch index enforces `index.max_result_window=10000`.
Once `offset + limit > 10000`, the API returns **HTTP 200** with a
plain-text body:

```
Parameters incorrectly formatted. For more information, please refer to the
API documentation page (https://www.fcc.gov/ecfs/help/public_api)
```

This is a **Phase 2 blocker** for any docket / window with more than ~10K
filings. Phase 1's 5K slice is comfortably below the ceiling. The client
detects the failure mode and raises `ECFSOffsetCeilingError`; the resolution
is date-window cursoring on `date_received` (analogous to the regulations.gov
`lastModifiedDate` cursoring that already exists), which lands in Phase 2.

### 3. Variable `submissiontype` shape

Three observed shapes for the same field:

```jsonc
{"description": "...", "short": "...", "id": 7,  "abbreviation": "CO"}
{"description": "...", "short": "...", "id": 88, "type": "PN", "id_submission_type": 88}
{"description": "...", "short": "...", "id": 29, "abbreviation": "LT"}
```

Only `description` and `id` are reliable across all observed records. The
client surfaces these two as `document_type` and `ecfs_submission_type_id`;
the rest survives via `attributes_json`.

### 4. Multi-valued `proceedings` array

One filing can be filed to multiple proceedings. The bronze row's `docket_id`
is pinned to **the docket we queried**, not `proceedings[0].name`. The full
`proceedings` array survives in `attributes_json`.

### 5. Multi-valued `filers` array

One filing can have multiple filers. The bronze row's `submitter_name` is the
non-empty filer names joined with `"; "`. The full array survives in
`attributes_json`.

### 6. Three date string formats coexist

Observed:

- `2017-08-28T13:00:06.000Z` — UTC with milliseconds, the common case.
- `2017-05-12T04:00:00.000-04:00` — Eastern offset, mostly in older
  proceeding metadata.
- `2017-04-27T13:20:07` — seconds-only, no timezone. Treated as UTC.

`agents/ingestion/sources/ecfs.py::_parse_ecfs_dt` normalizes all three to
UTC-aware datetimes.

### 7. `viewingstatus.id` type is unstable

Sometimes `10` (int), sometimes `"10"` (string), in records seconds apart.
We don't promote this field to a column, so the inconsistency is contained
in `attributes_json`.

### 8. Internal Elasticsearch metadata leaks

`_index`, `@timestamp`, `@version` show up on every record. They're stripped
from `attributes_json` before persistence — they're not stable contract.

### 9. `express_comment` is `0`/`1`, not a bool

Coerced to bool on the way into the bronze `ecfs_express_comment` column.

### 10. No rate-limit headers, but api.data.gov quota applies

api.data.gov enforces ~1000 req/hr per registered key. The client defaults
to 1 req/s (well below the gateway limit) and retries 429 and 5xx with
exponential backoff via `tenacity`. Override with `--ecfs-rate-limit-qps`.

## Phase 1 validation methodology

The Phase 1 success criterion is the known-answer benchmark: confirm that the
"Broadband for America" template phrase

> The unprecedented regulatory power the Obama Administration imposed on the
> internet is smothering innovation, damaging the American economy and
> obstructing job creation.

surfaces in the largest cluster's representative comment after running the
full pipeline against a 5K slice of docket `17-108` from the BFA campaign
window (late August 2017).

There are two possible outcomes:

1. **Template found in the 5K slice.** End-to-end pass; record the cluster
   ID, size, and representative comment in the run report.
2. **Template absent from the 5K slice.** Could mean either sampling
   variance (the BFA campaign comments are present in 17-108 but didn't fall
   into the 5K window we pulled) or data absence (the comments are absent
   from the API entirely). Distinguish with a targeted diagnostic query:

   ```
   q=text_data:"unprecedented regulatory power" AND proceedings.name:"17-108"
   ```

   - If the diagnostic returns hits, the 5K slice missed the template by
     sampling variance — note in the run report and consider expanding the
     window in Phase 2.
   - If the diagnostic returns zero hits, the BFA campaign comments are not
     in the public API and we need a different known-answer benchmark.

The diagnostic query is **not** part of the regular ingestion path — it's
a one-off investigative tool when validation is ambiguous.
