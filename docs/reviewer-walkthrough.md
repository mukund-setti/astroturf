# 90-Second Reviewer Walkthrough Guide

This runbook guides you through booting, inspecting, and verifying the Astroturf coordination analysis showcase locally in under 90 seconds.

---

## Step 1: Boot the Public Next.js Editorial UI (10 Seconds)

To verify the public landing page findings, exact-hash lift comparisons, and the interactive campaign detail inspector:

1. Open a PowerShell terminal and navigate to the `ui/` directory:
   ```powershell
   cd ui
   ```
2. Install the lightweight frontend dependencies:
   ```powershell
   npm install
   ```
3. Run the Next.js development server:
   ```powershell
   npm run dev
   ```
4. Open your browser and navigate to **[http://localhost:3000](http://localhost:3000)**.

> [!NOTE]
> On Windows, `npm run dev` uses Next's webpack dev server for stability. The Turbopack dev server is available as `npm run dev:turbo`, but it is not the recommended reviewer path.

> [!NOTE]
> **Data Mode**: Set `ASTROTURF_DATA_MODE=mock` for fully offline review, `ASTROTURF_DATA_MODE=live` to force Databricks SQL, or `ASTROTURF_DATA_MODE=auto` to try Databricks SQL and fall back to artifacts when credentials are absent. The UI shows a subtle label: `Live Databricks SQL mode`, `Offline benchmark artifact mode`, or `Auto mode: using fallback artifacts`.

For the live Databricks validation details, including run IDs and final row counts, see [docs/live-databricks-validation.md](docs/live-databricks-validation.md).

---

## Step 2: The 15-Second Landing Page Visual Check (15 Seconds)

Once the landing page loads, observe how the system immediately conveys the
core finding and avoids empty future-topic dashboards:

1. **The Hero Headline**: Look at the serif headline:
   > *"On one historic FCC Net Neutrality rulemaking, **1,002** nearly identical comments were submitted in **2** days."*
2. **The Dominant Metric**: Observe the comparison banner:
   > **Exact Hashing Surfaced: 16 comments.**
   > **Semantic Clustering Surfaced: 1,002 comments.**
   > **62x Campaign Detection Lift.**
3. **MVP Coverage**: Open the topic or agency browse pages. Primary browsing
   should show only FCC analyzed coverage and EPA baseline-only coverage, plus
   an **Analyze a docket** path for new rulemakings.
4. **Why Local Fails**: Inspect the **100K Memory Wall** card. See how a local single-node connected-components run crashes due to the **40 GB contiguous RAM requirement** for 10 Billion pairwise edges.
5. **Why Databricks Matters**: Observe how each physical data bottleneck is mapped to a robust Databricks solution (Delta Lake, Foundation Model serving, Unity Catalog, and Vector Search).

---

## Step 3: Drill Down Into Campaign Evidence (30 Seconds)

Let's drill down into the evidentiary proof:

1. Scroll to the **Campaign Grid** and click on the primary featured card showing **1,002 Comments**.
2. This opens the dynamic route: `/campaign/96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c`.
3. **Evidentiary Packet Inspection**:
   * **Boilerplate Repeated Phrases**: Notice that while individual comments were customized, phrases like *"That’s not the kind of Internet we want to pass on to future generations..."* appear in **35% of all comments** in this cluster.
   * **Timeline Filing Velocity**: Observe the extreme spike chart where **958 comments** were filed in a single hour bucket—a hallmark of coordinated automated submission routines.
   * **"How the Campaign Hides Itself"**: Review the stack of three sample comments side-by-side. See how different citizens added custom prefaces and personal paragraphs while maintaining the **identical core template** and **98%+ semantic similarity**, which completely broke naive exact-string hash filters.
   * **Likely Campaign Origin & Language Migration Check**: Scroll further down the campaign page. If the AttributionAgent and MigrationAgent have run, you will see a *candidate source*, an evidence excerpt, a confidence label, and a phrase-level overlap with a final-rule fixture. If they have not yet run, the panels show "Not yet analyzed" with the exact CLI command to run. These are **evidence packets**, not accusations — see [ADR-0015](decisions/0015-attribution-and-migration-agents.md) and [`docs/attribution-and-migration-methodology.md`](attribution-and-migration-methodology.md).

---

## Step 4: Boot the Developer Diagnostic Streamlit UI (20 Seconds)

To verify the internal engineering diagnostic panel:

1. Open a new PowerShell terminal at the root of the project.
2. Activate the pre-configured virtual environment and run the Streamlit app:
   ```powershell
   .uv-test-venv\Scripts\activate
   streamlit run debug_ui/app.py
   ```
3. Open your browser and navigate to **[http://localhost:8501](http://localhost:8501)**.
4. **Developer Navigation**:
   * Inspect the Bronze, Silver, and Gold Delta tables.
   * Examine the **Null Count & Schema** diagnostics tab.
   * Review the **Records Per Day** bar chart showing the live temporal spike.
   * Observe the **Gold Comment Clusters** tab showing a direct comparison between the exact-hash baseline and the semantic grouping.

---

## Step 5: Verify the Quality Assurance Receipts (15 Seconds)

We maintain complete transparency in our research. You can inspect the mathematically formal evidence receipts generated during our runs:

1. Open [artifacts/demo/example_run/demo_quality_evaluation_17-108.md](file:///c:/Users/mukun/astroturf/artifacts/demo/example_run/demo_quality_evaluation_17-108.md) in your editor.
2. Review our strict definitions for **Exact Duplicate Ratio**, **Near-Duplicate Ratio**, **Cluster Purity**, and **Representative-Comment Quality**, along with their honestly documented limitations and known failure modes.
3. Open [artifacts/benchmark/benchmark_report.md](file:///c:/Users/mukun/astroturf/artifacts/benchmark/benchmark_report.md) to inspect the raw performance runs and complexity profiling tables.

---

## MVP Coverage Policy

The public UI intentionally hides or de-emphasizes future sectors until they
have evidence or a clear action path.

- **Analyzed**: FCC `17-108` remains visible with semantic clusters and live
  Databricks validation.
- **Baseline only**: EPA `EPA-HQ-OAR-2021-0317` remains visible with exact-hash
  duplicate metrics and an explicit semantic clustering next step.
- **Ingestion ready**: CFPB, FTC, SEC, AI regulation, privacy, and other
  unsupported areas route to `/analyze` to generate config and commands.
- **Hidden**: Future topics with no docket and no action path are excluded from
  primary navigation.

A reviewer should not find a primary page that says, in effect, "nothing here."
