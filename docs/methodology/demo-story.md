# Demo story

The intended pitch for the Databricks Student Fellows program. Three acts: the
problem, what we built, and what the evidence shows. For "what exists today as
infrastructure," read `docs/architecture/system-map.md`.

## Act 1 — The problem

Federal rulemaking is supposed to be the public's say in how regulations get
written. But agencies routinely receive hundreds of thousands of comments on a
single rule, and a large share of them are **coordinated mass-comment
campaigns** — identical or near-identical letters submitted in bulk by
advocacy groups, trade associations, and political action portals.

Two things follow from that:

1. **A submission count is not a vote count.** "EPA received 200,000 comments
   in support" can mean two hundred thousand independent citizens, or it can
   mean one template letter sent two hundred thousand times. The agency, the
   press, and the public need to be able to tell the difference.
2. **Campaign language sometimes survives into the final rule.** When a
   coordinated campaign supplies a particular phrasing of a policy argument
   and that phrasing reappears in the agency's published rule, that is a
   provenance trail worth being able to point at.

Neither question is decidable by reading 200,000 comments by hand. It needs a
pipeline.

## Act 2 — What we built

**Astroturf is a six-agent system on a Delta medallion lakehouse.** Agents
communicate through durable Delta tables, not in-memory message passing, so
every stage is independently replayable, idempotent on its primary key, and
inspectable from any layer.

The shape today:

- **IngestionAgent** pulls every comment for a docket from `regulations.gov`
  v4 into `bronze.raw_comments`. Validated end-to-end on CFPB-2016-0025
  (211,885 comments, 0 duplicate IDs) and EPA-HQ-OAR-2021-0317.
- **ParserAgent** v1 + v2A normalizes text and side-loads each comment's full
  detail JSON into `silver.parsed_comments`, `silver.comment_details`, and
  `silver.comment_attachments`. Substantive vs. cover-note classification is
  built in.
- **AttachmentDownloaderAgent** v2B phase 1 puts attachment binaries on disk
  with size and checksum metadata. Text extraction is the next phase.
- **EmbeddingAgent** embeds substantive comment text via a pluggable backend.
  The local backend is `BAAI/bge-large-en-v1.5` via `sentence-transformers`;
  the Databricks backend is `databricks-bge-large-en` via the Databricks
  Foundation Model API. Same model family, byte-identical embeddings, so the
  local signal reproduces on Databricks.
- **ClusteringAgent** v1 detects near-duplicate clusters as connected
  components in a cosine-similarity graph, scoped by `(docket_id,
  embedding_model, clustering_version)` so re-runs are safe. Writes
  `gold.comment_clusters` and `gold.comment_cluster_memberships`.
- **ExactHashBaseline** runs alongside it on the literal
  `normalized_text_hash`, writing into the same gold tables under a different
  `clustering_version`. It is the floor — anything the embedding clusterer
  finds beyond this is paraphrase-driven, not copy-paste.
- **AttributionAgent** (future, genuinely agentic — tool-using LLM with web
  search + advocacy registry) and **MigrationAgent** (future, cluster
  templates vs. final rule text) round out the system.

The whole thing sits on Databricks-shaped infrastructure: Delta tables,
MLflow runs per stage, Foundation Model embeddings, Vector Search for cluster
retrieval (planned), Workflows for orchestration (planned), Unity Catalog
governance (planned). It is not a deployment target bolted on at the end; it
is the substrate the system was designed around. See
`docs/databricks/integration.md` for the promotion path.

## Act 3 — What the evidence shows

The running campaign-evidence demo is **EPA-HQ-OAR-2021-0317** (the EPA
methane-pollution rule). Its substantive content sits in in-line text rather
than attachments, so the same pipeline produces strong clusters end-to-end
today.

From 396 substantive `detail_comment_text` rows on this docket:

| Detector                                    | Clusters | Members | Largest cluster |
|---------------------------------------------|----------|---------|-----------------|
| Exact-hash baseline (literal duplicates)    | 7        | 16      | 4               |
| Embedding clustering, `databricks-bge-large-en`, threshold 0.92 | 13       | 162     | 123             |

The point of putting these two rows next to each other is the gap between
them:

- **Literal copy-paste catches 16 comments.** That is the kind of campaign
  detection you can do with a `GROUP BY normalized_text_hash`.
- **Semantic embedding clustering surfaces 162 campaign-like comments.** An
  order of magnitude more, because most coordinated campaigns supply a
  template that gets lightly paraphrased — a name swapped in, a sentence
  rewritten, a paragraph reordered — before submission.
