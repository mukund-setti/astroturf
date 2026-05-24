# Attribution and Migration Methodology

This document explains how the AttributionAgent and MigrationAgent work, what
they claim, what they explicitly do not claim, and how reviewers should
interpret their output. The companion architectural decision is
[ADR-0015](decisions/0015-attribution-and-migration-agents.md).

> Outputs from both agents are **evidence packets**, not accusations. They are
> a starting point for manual review, not a conclusion.

## What the agents do

### AttributionAgent

Given a detected comment cluster, AttributionAgent answers:

> Does this cluster's representative text show evidence of language drawn
> from a known organising source (a trade association, advocacy group,
> company, or other entity) that we have curated for this docket?

MVP mode is `offline_seed`. The agent loads a curated JSON registry under
`evals/fixtures/attribution/<docket>_known_sources.json` and, for each
candidate entity:

1. Looks for **exact phrase** matches between the entity's known template
   phrases and the cluster representative text (case- and
   whitespace-normalised).
2. Falls back to **fuzzy** matching (Python `difflib.SequenceMatcher` ratio
   ≥ 0.85) if no exact phrase matched.
3. Emits a **registry-only** row if the entity is listed for this docket
   but no phrase fit at all — this is a "needs manual review" signal, not
   evidence of authorship.

Each emitted row is a `gold.campaign_attributions` record with the matched
phrase, an excerpt of the cluster text around the match, the entity's
public URL, an `evidence_type`, a numeric `confidence_score`, and a
categorical `confidence_label`.

### MigrationAgent

Given a cluster and a final-rule text document, MigrationAgent answers:

> Does the cluster's representative text overlap, at the phrase level, with
> the final rule text?

MVP mode is `local_text`. The agent loads a local fixture or path, splits
the rule text into sections, generates candidate phrases from the cluster
representative text, and emits a row for each match above the configured
similarity threshold.

Each emitted row is a `gold.rule_migrations` record with the cluster
phrase, the matching rule phrase, the section, a similarity score, a
`match_type` (`exact` / `near_exact` / `semantic`), a `claim_scope`, and a
**mandatory** `caveat_text` field.

## What the agents do not claim

Both agents are explicit about their limits.

AttributionAgent does **not** claim:

- That a candidate entity "caused", "funded", "directed", or "is
  responsible for" any comment in the cluster.
- That every comment in the cluster is fake or inauthentic.
- Certainty. `confidence_score` is hard-capped strictly below 1.0, even on
  exact phrase matches.

MigrationAgent does **not** claim:

- That the campaign cluster influenced the rule.
- That rule authors saw, read, or considered the cluster.
- That the rule "adopted" cluster language. The strongest scope it emits is
  `possible_influence`, reserved for long exact phrase matches and still
  carrying an explicit caveat.

## Confidence scoring

AttributionAgent (`offline_seed`):

| Signal                                          | Base score | Label          |
|-------------------------------------------------|------------|----------------|
| Exact phrase appears verbatim in cluster text   | 0.85       | `high`         |
| Fuzzy phrase ratio ≥ 0.85                       | 0.65       | `medium`       |
| Registry entity, no phrase hit                  | 0.35       | `low`          |
| Multiple distinct exact phrases (additive)      | +0.10      | (capped 0.95)  |

MigrationAgent (`local_text`):

| Signal                                          | match_type   | Base score |
|-------------------------------------------------|--------------|------------|
| Exact phrase appears in a rule section          | `exact`      | 0.80       |
| Fuzzy ratio ≥ 0.90                              | `near_exact` | 0.65       |
| Fuzzy ratio in `[0.75, 0.90)`                   | `semantic`   | 0.45       |
| Ratio < 0.75                                    | dropped      | —          |

Both agents flip `confidence_label` to `needs_review` whenever the score is
below 0.50.

## Manual review expectations

- Every row carries `reviewed_status = "unreviewed"` until a human flips it.
- The campaign-detail UI displays the status prominently and uses neutral
  language only: "Candidate source", "Evidence match", "Likely campaign
  origin", "Language overlap", "Possible influence signal", "Needs manual
  review".
- Reviewers should always inspect the matched phrase, the excerpt, and the
  source URL before citing a row in any external context. The MVP does
  not enforce that workflow; it stores the field so downstream tools can.

## Ethical and civic caveats

- These are public comments on federal rulemakings. Naming a candidate
  organisation as the *likely origin* of a templated comment is not a claim
  about any individual commenter. Many commenters in a templated cluster
  may have submitted their comments in good faith.
- Public attribution of campaign sources is sensitive even when the
  evidence is strong. Conservatism in the user-facing language is part of
  the product, not a bug.
- The platform never asserts that a campaign caused a rule change. The
  observable signals — phrase overlap, temporal coordination, registry
  matches — are correlational. Causal claims require additional independent
  evidence (e.g., direct lobbying disclosures, regulator interviews,
  internal correspondence) that this platform does not collect.

## Running the agents

Attribution (offline_seed, against the curated FCC 17-108 seed):

```
python scripts/run_attribution.py --docket-id 17-108 --mode offline_seed --max-clusters 5
```

Migration (local_text, against the bundled fixture):

```
python scripts/run_migration.py --docket-id 17-108 --mode local_text \
    --final-rule-text evals/fixtures/migration/fcc_17_108_final_rule_excerpt.txt \
    --max-clusters 5
```

The migration fixture is clearly labelled
"test fixture, not official full rule text" and is intended for unit tests
and demo runs only.
