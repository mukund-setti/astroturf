export function WhyDatabricksSection() {
  const cards = [
    {
      title: "Delta Lake Tables",
      bottleneck: "Interrupted Ingestion & Re-run Drift",
      solution:
        "ACID-compliant transactions and idempotent writes via Delta MERGE. Guarantee that backfills, API timeouts, or re-runs results in zero duplicate rows and zero catalog corruption.",
      icon: "💾",
    },
    {
      title: "Distributed Vector Search",
      bottleneck: "O(N²) Pairwise Space Explosion",
      solution:
        "Bypasses contiguous float32 similarity matrices. Indexes silver embeddings into a managed, distributed HNSW index, reducing query complexity to sub-quadratic O(N log N) scaling.",
      icon: "🔍",
    },
    {
      title: "MLflow Audit Trails",
      bottleneck: "Unverifiable Regulation Proof & Bias",
      solution:
        "Logs full execution run history, parameters (threshold bounds, exact versions), metrics, and quality receipts. Establishes a compliant regulatory pedigree open to scrutiny.",
      icon: "📋",
    },
    {
      title: "Distributed Embeddings",
      bottleneck: "GPU Throttling & PyTorch CPU Walls",
      solution:
        "Scales processing across serverless Spark nodes driving parallel requests to Foundation Model endpoints (BGE-large) while managing API rate limits and retries automatically.",
      icon: "⚡",
    },
    {
      title: "Unity Catalog",
      bottleneck: "PII Leaks & Secure Citizen Isolation",
      solution:
        "Implements strict columns-level RBAC filters. Allows researchers to cluster and analyze coordinated comments without exposing sensitive names, emails, or phone numbers.",
      icon: "🛡️",
    },
  ];

  return (
    <section className="border-b border-rule bg-secondary/20">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-20">
        {/* Section Header */}
        <div className="text-center max-w-[70ch] mx-auto mb-16">
          <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
            INFRASTRUCTURE CORE
          </span>
          <h2 className="font-display text-3xl md:text-4xl text-foreground font-semibold mt-4 mb-4">
            Why Databricks is Load-Bearing
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Astroturf is not just a local script in an agent costume. True public-voice coordination tracing 
            requires high-throughput, highly resilient cloud architecture. Here is how we map benchmarks to solutions:
          </p>
        </div>

        {/* Feature Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {cards.map((card, idx) => (
            <div
              key={idx}
              className="border border-rule bg-card p-6 rounded-sm flex flex-col justify-between hover:border-foreground/20 transition-colors shadow-none"
            >
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-2xl">{card.icon}</span>
                  <h4 className="font-display text-lg text-foreground font-medium">
                    {card.title}
                  </h4>
                </div>

                <div className="mb-4">
                  <span className="text-[9px] font-sans uppercase tracking-wider text-destructive font-medium block">
                    Benchmarked Bottleneck
                  </span>
                  <p className="text-xs font-mono text-destructive leading-snug font-medium">
                    {card.bottleneck}
                  </p>
                </div>

                <div>
                  <span className="text-[9px] font-sans uppercase tracking-wider text-brand font-medium block">
                    Databricks Solution
                  </span>
                  <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">
                    {card.solution}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
