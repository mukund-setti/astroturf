# Databricks Unity Catalog promotion runbook

This runbook is the operator path for promoting a curated sample of the local
delta-rs lakehouse into Unity Catalog Delta tables on Databricks. It implements
the "Minimum credible Databricks demo path" from
[integration.md](integration.md):

```text
local Delta tables -> Parquet snapshots -> astroturf.bronze.raw_imports volume
-> Unity Catalog Delta tables -> EmbeddingAgent / ClusteringAgent on Databricks
```

The sample is intentionally minimal: all `EPA-HQ-OAR-2021-0317` rows plus an
optional small `CFPB-2016-0025` slice. It is the same data the Student Fellows
demo needs to show governed tables, Foundation Model embeddings, and a visible
cluster — and nothing more.

## Sample composition

| Layer  | Unity Catalog table                       | EPA rows           | Filter |
| ------ | ----------------------------------------- | ------------------ | ------ |
| Bronze | `astroturf.bronze.raw_comments`           | All EPA rows       | `docket_id = 'EPA-HQ-OAR-2021-0317'` |
| Silver | `astroturf.silver.parsed_comments`        | All EPA rows       | `docket_id = 'EPA-HQ-OAR-2021-0317'` |
| Silver | `astroturf.silver.comment_details`        | All EPA rows       | `docket_id = 'EPA-HQ-OAR-2021-0317'` |
| Silver | `astroturf.silver.comment_attachments`    | All EPA rows       | `docket_id = 'EPA-HQ-OAR-2021-0317'` |
| Silver | `astroturf.silver.comment_embeddings`     | EPA + Databricks model | `docket_id = ...` AND `embedding_model = 'databricks-bge-large-en'` |
| Gold   | `astroturf.gold.comment_clusters`         | EPA + Databricks model | same |
| Gold   | `astroturf.gold.comment_cluster_memberships` | EPA + Databricks model | same |

When `--include-cfpb-sample` is passed, the same set of tables also includes
`CFPB-2016-0025` rows restricted to the `comment_id` values that already exist
in `silver.parsed_comments` locally (the 250 curated CFPB comments). Everything
downstream of bronze (silver, gold) is consistent with that bronze slice.

The Parquet payload uses the Pydantic-derived Arrow schemas under
[shared/schemas/](../../shared/schemas/) so it matches the Delta table column
definitions below.

## 1. Run the export script

Run from the repository root.

```bash
# EPA-only sample (default).
uv run python scripts/promote_sample_to_parquet.py --overwrite

# EPA + small CFPB slice.
uv run python scripts/promote_sample_to_parquet.py \
    --overwrite \
    --include-cfpb-sample
```

Useful flags:

| Flag                     | Default                                  | Purpose |
| ------------------------ | ---------------------------------------- | ------- |
| `--data-dir`             | `./data`                                 | Root of the local lakehouse. |
| `--output-dir`           | `./data/exports/uc_sample`               | Per-table Parquet output directory. |
| `--embedding-model`      | `databricks-bge-large-en`                | `embedding_model` filter for the embedding / cluster tables. |
| `--include-cfpb-sample`  | off                                      | Also include the curated CFPB slice. |
| `--overwrite`            | off                                      | Replace existing per-table exports. Default refuses to overwrite. |
| `--log-level`            | `INFO`                                   | Python log level. |

The script is idempotent: rerunning with the same flags reproduces the same
Parquet payload, and it refuses to clobber an existing export without
`--overwrite`.

Output layout (one Parquet file per table, snappy-compressed):

```text
data/exports/uc_sample/
  bronze.raw_comments/part-000.parquet
  silver.parsed_comments/part-000.parquet
  silver.comment_details/part-000.parquet
  silver.comment_attachments/part-000.parquet
  silver.comment_embeddings/part-000.parquet
  gold.comment_clusters/part-000.parquet
  gold.comment_cluster_memberships/part-000.parquet
```

Inspect the export summary printed at the end — it lists per-table row counts
and the full output path for each file.

## 2. Provision the Unity Catalog volume