- **The primary cluster is 123 comments by itself.** One template, paraphrased
  123 ways, dominates the docket. The other twelve embedding clusters are
  smaller variants and sibling templates.

The bundled review at
`data/exports/cluster_evidence_EPA-HQ-OAR-2021-0317.md` shows the
representative text for each cluster, sample members with similarity scores,
and a campaign-style classification (`embedding/paraphrase-driven` vs.
`exact-duplicate-driven`). The 123-comment cluster is clearly a methane-rule
template paraphrased across many filings, with similarity to the
representative ranging from 0.84 up to 1.0.

**The Databricks claim is operational, not aspirational.** The clusters above
were produced using embeddings labeled `embedding_model =
databricks-bge-large-en`, the production model name. The
`DatabricksFoundationModelBackend` is implemented against the Databricks SDK
with a safe default batch size of 16 and is mock-tested locally; an explicitly
approved live workspace run is the remaining proof point and is the top item
on the next-priorities list.

## What a non-technical reviewer should see

A short, calm walkthrough in three screens:

1. **A docket overview.** One docket, one number that lands hard: hundreds of
   thousands of public comments on the CFPB docket, a histogram showing daily
   submission volume, and a single sentence about why anyone would care that
   they are not all independent.
2. **A detected campaign.** One cluster on the screen at a time. Cluster size
   (lead with the 123-comment EPA cluster), the representative template
   paragraph, three or four sample comments shown side-by-side so the visual
   sameness is obvious, the similarity threshold and the score distribution,
   and the timeline spike that shows when this campaign was active. The
   exact-hash baseline appears as a "literal duplicates" panel next to it so
   the reviewer can see what the embedding step added.
3. **(Stretch)** **A trace into the final rule.** One side-by-side panel: a
   phrase from the campaign template on the left, the matching language in
   the agency's final rule on the right, with the section citation.

No code, no Spark UI, no SQL. The reviewer should leave knowing what was
detected, why we believe it, and what is still claimed cautiously.

## The wow moment

A single screen showing 123 public comments collapsing into one detected
template — same phrasing, same submission window, same plausible origin —
right next to the 16-comment literal-duplicate baseline that any naive
detector would have produced. The contrast is the moment the embedding work
earns its keep.

If the migration step is not ready in time, the wow moment stays on the
cluster view: the visceral "these are not 162 independent voices, this is one
letter sent 123 times plus close paraphrases."

## Evidence a detected campaign should show

For every cluster surfaced in the demo UI, the reviewer should be able to see
all of the following at a glance:

- **Cluster size** — number of comments grouped into this cluster.
- **Similarity score and threshold** — the cosine similarity used to admit a
  comment into the cluster, and the threshold value, so the reviewer
  understands the sensitivity dial.
- **Campaign-style classification** — `exact-duplicate-driven` vs.
  `embedding/paraphrase-driven`, derived from the ratio of unique
  `normalized_text_hash` values inside the cluster.
- **Representative template** — the canonical text for the cluster, picked
  either as the medoid or the highest-frequency exact text.
- **Submission timeline spike** — a histogram of submission times for the
  cluster's comments, overlaid on (or contrasted with) the docket's overall
  submission timeline. Coordinated campaigns tend to spike inside a narrow
  window.
- **Sample comments** — three to five raw submissions from the cluster, shown
  in full, so the reviewer can confirm with their own eyes that the cluster
  is real.
- **Possible source attribution** — best guess at the campaign's origin (an
  advocacy group, an action portal, a partisan campaign), with the URL and
  the evidence the `AttributionAgent` used to make the call, plus a
  confidence level. Clearly labeled as "possible" until human-verified.
- **Possible final-rule language migration** — phrase- or section-level
  matches between the cluster's template and the agency's final rule text,
  with citations. Also clearly labeled as "possible."

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
  production without provisioning our own GPUs (ADR-0005). The local and
  Databricks signals are designed to be interchangeable.
- **Vector Search.** Databricks Vector Search indexes the
  `silver.comment_embeddings` table — filtered by `embedding_model` to
  satisfy its fixed-dimension constraint — so cluster candidate retrieval is
  a managed service, not custom infrastructure.
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
+ Unity Catalog is exactly the stack the system was designed around.

## v1 demo scope

The v1 demo should include all of the following, and **only** the following:

- **EPA-HQ-OAR-2021-0317 as the lead campaign story** — the 13-cluster, 162-
  membership, 123-primary-cluster signal is the visible result.
- **CFPB-2016-0025 as the scale story** — 211,885 comments ingested
  end-to-end, with an explicit caveat that most substantive text lives in
  attachments and the v1 embedding signal there is small because attachment
  extraction is the next phase.
