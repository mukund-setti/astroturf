export function LimitationsSection() {
  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-20">
        <div className="mb-10">
          <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
            RIGOR &amp; TRANSPARENCY
          </span>
          <h2 className="font-display text-2xl md:text-3xl text-foreground font-semibold mt-4">
            Methodological Bounds &amp; Limitations
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed mt-2 max-w-[80ch]">
            An honest representation of AI data pipelines requires clear documentation of scientific limits. 
            Here are the primary analytical constraints of the current Astroturf iteration:
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Limitation 1 */}
          <div className="p-5 border border-rule bg-card rounded-sm flex flex-col justify-between shadow-none">
            <div>
              <h4 className="font-display text-base font-semibold text-foreground mb-3">
                1. Temporal Horizon Slicing
              </h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Our active local case study evaluates public comments submitted within a narrow 3-day window 
                (August 28 to August 30, 2017). Coordinated campaign waves are wider; this temporal slice 
                efficiently captures the major filing burst but underrepresents the full absolute campaign volumes.
              </p>
            </div>
            <span className="text-[10px] font-mono text-brand mt-4 block">Bound: Data Scope Slice</span>
          </div>

          {/* Limitation 2 */}
          <div className="p-5 border border-rule bg-card rounded-sm flex flex-col justify-between shadow-none">
            <div>
              <h4 className="font-display text-base font-semibold text-foreground mb-3">
                2. Cosine Threshold Sensitivity
              </h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The clustering agent operates under a fixed cosine similarity threshold of **`0.92`** over BGE embeddings. 
                While this is highly optimized, citizens who add extensive personal paragraphs or heavily customize 
                prefaces will fall below this threshold (false negatives), showing that coordination is a spectrum.
              </p>
            </div>
            <span className="text-[10px] font-mono text-brand mt-4 block">Bound: Semantic Cutoff Bound</span>
          </div>

          {/* Limitation 3 */}
          <div className="p-5 border border-rule bg-card rounded-sm flex flex-col justify-between shadow-none">
            <div>
              <h4 className="font-display text-base font-semibold text-foreground mb-3">
                3. Astroturf vs. Allowed Advocacy
              </h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The system groups highly similar template text, but semantic grouping alone cannot distinguish 
                permitted civic bulk advocacy (e.g. authorized petitions compiled by advocacy groups) from 
                malicious identity hijacking without checking external lobby registries and authorization audits.
              </p>
            </div>
            <span className="text-[10px] font-mono text-brand mt-4 block">Bound: Intent Attribution Bound</span>
          </div>
        </div>
      </div>
    </section>
  );
}