In the Databricks SQL Editor (or a notebook), as a workspace user with
`CREATE CATALOG` / `CREATE SCHEMA` / `CREATE VOLUME` privileges:

```sql
CREATE CATALOG IF NOT EXISTS astroturf;
CREATE SCHEMA  IF NOT EXISTS astroturf.bronze;
CREATE SCHEMA  IF NOT EXISTS astroturf.silver;
CREATE SCHEMA  IF NOT EXISTS astroturf.gold;
CREATE SCHEMA  IF NOT EXISTS astroturf.demo;

CREATE VOLUME IF NOT EXISTS astroturf.bronze.raw_imports;
CREATE VOLUME IF NOT EXISTS astroturf.silver.attachments;
CREATE VOLUME IF NOT EXISTS astroturf.demo.exports;
```

## 3. Upload Parquet files to the volume

Pick one path:

**Databricks CLI (recommended):**

```bash
# One-time auth: databricks configure --token
databricks fs mkdir dbfs:/Volumes/astroturf/bronze/raw_imports/uc_sample/

for table in \
    bronze.raw_comments \
    silver.parsed_comments \
    silver.comment_details \
    silver.comment_attachments \
    silver.comment_embeddings \
    gold.comment_clusters \
    gold.comment_cluster_memberships; do
  databricks fs cp \
      "./data/exports/uc_sample/${table}/part-000.parquet" \
      "dbfs:/Volumes/astroturf/bronze/raw_imports/uc_sample/${table}/part-000.parquet" \
      --overwrite
done
```

**Workspace UI:**

1. Open Catalog -> `astroturf.bronze.raw_imports` -> Upload.
2. Create a folder `uc_sample/` then one subfolder per table name above.
3. Upload the `part-000.parquet` from the matching local directory.

After uploading, the staging path for each table is:

```text
/Volumes/astroturf/bronze/raw_imports/uc_sample/<table_name>/part-000.parquet
```

## 4. Create Unity Catalog Delta tables

Run each block in the Databricks SQL Editor against the `astroturf` catalog.
Tables are created `OR REPLACE` so the runbook is idempotent across reruns of
the export. Column types match the Pydantic-derived schemas under
[shared/schemas/](../../shared/schemas/).

### 4.1 `astroturf.bronze.raw_comments`

```sql
CREATE OR REPLACE TABLE astroturf.bronze.raw_comments (
    comment_id              STRING,
    docket_id               STRING,
    document_type           STRING,
    title                   STRING,
    posted_date             TIMESTAMP,
    received_date           TIMESTAMP,
    last_modified_date      TIMESTAMP,
    comment_text            STRING,
    submitter_name          STRING,
    first_name              STRING,
    last_name               STRING,
    organization            STRING,
    city                    STRING,
    state_province_region   STRING,
    country                 STRING,
    agency_id               STRING,
    has_attachments         BOOLEAN,
    attributes_json         STRING,
    ingested_at             TIMESTAMP
) USING DELTA;

COPY INTO astroturf.bronze.raw_comments
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/bronze.raw_comments/'
FILEFORMAT = PARQUET
COPY_OPTIONS ('mergeSchema' = 'false');
```

### 4.2 `astroturf.silver.parsed_comments`

```sql
CREATE OR REPLACE TABLE astroturf.silver.parsed_comments (
    comment_id              STRING,
    docket_id               STRING,
    title                   STRING,
    posted_date             TIMESTAMP,
    last_modified_date      TIMESTAMP,
    received_date           TIMESTAMP,
    source_system_version   STRING,
    parser_version          STRING,
    text_source             STRING,
    raw_text                STRING,
    normalized_text         STRING,
    normalized_text_hash    STRING,
    token_estimate          BIGINT,
    char_count              BIGINT,
    has_attachments         BOOLEAN,
    attachment_count        BIGINT,
    parse_status            STRING,
    parse_error             STRING,
    parsed_at               TIMESTAMP
) USING DELTA;

COPY INTO astroturf.silver.parsed_comments
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/silver.parsed_comments/'
FILEFORMAT = PARQUET;
```

### 4.3 `astroturf.silver.comment_details`

