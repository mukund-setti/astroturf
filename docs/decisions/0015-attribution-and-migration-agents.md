# ADR-0015: Attribution and migration evidence strategy

- Status: Accepted
- Date: 2026-05-24

## Context

Phase 8 introduces the influence-tracing layer of the pipeline. Two agents are
involved:

- `AttributionAgent` answers: *given a detected campaign cluster, where did
  the templated language most likely originate from?*
- `MigrationAgent` answers: *does cluster language appear in the final agency
  rule text?*

Both questions are politically and ethically loaded. The platform must not
imply that a particular organisation "wrote the rule" or that a cluster
"caused" a regulatory outcome — even when the evidence is strong, the
underlying lobbying / influence chain is rarely directly observable from
public data. We need an explicit, written policy on what these agents claim
and what they refuse to claim, so reviewers and downstream UI surfaces never
overstate the evidence.

The MVP is also deliberately small. We do not want to ship a feature whose
correctness depends on paid APIs, live web search, or LLM hypothesis
generation. The default path must run fully offline against curated seed data
and a local fixture for final rule text.

## Decision

### What AttributionAgent claims
- A *candidate* origin for a cluster, drawn from a curated registry of known
  advocacy groups, trade associations, companies, or other entities.
- An *evidence packet*: the matched phrase, the cluster excerpt, the source
  URL from the registry, the match type, a numeric `confidence_score` in
  `[0.0, 1.0)`, and a categorical `confidence_label`.
- A `reasoning_summary` field that paraphrases the evidence in human terms.
  It is generated mechanically from the matched fields in `offline_seed` mode
  and never invents new entities.

### What AttributionAgent does not claim
- That the candidate entity caused the cluster.
- That the candidate entity funded, organised, or is responsible for the
  cluster.
- Certainty. `confidence_score` is capped strictly below `1.0` even for exact
  phrase matches. There is no path in `offline_seed` mode to produce
  `confidence_score = 1.0`.
- Anything about individual commenters.

### What MigrationAgent claims
- That specific phrases from the cluster representative or member text
  *overlap* with phrases in the final rule text.
- A `claim_scope` of `phrase_overlap`, `argument_similarity`, or
  `possible_influence`. The MVP only emits `phrase_overlap` and (for higher
  bars) `possible_influence` — never anything stronger.
- A mandatory `caveat_text` field. No migration row may be written without
  one.

### What MigrationAgent does not claim
- That the cluster caused, influenced, or was adopted into the final rule.
- That the final rule's authors saw, read, or considered the campaign.
- Verbatim adoption above the phrase level unless the evidence is direct
  (and even then, "verbatim adoption" is described as "exact phrase overlap").
- Anything about closed-door negotiation, lobbying, or regulatory intent.

### Evidence sources

For `AttributionAgent`:

1. **Offline seed registry (MVP default).** Curated JSON files under
   `evals/fixtures/attribution/<docket>_known_sources.json`. Each entity has
   `entity_name`, `entity_type`, `url`, and one or more known
   `template_phrases`. Phrases are sourced only from material already present
   in this repository's documents or public reporting that we have cited
   internally. Out-of-repo curation requires a separate ADR.
2. **Web research (off by default).** Reserved for a future ADR. The agent
   accepts the mode but refuses to run if web tooling is not configured.
3. **LLM-assisted summary (off by default).** Restricted to summarising
   already-captured evidence and never inventing entity names. Out of scope
   for the MVP.

For `MigrationAgent`:

1. **Local text fixture (MVP default).** Plain text files under
   `evals/fixtures/migration/<docket>_final_rule_excerpt.txt`, explicitly
   labelled as test fixtures, not official full rule text.
2. **Federal Register API (off by default).** Reserved for a future ADR.
   The agent accepts the mode but refuses to run when no fetcher is
   configured. No paid APIs.

### Confidence scoring

`AttributionAgent` (`offline_seed`):

