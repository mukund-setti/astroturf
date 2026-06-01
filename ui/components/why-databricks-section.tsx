import { Database, Sparkles, Network, Workflow, ScrollText, PlugZap, type LucideIcon } from "lucide-react";

export function WhyDatabricksSection() {
  const cards: Array<{
    title: string;
    bottleneck: string;
    solution: React.ReactNode;
    Icon: LucideIcon;
  }> = [
    {
      title: "Delta Lake + Unity Catalog",
      bottleneck: "Interrupted ingestion / re-run drift",
      solution:
        "Every one of the six agents writes through Delta MERGE on a stable primary key. ACID transactions guarantee that 87-minute ECFS slices, mid-rate-limit retries, and partial-failure replays all converge to the same idempotent bronze/silver/gold tables. Unity Catalog adds column-level RBAC for PII isolation.",
      Icon: Database,
    },
    {
      title: "Foundation Model API",
      bottleneck: "Self-hosted embedding model ops",
      solution: (
        <>
          1024-d semantic embeddings via{" "}
          <code className="font-mono text-foreground">databricks-bge-large-en</code>{" "}
          served from a managed endpoint. No GPU pool to provision, no PyTorch
          containers to keep warm, no quantization to debug - just a billed
          request per comment with automatic retries and rate-limit shaping
          inside the EmbeddingAgent backend.
        </>
      ),
      Icon: Sparkles,
    },
    {
      title: "Vector Search",
      bottleneck: "O(N^2) pairwise comparison wall",
      solution:
        "MinHash/LSH generates candidate pairs cheaply, then Vector Search confirms semantic neighbors over an HNSW index synced from the silver embeddings Delta table. Cluster confirmation drops from a contiguous float32 similarity matrix to a sub-quadratic index lookup, so the pipeline stays linear in docket size.",
      Icon: Network,
    },
    {
      title: "Workflows / Jobs",
      bottleneck: "Notebook-as-orchestrator anti-pattern",
      solution: (
        <>
          The whole 5-stage pipeline runs as a parameterized Databricks Job:{" "}
          <code className="font-mono text-foreground">job_id</code> + per-docket{" "}
          <code className="font-mono text-foreground">request_id</code> +
          base_parameters for catalog, data_root, and clustering mode.
          Submission, lifecycle, retries, and the per-stage zero-row guards all
          live inside the Job, called from the Next.js{" "}
          <code className="font-mono text-foreground">/analyze</code> endpoint.
        </>
      ),
      Icon: Workflow,
    },
    {
      title: "MLflow audit trails",
      bottleneck: "Unverifiable regulatory provenance",
      solution:
        "Each agent emits an MLflow run with inputs (docket_id, source, config), outputs (per-stage row counts, quality metrics), and timing. Threshold bounds, exact model versions, and rate-limit budget consumption are all reconstructable from the experiment - required pedigree for any downstream regulatory citation.",
      Icon: ScrollText,
    },
    {
      title: "Databricks SQL Connector",
      bottleneck: "Mock data divergence in the UI",
      solution: (
        <>
          The Next.js UI queries the actual Delta tables (via{" "}
          <code className="font-mono text-foreground">delta.`/Volumes/.../path`</code>{" "}
          and the SQL warehouse) for cluster_review_export, per-stage row
          counts, and Delta history. Zero mock data in the production path - 
          when the live counts disagree with what the page shows, the page is
          wrong, not the warehouse.
        </>
      ),
      Icon: PlugZap,
    },
  ];

  return (
    <section className="relative border-b border-rule/60 bg-secondary/30">
      <div className="mx-auto max-w-6xl px-6 py-20 md:py-24">
        {/* Section Header - left-aligned, conversational, no shouting badge. */}
        <div className="max-w-[60ch] mb-14">
          <p className="text-sm text-brand font-medium mb-3">The infrastructure</p>
          <h2 className="font-display text-3xl md:text-5xl text-foreground tracking-tight leading-[1.05]">
            Why Databricks is load-bearing.
          </h2>
          <p className="mt-5 text-base md:text-lg text-foreground/70 leading-relaxed">
            Each of the six agents leans on a specific Databricks capability. Pull any of these
            out and the pipeline either stops scaling, stops being reproducible, or stops being
            safe to put in front of a regulator.
          </p>
        </div>

        {/* Feature Grid - two columns on desktop for breathing room. */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {cards.map((card, idx) => {
            const { Icon } = card;
            return (
              <div
                key={idx}
                className="group relative flex flex-col justify-between rounded-xl border border-rule/70 bg-card p-7 md:p-8 transition-all duration-200 hover:-translate-y-0.5 shadow-[var(--shadow-soft)] hover:shadow-[var(--shadow-soft-hover)]"
              >
                <div>
                  <div className="flex items-start gap-3.5 mb-5">
                    <span
                      aria-hidden="true"
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand"
                    >
                      <Icon className="h-5 w-5" strokeWidth={1.75} />
                    </span>
                    <h4 className="font-display text-xl md:text-2xl text-foreground font-semibold leading-tight pt-1.5">
                      {card.title}
                    </h4>
                  </div>

                  <div className="mb-5 flex items-baseline gap-2">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-destructive/70 translate-y-[-2px]" />
                    <p className="text-sm text-destructive/90 font-medium leading-snug">
                      {card.bottleneck}
                    </p>
                  </div>

                  <p className="text-sm text-foreground/75 leading-relaxed">
                    {card.solution}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