```sql
CREATE OR REPLACE TABLE astroturf.silver.comment_details (
    comment_id                STRING,
    docket_id                 STRING,
    enrichment_status         STRING,
    enrichment_error          STRING,
    raw_detail_json           STRING,
    extracted_at              TIMESTAMP,
    api_version               STRING,
    has_substantive_comment   BOOLEAN,
    is_cover_note             BOOLEAN
) USING DELTA;

COPY INTO astroturf.silver.comment_details
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/silver.comment_details/'
FILEFORMAT = PARQUET;
```

### 4.4 `astroturf.silver.comment_attachments`

```sql
CREATE OR REPLACE TABLE astroturf.silver.comment_attachments (
    attachment_id         STRING,
    comment_id            STRING,
    docket_id             STRING,
    file_name             STRING,
    file_url              STRING,
    format                STRING,
    size_bytes            BIGINT,
    detected_at           TIMESTAMP,
    download_status       STRING,
    extracted_text_path   STRING,
    local_path            STRING,
    checksum_sha256       STRING,
    downloaded_at         TIMESTAMP,
    download_error        STRING,
    size_bytes_actual     BIGINT
) USING DELTA;

COPY INTO astroturf.silver.comment_attachments
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/silver.comment_attachments/'
FILEFORMAT = PARQUET;
```

### 4.5 `astroturf.silver.comment_embeddings`

```sql
CREATE OR REPLACE TABLE astroturf.silver.comment_embeddings (
    comment_id          STRING,
    docket_id           STRING,
    embedding_model     STRING,
    embedding_dim       BIGINT,
    text_hash           STRING,
    text_source         STRING,
    embedding_vector    ARRAY<FLOAT>,
    embedded_at         TIMESTAMP,
    backend             STRING
) USING DELTA;

COPY INTO astroturf.silver.comment_embeddings
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/silver.comment_embeddings/'
FILEFORMAT = PARQUET;
```

The compound primary key is `(comment_id, embedding_model)` (see ADR-0005). The
Vector Search index in [integration.md](integration.md)
slices this table to a single `embedding_model` before indexing.

### 4.6 `astroturf.gold.comment_clusters`

```sql
CREATE OR REPLACE TABLE astroturf.gold.comment_clusters (
    cluster_id                  STRING,
    clustering_run_id           STRING,
    docket_id                   STRING,
    embedding_model             STRING,
    embedding_backend           STRING,
    clustering_version          STRING,
    similarity_threshold        DOUBLE,
    candidate_count             BIGINT,
    cluster_size                BIGINT,
    representative_comment_id   STRING,
    representative_text_hash    STRING,
    mean_similarity             DOUBLE,
    min_similarity              DOUBLE,
    max_similarity              DOUBLE,
    created_at                  TIMESTAMP,
    updated_at                  TIMESTAMP
) USING DELTA;

COPY INTO astroturf.gold.comment_clusters
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/gold.comment_clusters/'
FILEFORMAT = PARQUET;
```

### 4.7 `astroturf.gold.comment_cluster_memberships`

```sql
CREATE OR REPLACE TABLE astroturf.gold.comment_cluster_memberships (
    cluster_id                     STRING,
    comment_id                     STRING,
    clustering_run_id              STRING,
    docket_id                      STRING,
    embedding_model                STRING,
    embedding_backend              STRING,
    clustering_version             STRING,
    similarity_threshold           DOUBLE,
    text_hash                      STRING,
    text_source                    STRING,
    similarity_to_representative   DOUBLE,
    membership_rank                BIGINT,
    created_at                     TIMESTAMP,
    updated_at                     TIMESTAMP
) USING DELTA;

COPY INTO astroturf.gold.comment_cluster_memberships
FROM '/Volumes/astroturf/bronze/raw_imports/uc_sample/gold.comment_cluster_memberships/'
FILEFORMAT = PARQUET;
```

## 5. Verification queries

Run each query and confirm the row count matches the export summary printed by
`scripts/promote_sample_to_parquet.py`.