| Signal                                          | Base score | Label          |
|-------------------------------------------------|------------|----------------|
| Exact phrase appears verbatim in cluster text   | 0.85       | `high`         |
| Fuzzy ratio between phrase and cluster ≥ 0.85   | 0.65       | `medium`       |
| Entity matched by registry, no phrase hit       | 0.35       | `low`          |
| Bonus for multiple distinct exact phrases       | +0.10      | (capped 0.95)  |
| LLM hypothesis (future mode)                    | ≤ 0.50     | `needs_review` |

`confidence_score` is hard-clamped to `[0.0, 0.95]`. Any score below `0.50`
flips `confidence_label` to `needs_review` regardless of evidence type.

`MigrationAgent` (`local_text`):

| Signal                                                       | match_type   | Base score |
|--------------------------------------------------------------|--------------|------------|
| Cluster phrase appears verbatim in final-rule section        | `exact`      | 0.80       |
| Fuzzy ratio ≥ 0.90                                           | `near_exact` | 0.65       |
| Fuzzy ratio in `[0.75, 0.90)`                                | `semantic`   | 0.45       |
| All matches below 0.75 are ignored                           | -            | -          |

`confidence_label` follows the same mapping as attribution. `claim_scope`
defaults to `phrase_overlap` and is upgraded to `possible_influence` only when
the match type is `exact` and the phrase is at least 12 words long. Anything
stronger than `possible_influence` is out of scope.

### Manual review requirements

- `reviewed_status` defaults to `unreviewed`.
- The UI displays this status prominently and uses neutral language only
  ("Candidate source", "Evidence match", "Needs manual review", "Likely
  campaign origin").
- Reviewers may flip the status to `reviewed` or `rejected`. This MVP does
  not implement the review workflow itself; it stores the status field so
  downstream tools can.

### Why outputs are "evidence packets," not definitive accusations

A row in `gold.campaign_attributions` is not a statement that an entity is
responsible for a campaign. It is a statement that *we observed an evidence
match against a curated registry entry with a particular confidence*. A row
in `gold.rule_migrations` is not a statement that a cluster influenced a
rule. It is a statement that *cluster text overlaps with final rule text at
the phrase level, with a specified scope and caveat*. The schemas, the UI
labels, and this ADR all reinforce that distinction.

## Consequences

Positive:

- The platform can ship the full influence-tracing arc
  (`cluster → likely origin → possible language overlap with final rule`)
  without overclaiming.
- Reviewers always see explicit confidence labels and caveats.
- The MVP requires no paid API, no live web search, and no LLM call.
- Both agents are independently replayable, idempotent on their primary keys,
  and gated by `confidence_threshold` so noisy matches are filtered out.

Negative:

- Coverage is bounded by the seed registry and fixture. Adding a new docket
  requires curating new seed data, which is manual.
- Without `web_research` or `federal_register_api` modes, the MVP cannot
  surface attribution for a docket we have not curated.
- `confidence_score < 1.0` is unusual in ML output and may surprise readers;
  the cap is intentional and is documented in this ADR plus
  `docs/methodology/attribution-and-migration.md`.

## Alternatives considered

### 1. Skip AttributionAgent / MigrationAgent until LLM tools are wired up

Rejected. The product narrative needs the end-to-end arc visible to reviewers,
and the offline_seed mode is the most defensible MVP. Web/LLM modes can be
added later without breaking the schema.

### 2. Emit a single boolean "is attributed" / "is migrated" flag

Rejected. A boolean hides the evidence; reviewers cannot triage without the
matched phrase, the excerpt, the source URL, and the confidence score.

### 3. Allow `confidence_score = 1.0` for direct phrase hits

Rejected. Even verbatim phrase matches do not prove intent or causality. The
cap below `1.0` is a small but durable correctness signal.

### 4. Inline attribution/migration data into `gold.comment_clusters`

Rejected. Multiple attribution rows per cluster are expected, and migration
output joins against external rule documents. Separate gold tables follow the
same medallion pattern as ADR-0006 / ADR-0009 and keep the cluster table
focused on cluster identity.
