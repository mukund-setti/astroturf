import type { ReactNode } from "react";

interface Step {
  title: string;
  body: ReactNode;
}

const STEPS: Step[] = [
  {
    title: "Ingest",
    body: (
      <>
        Public comments are pulled from{" "}
        <strong className="text-foreground">two federal sources</strong>:
        regulations.gov v4 (CFPB, EPA, FTC, FDA, ...) and the FCC ECFS public
        API (telecom dockets). Cursor-based pagination, exponential-backoff
        retries, and a shared <code className="font-mono text-[0.95em] text-foreground">api.data.gov</code>{" "}
        rate-limit budget. Data lands in a Delta Lake bronze table on
        Databricks Unity Catalog with full provenance, idempotent re-runs,
        and an MLflow run per ingestion.
      </>
    ),
  },
  {
    title: "Parse and enrich",
    body: (
      <>
        Comments are normalized through a medallion architecture (bronze to
        silver). HTML cleaning, attachment cataloging, and detail-level
        enrichment run as a Databricks Workflow, source-aware: ECFS rows
        skip the detail-fetch round-trip because their bodies are already
        plain text, while regulations.gov rows fan out per-comment detail
        requests under the rate-limit budget.
      </>
    ),
  },
  {
    title: "Embed",
    body: (
      <>
        Each comment is converted to a 1024-dimension semantic embedding via{" "}
        <code className="font-mono text-[0.95em] text-foreground">
          databricks-bge-large-en
        </code>
        , served through the Databricks Foundation Model API. Embeddings are
        written to a Delta table and synced to a Databricks Vector Search
        index.
      </>
    ),
  },
  {
    title: "Cluster",
    body: (
      <>
        A two-stage clusterer collapses the {" "}
        <code className="font-mono text-[0.95em] text-foreground">O(N^2)</code>{" "}
        comparison space: <strong className="text-foreground">MinHash/LSH</strong>{" "}
        on token shingles generates candidate pairs; cosine similarity over
        the Vector Search index confirms semantic neighbors above a tunable
        threshold (default 0.92). Cluster assignments and representative
        templates land in gold Delta tables, joined with cluster sizes and
        date spans for the UI.
      </>
    ),
  },
  {
    title: "Attribute and trace",
    body: (
      <>
        Two evidence-packet agents read from gold: the{" "}
        <strong className="text-foreground">AttributionAgent</strong> assembles
        candidate campaign sponsors from a curated advocacy registry
        (offline-seed today; tool-using LLM mode behind an ADR), and the{" "}
        <strong className="text-foreground">MigrationAgent</strong> compares
        cluster template language against the final agency rule text to
        flag phrase-level migration. Both write capped-confidence,
        caveat-bearing rows - never silent accusations.
      </>
    ),
  },
  {
    title: "Serve",
    body: (
      <>
        Findings are denormalized into{" "}
        <code className="font-mono text-[0.95em] text-foreground">
          astroturf.demo.cluster_review_export
        </code>{" "}
        and queried live from this Next.js UI via the Databricks SQL Connector.
        A Postgres control plane (Supabase) tracks analysis-request lifecycle,
        Databricks job IDs, and source-validated docket discoveries so the UI
        can poll{" "}
        <code className="font-mono text-[0.95em] text-foreground">
          /api/analysis/[id]/progress
        </code>{" "}
        every 10s with per-stage row counts.
      </>
    ),
  },
];

export function HowItWorks() {
  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-24">
        <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-4">
          The pipeline
        </p>
        <h2 className="font-display text-3xl md:text-5xl tracking-tight text-foreground leading-tight">
          How it works
        </h2>

        <ol className="mt-12 md:mt-16 space-y-12 md:space-y-14 max-w-3xl">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className="grid grid-cols-[auto_1fr] gap-x-6 md:gap-x-10 items-start"
            >
              <span
                className="font-display tabular-nums text-brand leading-none text-4xl md:text-5xl select-none"
                aria-hidden="true"
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <div>
                <h3 className="font-display text-xl md:text-2xl tracking-tight text-foreground">
                  {step.title}
                </h3>
                <p className="mt-3 text-base md:text-lg text-foreground/90 leading-relaxed">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
