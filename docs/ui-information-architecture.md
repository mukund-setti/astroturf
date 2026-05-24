# UI Information Architecture & Routing Matrix

This document outlines the public Next.js frontend navigation, structural
routes, global search behavior, and data-hydration strategy for Astroturf's
evidence-first MVP.

## Route Matrix

The frontend uses the Next.js App Router:

```text
ui/app/
├── page.tsx                   # MVP landing page with evidence-first coverage
├── topics/
│   ├── page.tsx               # Analyzed topics plus Analyze CTA
│   └── [topic_id]/page.tsx    # Topic dossier or ingestion handoff
├── agencies/
│   ├── page.tsx               # Agencies with evidence plus supported sources
│   └── [agency_id]/page.tsx   # Agency dossier or ingestion handoff
├── dockets/
│   └── [docket_id]/page.tsx   # Docket evidence dossier or config handoff
├── analyze/
│   └── page.tsx               # Advanced pipeline config manual workflow
├── discoveries/
│   └── page.tsx               # Autopilot discovered rulemaking candidates
├── watchlist/
│   └── page.tsx               # Interactive watchlist monitor configurations
├── monitor/
│   └── page.tsx               # System Pipeline Monitor dashboard
├── campaign/
│   └── [cluster_id]/page.tsx  # Dynamic campaign/cluster dossier
└── api/
    ├── stats/route.ts
    ├── watchlist/route.ts
    ├── discoveries/route.ts
    └── clusters/
        ├── route.ts
        └── [cluster_id]/route.ts
```

## MVP Coverage Policy

Primary navigation only shows topics and agencies with real product value.

| State | UI treatment | Current examples |
| --- | --- | --- |
| `analyzed` | Prominent topic, agency, docket, and campaign pages with semantic analysis and validation status. | Telecom / Net Neutrality, FCC `17-108` |
| `baseline_only` | Visible topic/docket with exact-hash metrics, partial-processing labels, and the next semantic command. | Climate / Oil & Gas / Methane, EPA `EPA-HQ-OAR-2021-0317` |
| `ingestion_ready` | Action path or template that generates `configs/dockets.yaml` snippets and commands. | `/analyze`, CFPB/FTC/SEC templates |
| `hidden` | Excluded from primary navigation. Direct routes hand off to Analyze when metadata exists. | Healthcare, Labor, other future sectors |

The user should never land on a polished page with only zero counts. If data
exists, the UI shows analysis. If partial data exists, it labels the processing
stage. If no data exists, it helps the user start ingestion.

## Seed Data & Hydration

`ui/lib/fallback-data.ts` is the single source of truth for frontend metadata:

- `Topic`: sector metadata, dockets, coverage state, and visibility.
- `Agency`: agency metadata, supported-source status, and visibility.
- `Docket`: rulemaking metadata, validation summaries, and next-step commands.
- `CoverageStatus`: `analyzed`, `baseline_only`, `ingestion_ready`, or `hidden`.

The UI's `CoverageStatus` is a separate vocabulary from the backend
`processing_status` enforced in
[`scripts/run_docket_pipeline.py`](../scripts/run_docket_pipeline.py)
(`ALLOWED_PROCESSING_STATUSES`). They map as follows:

| Backend `processing_status` | UI `CoverageStatus` | UI label |
| --- | --- | --- |
| `analyzed` | `analyzed` | "Analyzed" |
| `partially_processed` / `baseline_only` | `baseline_only` | "Partially processed" / "Baseline only" |
| `configured_awaiting_run` / `queued` | `ingestion_ready` | "Configured, awaiting run" / "Queued" |
| (none) | `hidden` | (not displayed) |

The backend list is canonical; the UI list is what gets rendered. New
backend statuses do not require a UI change unless we want a new tier.

Data hydration works as follows:

1. FCC `17-108` calls `getStatsPayload()` and `getClustersSummary()` to retrieve
   semantic cluster output from Databricks SQL or fallback artifacts.
2. EPA `EPA-HQ-OAR-2021-0317` renders exact-hash baseline clusters and states
   that semantic clustering is queued.
3. Configured-but-unprocessed dockets route to `/analyze` instead of rendering
   zero campaign dashboards.

## Global Search

`ui/components/search-autocomplete.tsx` searches topics, agencies, dockets, and
campaigns while respecting coverage visibility:

- `net neutrality` returns the real FCC `17-108` topic/docket/campaign surfaces.
- `FCC` returns the FCC agency with analyzed evidence.
- `methane` or `EPA` returns baseline-only EPA coverage.
- `AI regulation` returns the Analyze workflow for an ingestion template.
- Unknown queries return "No analyzed docket yet" and route to `/analyze?query=...`.

Search should not return dead placeholder pages.
