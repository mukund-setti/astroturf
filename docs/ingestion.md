# Comment Ingestion and Local Debug UI

This document provides instructions on how to ingest comments locally and run the local developer debug UI.

## 1. Local Ingestion Setup

To ingest public comments from Regulations.gov into the local Bronze Delta table, use `scripts/run_ingestion.py`.

### Prerequisites

Ensure you have a `.env` file in the root directory containing your API key:
```env
REGULATIONS_GOV_API_KEY=your_api_key_here
```

### Ingestion Commands

Use `uv run` to run the ingestion script with specific docket IDs:

#### A. Tiny Docket (Sanity Checks)
*   **Docket ID:** `FDA-2013-S-0610`
*   **Expected Comments:** 1
*   **Command:**
    ```powershell
    uv run python scripts/run_ingestion.py --docket FDA-2013-S-0610
    ```

#### B. Medium Docket (Pagination & Throughput Tests)
*   **Docket ID:** `EPA-HQ-OAR-2021-0317`
*   **Expected Comments:** ~3,578 (We limit to 500 here for testing early stopping)
*   **Command:**
    ```powershell
    uv run python scripts/run_ingestion.py --docket EPA-HQ-OAR-2021-0317 --max-comments 500
    ```

#### C. Large Docket (Date-Window Cursoring / >5,000 Comments)
*   **Docket ID:** `FDA-2023-N-2177`
*   **Expected Comments:** ~6,708
*   **Command:**
    ```powershell
    uv run python scripts/run_ingestion.py --docket FDA-2023-N-2177
    ```

---

## 2. Local Debug UI

The local debug UI is built with Streamlit. It allows developers to visually inspect ingestion results, check table health, review date ranges, preview comments, search/filter, view raw metadata JSON, and analyze exact duplicate text comments.

### Installation

Add Streamlit as a dependency to your local virtual environment:
```powershell
uv add streamlit
```

### Run Command

To launch the Streamlit debug UI, run the following command in PowerShell:
```powershell
uv run streamlit run debug_ui/app.py
```

### Key UI Features

1.  **Sidebar Configuration:** Select/change the bronze Delta table path, choose a `docket_id` from the dynamically populated dropdown (or type in a manual fallback), and limit the preview rows.
2.  **Overview Panel:** Provides immediate visual diagnostics of row counts, date ranges, attachment counts, and size on disk.
3.  **Data Preview:** Shows a searchable/filterable table populated dynamically based on existing schema fields, with a text filtering option.
4.  **JSON Metadata Inspector:** Inspect the raw metadata JSON or attributes tree for any selected comment.
5.  **White-Box Diagnostics:** Review schema null rates, look up records per day in a bar chart, check for any duplicate `comment_id` records, and expand raw records.
6.  **Duplicate Text Inspection:** Automatically normalizes, hashes, and highlights exact duplicate comments.
