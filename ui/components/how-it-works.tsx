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
        Public comments are pulled from regulations.gov via the official API,
        with cursor-based pagination and exponential-backoff retries. Data
        lands in a Delta Lake bronze table on Databricks Unity Catalog, with
        full provenance and idempotent re-runs.
      </>
    ),
  },
  {
    title: "Parse and enrich",
    body: (
      <>
        Comments are normalized through a medallion architecture (bronze to
        silver). HTML cleaning, attachment cataloging, and detail-level
        enrichment use Databricks Workflows for orchestration.
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
        Pairwise cosine similarity over the Vector Search index identifies
        clusters of textually similar comments above a tunable threshold.
        Cluster assignments and template comments are written to gold Delta
        tables.
      </>
    ),
  },
  {
    title: "Serve",
    body: (
      <>
        Findings are exported to{" "}
        <code className="font-mono text-[0.95em] text-foreground">
          workspace.demo.cluster_review_export
        </code>{" "}
        and queried live from this UI via the Databricks SQL Connector.
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
