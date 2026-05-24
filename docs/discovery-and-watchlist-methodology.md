# Discovery and Watchlist Methodology

This document outlines the mathematics, algorithms, and logical rules powering the Astroturf Autopilot discovery, classification, and prioritization engine.

---

## 1. Prioritization Engine Architecture

To optimize compute costs on Databricks Serverless, Astroturf cannot run high-scale semantic clustering on every rulemaking docket published by federal agencies. We use a multi-factored prioritization formula to rank newly discovered dockets and run analysis runs only on high-impact targets.

### The Prioritization Formula

The priority score $P$ is bounded in $[0.0, 100.0]$ and is computed deterministically as:

$$P = \min\left(100.0, \, S_{\text{scale}} + S_{\text{recency}} + S_{\text{watchlist}} + S_{\text{agency}}\right)$$

#### A. Estimated Scale Score ($S_{\text{scale}}$)
Large-scale public comment campaigns usually contain more than 10,000 comments. We reward dockets with larger scale estimates up to a maximum score of $25.0$:

$$S_{\text{scale}} = 25.0 \times \min\left(1.0, \, \frac{N_{\text{est}}}{50000}\right)$$

where $N_{\text{est}}$ is the estimated comment count. A docket with 50,000 or more comments achieves the maximum scale score of $25.0$.

#### B. Recency & Temporal Decay Score ($S_{\text{recency}}$)
Rulemakings with active public participation are prioritized over historically closed or stalled dockets. We apply an exponential time decay algorithm with a half-life of 30 days:

$$S_{\text{recency}} = 25.0 \times e^{-\frac{\Delta t}{30.0}}$$

where $\Delta t$ is the number of days elapsed since `last_comment_date`. If comments were submitted today ($\Delta t = 0$), the docket receives the full $25.0$ points. If the last comment was submitted 30 days ago, the score decays to $25.0 \times e^{-1} \approx 9.2$ points.

#### C. User Interest & Watchlist Score ($S_{\text{watchlist}}$)
Active user engagement is the strongest signal for analysis. We reward user votes and active watchlist matches up to a maximum score of $45.0$:

$$S_{\text{watchlist}} = 30.0 \times \min\left(1.0, \, \frac{V_{\text{user}}}{10}\right) + B_{\text{match}}$$

where:
- $V_{\text{user}}$ is the `user_requested_count` (number of times users requested analysis on this docket).
- $B_{\text{match}}$ is a $15.0$ point bonus added if the docket matches an active keyword, topic, or agency in the user's **Watchlist**.

#### D. Core Agency Priority Bonus ($S_{\text{agency}}$)
rule dockets from our core calibrated agencies (FCC, EPA, CFPB, FTC) receive an automatic priority bonus of $5.0$:

$$S_{\text{agency}} = \begin{cases} 5.0 & \text{if agency\_id} \in \{\text{FCC, EPA, CFPB, FTC}\} \\ 0.0 & \text{otherwise} \end{cases}$$

---

## 2. Decoupled Topic Classification

Discovered dockets must be categorized into policy sectors. Astroturf uses a deterministic rules-based keyword classifier (`scripts/classify_dockets.py`) to process titles and summaries.

### Classification Matrix & Tag Extraction

| Topic ID | Target Keywords | Example Extracted Tags |
| :--- | :--- | :--- |
| `oil_and_gas` | `methane`, `climate`, `emissions`, `greenhouse` | `Climate`, `Environment`, `Methane` |
| `telecom` | `neutrality`, `broadband`, `common carrier`, `telecom` | `Telecom`, `Net Neutrality`, `Open Internet` |
| `finance` | `payday`, `installment`, `loans`, `custody`, `asset` | `Finance`, `Loans`, `Consumer Protection` |
| `ai_regulation` | `algorithmic`, `transparency`, `software`, `cybersecurity` | `AI`, `Software`, `Transparency` |
| `privacy` | `robocall`, `spoofing`, `caller id`, `privacy` | `Privacy`, `Robocalls`, `Telemarketing` |
| `labor` | `non-compete`, `workplace`, `employment` | `Labor`, `FTC`, `Workplace` |
| `healthcare` | `clinical`, `device`, `medical`, `fda` | `Healthcare`, `FDA`, `Devices` |

### Decoupled Parity for Future Embeddings Classifiers

By separating classification logic into `scripts/classify_dockets.py`, the system is fully prepared to transition from keyword rules to a semantic **Databricks Foundation Model (e.g. Llama-3)** or an embedding-based nearest-neighbor classifier. Because the script outputs a stable Pydantic model with a defined schema, swapping the classification algorithm will require zero changes to the underlying Delta tables or frontend hydration routines.

---

## 3. UI Ingestion & Watchlist Control Plane

The Next.js web application acts as the steering system and control plane:
1. **Adding Watchlist Items**: Writing to `/api/watchlist` adds a monitoring keyword or entity.
2. **Interactive Catalog Upvotes**: Hitting "Request Analysis" on `/discoveries` increments `user_requested_count`, triggers a background Autopilot sweep, and automatically schedules a local pipeline run once the priority threshold is passed.
3. **Transparency and Offline Fallback**: Under auto-mode, if the live SQL Warehouse or Databricks Jobs API fails, the control plane seamlessly falls back to local JSON data, preventing native app crashes and ensuring high demo availability.
