# Test Dockets for Development and Benchmarking

This document lists curated, verified real dockets from regulations.gov for testing IngestionAgent and other downstream agents locally. All counts were checked and validated against the regulations.gov v4 API live endpoint on **May 21, 2026**.

## 1. Tiny Docket (Sanity Checks)
*   **Docket ID:** `FDA-2013-S-0610`
*   **Agency:** `FDA` (Food and Drug Administration)
*   **Expected Comments:** `1`
*   **Usefulness:** Perfect for immediate, zero-latency end-to-end integration tests, schema sync validation, and basic dry runs. Ingestion takes less than 1 second.
*   **Date Checked:** 2026-05-21

## 2. Medium Docket (Pagination & Throughput Tests)
*   **Docket ID:** `EPA-HQ-OAR-2021-0317`
*   **Agency:** `EPA` (Environmental Protection Agency)
*   **Expected Comments:** `3,578`
*   **Usefulness:** Outstanding medium docket for testing pagination beyond a single page (exceeds the 250 record page size), exercising early stopping limits (like `--max-comments 500`), and measuring local delta-rs write throughput.
*   **Date Checked:** 2026-05-21

## 3. Large Docket (Date-Window Cursoring / >5,000 Comments)
*   **Docket ID:** `FDA-2023-N-2177`
*   **Agency:** `FDA` (Food and Drug Administration)
*   **Expected Comments:** `6,708`
*   **Usefulness:** Crucial for testing the `IngestionAgent`'s advanced date-window cursoring capability. Since the regulations.gov v4 API caps standard pagination at 5,000 records, this docket exercises the date-range advancing logic to recover all 6,708 comments seamlessly.
*   **Date Checked:** 2026-05-21