```sql
-- Row counts per Unity Catalog table.
SELECT 'bronze.raw_comments'                     AS table_name, COUNT(*) AS row_count FROM astroturf.bronze.raw_comments
UNION ALL SELECT 'silver.parsed_comments',                    COUNT(*) FROM astroturf.silver.parsed_comments
UNION ALL SELECT 'silver.comment_details',                    COUNT(*) FROM astroturf.silver.comment_details
UNION ALL SELECT 'silver.comment_attachments',                COUNT(*) FROM astroturf.silver.comment_attachments
UNION ALL SELECT 'silver.comment_embeddings',                 COUNT(*) FROM astroturf.silver.comment_embeddings
UNION ALL SELECT 'gold.comment_clusters',                     COUNT(*) FROM astroturf.gold.comment_clusters
UNION ALL SELECT 'gold.comment_cluster_memberships',          COUNT(*) FROM astroturf.gold.comment_cluster_memberships;

-- Docket scope sanity check.
SELECT docket_id, COUNT(*) AS row_count
FROM astroturf.bronze.raw_comments
GROUP BY docket_id
ORDER BY row_count DESC;

-- Embeddings should be a single model + dimension after the EPA-only export.
SELECT embedding_model, embedding_dim, COUNT(*) AS row_count
FROM astroturf.silver.comment_embeddings
GROUP BY embedding_model, embedding_dim;

-- Cluster + membership scope (one docket, one model).
SELECT docket_id, embedding_model, similarity_threshold, COUNT(*) AS clusters
FROM astroturf.gold.comment_clusters
GROUP BY docket_id, embedding_model, similarity_threshold
ORDER BY clusters DESC;

-- Eyeball one cluster end-to-end.
WITH top_cluster AS (
    SELECT cluster_id
    FROM astroturf.gold.comment_clusters
    ORDER BY cluster_size DESC, cluster_id
    LIMIT 1
)
SELECT m.cluster_id,
       m.comment_id,
       m.similarity_to_representative,
       p.title,
       LEFT(p.normalized_text, 240) AS text_preview
FROM astroturf.gold.comment_cluster_memberships m
JOIN top_cluster t ON t.cluster_id = m.cluster_id
LEFT JOIN astroturf.silver.parsed_comments p
       ON p.comment_id = m.comment_id
ORDER BY m.membership_rank;
```

## 6. Screenshot checklist (Student Fellows evidence)

Capture these in order — each artifact ties back to the
"Evidence checklist" section of
[integration.md](integration.md):

1. **Catalog overview.** Catalog Explorer showing `astroturf` with the
   `bronze`, `silver`, `gold`, and `demo` schemas expanded.
2. **Volume contents.** Catalog Explorer showing
   `astroturf.bronze.raw_imports/uc_sample/` with the seven per-table
   subdirectories, each holding `part-000.parquet`.
3. **Table preview — bronze.** `astroturf.bronze.raw_comments` with the
   docket-id breakdown and the first EPA rows visible.
4. **Table preview — silver.** `astroturf.silver.parsed_comments` showing
   `text_source = comment_text`, non-empty `normalized_text`, and a populated
   `normalized_text_hash`.
5. **Table preview — embeddings.** `astroturf.silver.comment_embeddings` showing
   `embedding_model = databricks-bge-large-en`, `embedding_dim = 1024`,
   `backend = databricks_foundation_model`, and the `embedding_vector` column
   header.
6. **Table preview — gold.** `astroturf.gold.comment_clusters` ordered by
   `cluster_size DESC`, plus one expanded row from
   `astroturf.gold.comment_cluster_memberships` showing the same `cluster_id`
   and the `similarity_to_representative` column.
7. **Verification SQL.** A run of the row-count UNION ALL query from section 5,
   side-by-side with the export summary from `promote_sample_to_parquet.py`,
   showing matching row counts per table.
8. **Sample cluster join.** The "Eyeball one cluster" query from section 5
   showing the representative title, similarity values, and the truncated
   member text for the top cluster.

Save each screenshot under
`data/exports/screenshots/uc-promotion/<NN>-<short-name>.png` (gitignored).
This keeps the evidence ordered, named, and ready to drop into the Student
Fellows submission.
