export function ReviewerDemoFlow() {
  const steps = [
    {
      num: "01",
      name: "IngestionAgent",
      role: "Multi-Source Puller",
      desc: "Fetches comments via ECFS/Regulations.gov APIs. Overwrites raw comments onto bronze Delta tables on unique keys.",
    },
    {
      num: "02",
      name: "ParserAgent",
      role: "Metadata Extractor",
      desc: "Segregates inline bodies, enriches comment details, catalogs scanned attachment binaries, and flags boilerplate covers.",
    },
    {
      num: "03",
      name: "EmbeddingAgent",
      role: "Vectorizer Node",
      desc: "Distributes batch text blocks across Spark nodes. Encodes comments into 1024-dim dense vectors using BGE-large.",
    },
    {
      num: "04",
      name: "ClusteringAgent",
      role: "Vector Search Solver",
      desc: "Triggers distributed Vector Search (HNSW) nearest-neighbor indexes. Performs cosine grouping above a stable threshold (0.92).",
    },
    {
      num: "05",
      name: "AttributionAgent",
      role: "Web Search Tool",
      desc: "Delegates to LLMs to perform automated Google/Lobby registry searches to attribute clusters to corporate/lobby groups.",
    },
    {
      num: "06",
      name: "MigrationAgent",
      role: "Final Rule Tracer",
      desc: "Extracts regulatory text from the Federal Register. Computes phrase-level similarity to trace template language into final laws.",
    },
  ];

  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-20">
        {/* Header */}
        <div className="mb-12">
          <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
            PIPELINE FLOW
          </span>
          <h2 className="font-display text-2xl md:text-3xl text-foreground font-semibold mt-4">
            The Multi-Agent Medallion Sequence
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed mt-2 max-w-[80ch]">
            Astroturf processes data through six independent, idempotent agents. Delta Lake tables serve as the 
            durable state machine connecting agents, while MLflow tracks run provenance.
          </p>
        </div>

        {/* Steps Grid */}
        <div className="grid grid-cols-1 md:grid-cols-6 gap-6">
          {steps.map((step, idx) => (
            <div key={idx} className="flex flex-col border-t border-rule pt-6">
              <span className="font-mono text-3xl font-bold text-brand/30 leading-none mb-2 tabular-nums">
                {step.num}
              </span>
              <h4 className="font-display text-base font-semibold text-foreground leading-tight">
                {step.name}
              </h4>
              <span className="text-[10px] font-sans uppercase tracking-wider text-muted-foreground mb-3 block">
                {step.role}
              </span>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {step.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