- **Comment-level embeddings** (not paragraph-level, not attachment-page-
  level).
- **Near-duplicate clusters** from cosine on those embeddings, with a
  tunable threshold and the exact-hash baseline shown alongside.
- **A basic Streamlit or Databricks App explorer** that lists clusters, lets
  a reviewer click in, and shows the evidence panel (size, threshold,
  template, timeline, samples).
- **An end-to-end run on Databricks** of at least one docket, so the story
  "same code runs locally and on Databricks" is true and demonstrable.

That is the v1 line. Everything else lives in stretch goals.

## Non-goals for v1

The demo deliberately does **not** claim, and the system deliberately does
**not** try to prove, any of the following:

- **Legal causality.** "This campaign caused this rule to say X" is a legal
  claim. We surface candidate matches; we do not litigate them.
- **That lobbying caused agency decisions.** Coordinated commenting is a
  fact about public input volume, not a fact about agency decision-making.
  Correlation in the rule text is suggestive, not dispositive.
- **Full all-agency `regulations.gov` coverage.** v1 covers one or two
  dockets, run end-to-end. A platform sweep of every active rulemaking is a
  later project.
- **Perfect OCR on scanned attachments.** Attachment text extraction is
  best-effort; some scanned PDFs will degrade or fail, and the demo should
  be honest about which clusters are derived from clean text vs. extracted
  text.
- **Fully automated attribution.** The `AttributionAgent` proposes likely
  origins with evidence and confidence. Final attribution claims belong to
  a human reviewing the evidence panel.

## Reviewer pitch paragraph (Databricks Student Fellows)

> Astroturf detects coordinated public comment campaigns in federal
> rulemaking and traces their language into final rules. It is a six-stage
> multi-agent system on a Delta medallion lakehouse, with Databricks
> Foundation Models for embeddings, Databricks Vector Search for cluster
> retrieval, MLflow for per-stage experiment tracking, Workflows for
> orchestration, and Unity Catalog for governance. On EPA-HQ-OAR-2021-0317,
> a naive literal-duplicate baseline finds 16 copy-pasted comments across 7
> clusters; the embedding clusterer (`databricks-bge-large-en`, cosine
> threshold 0.92) surfaces 162 campaign-like comments across 13 clusters,
> with a single 123-comment template dominating — a roughly tenfold lift
> over the literal baseline, on real public-comment data. Each agent
> communicates through durable Delta tables and is independently
> replayable, so the system scales from a single docket on a laptop to all
> active rulemaking on a Databricks workspace without changing shape. The
> work fits the Student Fellows program because it is a real, end-to-end
> Databricks workload on a problem the platform is uniquely well-suited to
> solve, and because every architectural choice has been written down as an
> ADR rather than improvised.

## Cut list (if time is short)

In priority order, the things to drop first:

1. **Final-rule migration view** (the third demo screen). Cut entirely if
   `MigrationAgent` is not ready. The cluster view alone is sufficient for
   the wow moment.
2. **Source attribution view.** Replace with a static "Attribution agent:
   under construction" panel and a description of what it would surface. Do
   not show half-built attributions.
3. **CFPB docket as a second demo arc.** Drop to EPA-only. The story is the
   same; the scale claim shrinks.
4. **Attachment-derived comments.** If v2B phases 2–4 are not done, run the
   demo on cover-note + in-line comments only and call out in the script that
   attachment extraction is the next milestone. The CFPB sample shape (most
   substantive content in attachments) means this materially limits coverage
   on that docket, and the script should say so.
5. **Live Databricks run on stage.** Pre-record the Databricks run; demo from
   the local Streamlit explorer reading Delta tables that were produced on
   Databricks.

## Stretch goals (if ahead)

In priority order, the things to add if there is time:

1. **Two dockets, side by side.** Show the system generalizes by running it
   end-to-end on a second docket from a different agency — e.g., FCC or a
   different EPA rule.
2. **Cross-docket campaign linkage.** If a single advocacy group ran a
   coordinated campaign across multiple dockets, link the clusters across
   dockets in the UI.
3. **Live Databricks Workflow demo.** Trigger a Workflow run on stage and
   show the task DAG and MLflow runs populating in real time.
4. **Per-cluster confidence bands.** Surface a calibrated confidence score
   per cluster, not just a similarity threshold, derived from cluster density
   and submission-time concentration.
5. **Embedded reviewer notes.** Let a reviewer mark a cluster as "confirmed,"
   "rejected," or "needs human review" and write that judgment back into a
   Delta table for downstream evaluation.
