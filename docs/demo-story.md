# Demo story

The intended final demo for the Databricks Student Fellows program. This is a
forward-looking document: it describes what the v1 demo *should* show, not what
exists today. For "what exists today," read `docs/system-map.md`.

## 60-second demo script

> "Federal rulemaking is supposed to be the public's say in how regulations get
> written. But agencies routinely receive hundreds of thousands of comments on a
> single rule, and a large share of them are coordinated mass-comment campaigns —
> identical or near-identical letters submitted in bulk by advocacy groups,
> trade associations, and political action portals.
>
> Astroturf is a multi-agent system on Databricks that finds those campaigns
> automatically and traces their language into the agency's final rule.
>
> *(Open the demo app, pick CFPB-2016-0025 — the consumer-arbitration rule.)*
>
> The system has ingested all 211,885 public comments on this docket into a
> Delta bronze table, parsed them into normalized text in silver, and embedded
> them with `BAAI/bge-large-en-v1.5` via Databricks Foundation Model API.
>
> *(Click into a detected cluster.)*
>
> Here is one campaign: thousands of near-identical comments submitted in a
> tight time window. Here is the representative template, the cosine similarity
> threshold, sample submissions, and the timeline spike. *(Click attribution.)*
> Here is a likely origin — an advocacy group's action page that we matched
> against this template via a tool-using LLM agent. *(Click migration.)*
> And here is where similar phrasing appeared in the agency's final rule.
>
> Every stage runs as an independent agent over Delta tables, every run is
> tracked in MLflow, every embedding goes through Databricks Vector Search,
> and the whole thing is governed in Unity Catalog. Same code runs locally and
> on Databricks Workflows."

That is the v1 ambition. The current state ends at "embedded with the local
backend"; the v1 scope below is what we plan to actually have working for the
demo.

## What a non-technical reviewer should see

A short, calm walkthrough in three screens:

1. **A docket overview.** One docket, one number that lands hard: hundreds of
   thousands of public comments, a histogram showing daily submission volume,
   and a single sentence about why anyone would care that they are not all
   independent.
2. **A detected campaign.** One cluster on the screen at a time. Cluster size,
   a representative template paragraph, three or four sample comments shown
   side-by-side so the visual sameness is obvious, and the timeline spike that
   shows when this campaign was active.
3. **(Stretch)** **A trace into the final rule.** One side-by-side panel: a
   phrase from the campaign template on the left, the matching language in the
   agency's final rule on the right, with the section citation.

No code, no Spark UI, no SQL. The reviewer should leave knowing what was
detected, why we believe it, and what is still claimed cautiously.

## The wow moment

A single screen showing thousands of public comments collapsing into one
detected campaign — same template, same submission window, same plausible
origin — followed by a phrase from that campaign appearing verbatim or
near-verbatim in the agency's final rule. That is the moment the project earns
its name.

If the migration step is not ready in time, the wow moment is just the cluster
view: the visceral "these are not 8,432 independent voices, this is one letter
sent 8,432 times."

## Evidence a detected campaign should show

For every cluster surfaced in the demo UI, the reviewer should be able to see
all of the following at a glance:

- **Cluster size** — number of comments grouped into this cluster.
- **Similarity score and threshold** — the cosine similarity used to admit a
  comment into the cluster, and the threshold value, so the reviewer
  understands the sensitivity dial.
- **Representative template** — the canonical text for the cluster, picked
  either as the medoid or the highest-frequency exact text.
- **Submission timeline spike** — a histogram of submission times for the
  cluster's comments, overlaid on (or contrasted with) the docket's overall
  submission timeline. Coordinated campaigns tend to spike inside a narrow
  window.
- **Sample comments** — three to five raw submissions from the cluster, shown
  in full, so the reviewer can confirm with their own eyes that the cluster is
  real.
- **Possible source attribution** — best guess at the campaign's origin (an
  advocacy group, an action portal, a partisan campaign), with the URL and the
  evidence the `AttributionAgent` used to make the call, plus a confidence
  level. Clearly labeled as "possible" until human-verified.
- **Possible final-rule language migration** — phrase- or section-level
  matches between the cluster's template and the agency's final rule text, with
  citations. Also clearly labeled as "possible."

The "possible" labels are important. The system surfaces strong candidates;
it does not pronounce verdicts.

## Why Databricks is load-bearing

This is not a project that *could* run on Databricks — it is a project that
needs Databricks for several distinct reasons, not just one.

- **Delta medallion architecture.** Agents communicate through durable Delta
  tables (bronze → silver → gold), not in-memory message passing (ADR-0001).
  Every stage is independently replayable, idempotent on its primary key, and
  inspectable from any layer. Delta MERGE is the inter-agent contract.
- **Scalable embeddings.** The Databricks Foundation Model API
  (`databricks-bge-large-en`) hosts the same model family we run locally
  (`BAAI/bge-large-en-v1.5`), so we can embed millions of comments in
  production without provisioning our own GPUs (ADR-0005).
- **Vector Search.** Databricks Vector Search indexes the
  `silver.comment_embeddings` table — filtered by `embedding_model` to satisfy
  its fixed-dimension constraint — so cluster candidate retrieval is a managed
  service, not custom infrastructure.
