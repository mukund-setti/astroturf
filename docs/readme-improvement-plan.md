# README & Demo Visual Improvement Plan

This document outlines our strategy to elevate the project's root `README.md` and draft visual layouts to impress the **Databricks Student Fellows selection committee**.

---

## 1. High-Impact README Outline

To represent Astroturf as a professional, production-grade Databricks project, we will expand the root `README.md` into the following structured sections:

### I. Cover Banner & Elevator Pitch
- A modern, stylized headline banner.
- A concise, high-fidelity paragraph:
  > "Astroturf is a multi-agent system on a Delta Medallion Lakehouse designed to detect coordinated public comment campaigns in federal rulemaking and trace their language into final rules. It solves the democratic problem where public commenting volume is dominated by mass, automated lobbying templates rather than organic public voices."
- Quick visual highlight cards: **Bronze/Silver/Gold durable tables**, **Databricks Foundation Model embeddings**, **MLflow tracking**, and **Delta MERGE idempotency**.

### II. Core Value Proposition: The "Wow" Contrasters
- A structured table comparing naive exact-duplicate detection (e.g. `GROUP BY text_hash`) vs. our deep learning semantic connected-components clustering:
  - Naive finds **16 literal copies** across **7 clusters**.
  - Semantic Connected Components finds **1,017 campaign comments** across **3 clusters** (capturing near-duplicates and close paraphrases).

### III. System Architecture & Lakehouse Layout
- A beautifully detailed walkthrough of our **6-agent medallion pipeline**:
  1. **IngestionAgent**: Multi-source API pulls (regulations.gov + FCC ECFS) → `bronze.raw_comments`
  2. **ParserAgent**: Substantive classification and metadata enrichment → `silver.parsed_comments`
  3. **EmbeddingAgent**: Vector generation using `databricks-bge-large-en` → `silver.comment_embeddings`
  4. **ClusteringAgent**: Cosine-similarity connected components → `gold.comment_clusters` & `gold.comment_cluster_memberships`
  5. **AttributionAgent**: Web search + registry lookups → `gold.campaign_attributions`
  6. **MigrationAgent**: Text-similarity extraction between clusters and final rule → `gold.rule_migrations`
- A dedicated **Why Databricks is Load-Bearing** section highlighting: Serverless Compute, Unity Catalog Governance, MLflow audit trails, Vector Search indices, and Workflows.

### IV. Setup & Reproducibility Guide
- Clear installation commands using `uv`.
- Environment variable definitions (`DATA_GOV_API_KEY`, `MLFLOW_TRACKING_URI`, etc.).
- Step-by-step commands to run individual agents or execute the local orchestrator.

### V. Reproducible Reviewer Demo Path (The 90-Second Walkthrough)
- Simple inline commands letting reviewers immediately generate evidence and quality receipts.
- Direct links to generated reports.

### VI. Evidentiary Validation Harness
- Explanations of our core quality metrics: Exact Duplicate Ratio, Near-Duplicate Ratio, Cluster Purity, and Representative Quality.
- Transparently documented limitations.

---

## 2. Architecture Diagram Recommendations

A high-fidelity technical README needs clear, visual architecture flowcharts. We recommend including two distinct diagrams:

### Diagram A: The Medallion Data Lineage (Durable Delta Tables)
A horizontal swimlane layout showing the flow of data through the medallion lakehouse layers:
- **Bronze (Raw comments)**: Wide, source-unified schema preserving raw payloads and source tagging.
- **Silver (Structured/Enriched)**: Separate but joined tables for parsed clean text, attachment metadata, and BGE vector embeddings.
- **Gold (Aggregated Insights)**: Highly optimized tables for comment clusters, memberships, source attributions, and final-rule text migrations.
- *Visual Style*: Glassmorphic cards with distinct colors for bronze (rust), silver (metallic blue), and gold (gold/yellow).

### Diagram B: Multi-Agent Choreography & Tool Integration
A circular or workflow DAG showing how the 6 agents coordinate:
- Ingestion → Parser → Embedder → Clusterer → Attribution (using Web Search tool + advocacy registry lookup) → Migration (comparing cluster medoid against federal registry final rule PDF text).
- Showing the Orchestrator as a lightweight coordinator, with Delta tables acting as the durable state machine between stages.
- *Visual Style*: Hexagonal nodes representing agents, solid arrows representing Delta table reads/writes, and dashed arrows representing MLflow tracking and Unity Catalog audit logging.

---

## 3. Recommended Screenshots & Plots for the UI Dashboard

To make the Streamlit/app dashboard immediately intuitive and premium for a non-technical reviewer, the UI should render the following screenshots, plots, and visual cards:

### A. The Docket Filing Velocity Spike
- *Plot Type*: A high-fidelity, dual-axis temporal area chart overlaying the total docket submission volume against the specific cluster's filing volume.
- *Visual Clue*: Coordinated astroturf campaigns exhibit a sharp, unnatural vertical spike (e.g. 500 filings in a single hour) compared to a smoother, distributed baseline of organic citizen comments.
- *Color Palette*: Curated HSL dark mode; background dark gray, docket volume light blue/teal, campaign spike vibrant purple/magenta area.

### B. Cosine Similarity Distribution Curve
- *Plot Type*: A kernel density estimate (KDE) or histogram showing the distribution of member comments' similarity scores relative to the cluster's medoid.
- *Visual Clue*: A tight peak near `0.95 - 0.98` indicates a highly organized campaign template where writers made minor personal modifications. A broader peak indicates looser coordination or theme-based organic writing.
- *Color Palette*: Sleek gradient curve fading from gold to orange.

### C. Campaign "Receipt" Card Side-by-Side Comparison
- *Visual Layout*: A split screen containing:
  - **Left Panel (Campaign Metadata)**: Size badge (e.g. `1,017 comments`), Coordinated Campaign Confidence Score (`0.982`), Exact-Match Ratio (`82.4%`), and primary filing peak.
  - **Right Panel (Boilerplate Saturation)**: Interactive bars showing the most common boilerplate sentence segments and how many comments they appear in.
- *Visual Style*: Clean glassmorphic panels with subtle micro-animations on hover.
