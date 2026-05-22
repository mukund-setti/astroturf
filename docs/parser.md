# Silver Parsing Layer (`ParserAgent`)

The Silver Parsing Layer is the second stage of the AstroTurf medallion architecture. It is responsible for consuming raw, unstructured comment metadata from the bronze table (`data/bronze/raw_comments`), cleaning and normalizing the comment text, resolving title-only fallbacks, computing stable fingerprint hashes for exact duplicates, and storing the clean parsed state in a local silver Delta table (`data/silver/parsed_comments`).

This provides a high-quality, normalized starting point for downstream analytical agents (e.g. `EmbeddingAgent`, `ClusteringAgent`, `AttributionAgent`).

---

## 1. Scope & Capabilities

### What ParserAgent v1 Does:
1. **Deterministic Text Normalization:** Lowers case, trims surrounding whitespace, and collapses all interior contiguous whitespaces into single spaces.
2. **Text Source Resolution:** 
   - If a main comment body exists, it's used as the primary text (`text_source="comment_text"`, `parse_status="parsed"`).
   - If missing, it falls back to the submission title (`text_source="title_only"`, `parse_status="title_only"`).
   - If both are missing, it marks text as missing (`text_source="missing"`, `parse_status="missing_text"`).
3. **Fingerprinting & Hashing:** Generates stable SHA-256 hashes on normalized texts to assist subsequent deduplication and MinHash/LSH cluster candidate generation.
4. **Token Estimation:** Uses a lightweight character-based heuristic (`max(1, char_count // 4)`) to estimate token counts without paying high LLM model processing costs.
5. **Robust Row Isolation:** Wraps individual row processing in try-except isolation blocks to prevent a single malformed row from crashing a multi-thousand-row docket parser run.
6. **MLflow Metrics & Parity:** Records parsing distribution statistics (`parsed_count`, `title_only_count`, `missing_text_count`, `error_count`, `duration_seconds`) to MLflow and standard logging interfaces.

### What ParserAgent v1 Deliberately Does NOT Do (Deferred/Out of Scope):
* **No LLM Extractions:** Does not classify text, identify entities, or query generative models yet.
* **No OCR or Attachment Fetching:** Does not fetch or extract PDF/scanned attachments yet.
* **No Embeddings:** Embedding creation is deferred to the downstream `EmbeddingAgent` using Databricks Foundation models.
* **No Vector Clustering:** Grouping campaigns by cosine/LSH similarity is deferred to `ClusteringAgent`.

---

## 2. CLI Execution Instructions (PowerShell)

Ensure your virtual environment is active:
```powershell
.venv\Scripts\Activate.ps1
```

### A. Run Ingestion (Bronze Layer)
Ensure you have fetched comments into the bronze table first:
```powershell
python scripts/run_ingestion.py --docket EPA-HQ-OAR-2021-0317 --max-comments 100
```

### B. Run Parser (Silver Layer)
Run ParserAgent v1 on the ingested docket:
```powershell
python scripts/run_parser.py --docket EPA-HQ-OAR-2021-0317
```

### CLI Summary Output Example:
```
==================================================
PARSING SUMMARY
==================================================
Docket ID:          EPA-HQ-OAR-2021-0317
Comments Read:      100
Comments Written:   100
Successfully Parsed:98
Title Only Fallback:2
Missing Text Rows:  0
Parse Errors:       0
Duration:           0.42 seconds
Silver Path:        ./data/silver/parsed_comments
==================================================
```

---

## 3. Visualizing in the Streamlit Debug UI

Extend your local Streamlit developer dashboard to inspect and verify the silver layer parsed health:

1. **Launch the UI:**
   ```powershell
   streamlit run debug_ui/app.py
   ```
2. **Inspect Silver Panel:**
   - Under the sidebar inputs, verify that **Silver Table Path** points to `./data/silver/parsed_comments`.
   - Scroll down to the **“Silver Parsed Comments Panel”**.
   - Check the total parsed rows, average character lengths, and parse status distributions.
   - Expand the **“Top Duplicate Normalized Text Hashes”** table to immediately spot exact coordinate comment clusters.
   - Browse the **Parsed Comments Preview** table to confirm text lowercasing and trimming are correctly applied.