- **MLflow experiments.** Every agent run already emits an MLflow run with
  inputs, outputs, row counts, and timing. On Databricks this becomes the
  production audit trail across thousands of dockets — not just our laptop.
- **Workflows.** Databricks Workflows replaces the local orchestrator for
  production runs, with task dependencies, retries, and a single dashboard.
- **Unity Catalog / governance.** Bronze, silver, and gold tables move from
  file paths to three-part names with table-level lineage, access controls,
  and column-level governance — important when downstream consumers might
  include journalists, agencies, or the public.

In short: medallion + Vector Search + Foundation Models + MLflow + Workflows
+ Unity Catalog is exactly the stack the system was designed around. It is
not a deployment target bolted on at the end.

## v1 demo scope

The v1 demo should include all of the following, and **only** the following:

- One or two dockets, picked because they have a known mass-comment story
  (CFPB-2016-0025 is the running candidate; one EPA or FCC docket is the likely
  second).
- Comment-level embeddings (not paragraph-level, not attachment-page-level).
- Near-duplicate clusters from cosine on those embeddings, with a tunable
  threshold.
- A basic Streamlit or Databricks App explorer that lists clusters, lets a
  reviewer click in, and shows the evidence panel (size, threshold, template,
  timeline, samples).
- An end-to-end run on Databricks of at least one of the two dockets, so the
  story "same code runs locally and on Databricks" is true and demonstrable.

That is the v1 line. Everything else lives in stretch goals.

## Non-goals for v1

The demo deliberately does **not** claim, and the system deliberately does
**not** try to prove, any of the following:

- **Legal causality.** "This campaign caused this rule to say X" is a legal
  claim. We surface candidate matches; we do not litigate them.
- **That lobbying caused agency decisions.** Coordinated commenting is a fact
  about public input volume, not a fact about agency decision-making.
  Correlation in the rule text is suggestive, not dispositive.
- **Full all-agency `regulations.gov` coverage.** v1 covers one or two
  dockets, run end-to-end. A platform sweep of every active rulemaking is a
  later project.
- **Perfect OCR on scanned attachments.** Attachment text extraction is
  best-effort; some scanned PDFs will degrade or fail, and the demo should be
  honest about which clusters are derived from clean text vs. extracted text.
- **Fully automated attribution.** The `AttributionAgent` proposes likely
  origins with evidence and confidence. Final attribution claims belong to a
  human reviewing the evidence panel.

## Reviewer pitch paragraph (Databricks Student Fellows)

> Astroturf detects coordinated public comment campaigns in federal rulemaking
> and traces their language into final rules. It is a six-stage multi-agent
> system on a Delta medallion lakehouse, with Databricks Foundation Models for
> embeddings, Databricks Vector Search for cluster retrieval, MLflow for
> per-stage experiment tracking, Workflows for orchestration, and Unity Catalog
> for governance. Each agent communicates through durable Delta tables and is
> independently replayable, so the system scales from a single docket on a
> laptop to all active rulemaking on a Databricks workspace without changing
> shape. The output is a reviewer-facing app that surfaces detected campaigns
> with size, similarity, representative template, timeline, and a candidate
> origin, and — at v1 stretch — flags where that campaign's language reappears
> in the agency's final rule. The work fits the Student Fellows program because
> it is a real, end-to-end Databricks workload on a problem the platform is
> uniquely well-suited to solve, and because every architectural choice has
> been written down as an ADR rather than improvised.

## Cut list (if time is short)

In priority order, the things to drop first:

1. **Final-rule migration view** (the third demo screen). Cut entirely if
   `MigrationAgent` is not ready. The cluster view alone is sufficient for the
   wow moment.
2. **Source attribution view.** Replace with a static "Attribution agent: under
   construction" panel and a description of what it would surface. Do not show
   half-built attributions.
3. **Second docket.** Drop to a single docket (CFPB-2016-0025). The story is
   the same; the breadth claim shrinks.
4. **Attachment-derived comments.** If v2B phases 2–4 are not done, run the
   demo on cover-note + in-line comments only and call out in the script that
   attachment extraction is the next milestone. The CFPB sample shape (most
   substantive content in attachments) means this materially limits coverage,
   and the script should say so.
5. **Live Databricks run on stage.** Pre-record the Databricks run; demo from
   the local Streamlit explorer reading Delta tables that were produced on
   Databricks.

## Stretch goals (if ahead)

In priority order, the things to add if there is time:

1. **Two dockets, side by side.** Show the system generalizes by running it
   end-to-end on a second docket from a different agency.
2. **Cross-docket campaign linkage.** If a single advocacy group ran a
   coordinated campaign across multiple dockets, link the clusters across
   dockets in the UI.
3. **Live Databricks Workflow demo.** Trigger a Workflow run on stage and show
   the task DAG and MLflow runs populating in real time.
4. **Per-cluster confidence bands.** Surface a calibrated confidence score per
   cluster, not just a similarity threshold, derived from cluster density and
   submission-time concentration.
5. **Embedded reviewer notes.** Let a reviewer mark a cluster as "confirmed,"
   "rejected," or "needs human review" and write that judgment back into a
   Delta table for downstream evaluation.
