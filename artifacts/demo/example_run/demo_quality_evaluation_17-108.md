# Coordinated Campaign Validation & Quality Report: 17-108

## Reviewer Quality Summary

This report assesses the quality of our campaign clusters against strict mathematical metrics.
To ensure high-fidelity evidence, each metric is explicitly defined by what it measures,
what it does not measure, and its known failure modes.

---

## Evaluation Metrics Dashboard

| Rank | Cluster ID | Size | Exact Duplicate % | Near Duplicate % | Cluster Purity | Representative Quality |
| --- | --- | --- | --- | --- | --- | --- |
| #1 | `96413d57e367` | **1002** | 1.6% | 98.4% | 99.5% | 0.9655 |
| #2 | `753fb0e2d898` | **13** | 100.0% | 0.0% | 100.0% | 1.0000 |
| #3 | `73c8d60afb00` | **2** | 100.0% | 0.0% | 100.0% | 1.0000 |

---

## Metric Definitions & Honestly Documented Limitations

### 1. Exact Duplicate Ratio
- **What it measures**: The proportion of comments within a cluster that are character-for-character identical after whitespace normalization.
- **What it does NOT measure**: Semantic paraphrasing, light editing (e.g. adding a personal preface), or typo correction.
- **Known Failure Modes**: An astroturf campaign where users are instructed to change just a single word (e.g. swapping "smothering" for "hurting") will have an Exact Duplicate Ratio of `0.0`, despite being highly coordinated.

### 2. Near-Duplicate Ratio
- **What it measures**: The proportion of comments in a cluster that are grouped semantically but are NOT character-for-character identical.
- **What it does NOT measure**: The exact quality or meaningfulness of the customized edits.
- **Known Failure Modes**: If the similarity threshold is set too low (e.g., `0.85`), unrelated but highly verbose comments discussing the same general topic might get clumped together and inflate this ratio.

### 3. Cluster Purity
- **What it measures**: The percentage of members in a cluster that contain the signature campaign sentences/boilerplate phrases.
- **What it does NOT measure**: Semantic alignment of comments that do not use the explicit boilerplate words.
- **Known Failure Modes**: If members express the same sentiment in completely different words, purity will be low despite high semantic similarity.

### 4. Representative-Comment Quality
- **What it measures**: The readability (length sanity) and centralization (similarity to other members).
- **What it does NOT measure**: The truthfulness, political efficacy, or legal validity of the comment's arguments.
- **Known Failure Modes**: A very long comment containing extensive unrelated personal rants could be selected as the medoid if it happens to contain parts of the template, resulting in low representative-comment readability/quality score.

---

## Detailed Diagnostics per Cluster

### Cluster `96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c` (Size: 1002)
- **Exact Duplicate Ratio**: `0.0160`
- **Near-Duplicate Ratio**: `0.9840`
- **Cluster Purity**: `0.9950`
- **Representative Quality**: `0.9655`

**Surfaced Campaign Boilerplate Sentences**:
1. "That’s not the kind of Internet we want to pass on to future generations of technology users."
2. "That’s contrary to the basic precepts on which the Internet was built."
3. "That’s not how the Internet was built, and that's not what we want."

---

### Cluster `753fb0e2d898c0f0d1dbd7070b6e1fcb1a839da537e2e757b238cba2d3b75906` (Size: 13)
- **Exact Duplicate Ratio**: `1.0000`
- **Near-Duplicate Ratio**: `0.0000`
- **Cluster Purity**: `1.0000`
- **Representative Quality**: `1.0000`

**Surfaced Campaign Boilerplate Sentences**:
1. "Net neutrality has created an unreliable landscape for consumers and businesses alike."
2. "We need Congress to bring clarity to this debate."

---

### Cluster `73c8d60afb009ba76673e9218d60f0ef0ebaa39f421de2f1bc24040a4aeaedb3` (Size: 2)
- **Exact Duplicate Ratio**: `1.0000`
- **Near-Duplicate Ratio**: `0.0000`
- **Cluster Purity**: `1.0000`
- **Representative Quality**: `1.0000`

**Surfaced Campaign Boilerplate Sentences**:
1. "I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II."

---

## Pipeline General Limitations
1. **Temporal Horizon Bias**: The local demo slice spans only a 3-day window. Some campaign waves are wider, meaning full volume is underrepresented here.
2. **Threshold Sensitivity**: A fixed similarity threshold of `0.92` works exceptionally well for BGE embeddings, but slight semantic drifts (e.g. heavy personal prefaces) can lead to false negatives.
3. **Spam Filtering Assumptions**: This harness assumes that high similarity represents a coordinated spam campaign; it cannot distinguish legal bulk filings (advocacy groups compiling authorized petitions) from malicious fake submissions (identity theft) without manual registry checks.
