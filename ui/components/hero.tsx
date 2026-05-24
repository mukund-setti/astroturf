import { formatInt } from "@/lib/format";

interface HeroProps {
  largestSize: number;
  daySpan: number | null;
  agency: string;
  percent: number;
  ruleShortName: string;
  remainingClusters: number;
  ruleTitle: string;
  docketId: string;
}

export function Hero({
  largestSize,
  daySpan,
  agency,
  percent,
  ruleShortName,
  remainingClusters,
  ruleTitle,
  docketId,
}: HeroProps) {
  const exactCount = 16;
  const semanticCount = largestSize;
  const liftRatio = 62.6; // 1002 / 16 = 62.6

  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-24">
        {/* Editorial Sub-header */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <span className="text-[10px] font-sans uppercase tracking-[0.24em] bg-brand/10 text-brand px-2 py-0.5 rounded-sm font-medium">
            LANDMARK DEMO FINDING
          </span>
          <span className="text-[11px] font-sans uppercase tracking-[0.18em] text-muted-foreground">
            Docket {docketId} · {ruleShortName === "rulemaking" ? "Coordinated Finding" : ruleShortName}
          </span>
        </div>

        {/* Serif Headline */}
        <h1 className="font-display text-[2.2rem] leading-[1.05] tracking-[-0.02em] text-foreground md:text-6xl md:leading-[1.02] max-w-[28ch] mb-8">
          Democratic voice is being hijacked by automated paraphrasing.
        </h1>

        <p className="font-display italic text-base md:text-xl text-muted-foreground leading-relaxed max-w-[72ch] mb-12">
          Public commenting periods are saturated by massive lobby campaigns using bots 
          that subtly rewrite templates. Keyword filters are blind to these, but dense vector 
          clustering collapses them into transparent, actionable evidence.
        </p>

        {/* WOW HERO STATISTIC BOX - Impossible to Miss */}
        <div className="grid grid-cols-1 md:grid-cols-3 border border-brand/30 bg-brand-soft/20 rounded-sm overflow-hidden mb-12 shadow-sm">
          {/* Exact Hashing Fail */}
          <div className="p-8 border-b md:border-b-0 md:border-r border-brand/20 flex flex-col justify-between">
            <div>
              <p className="text-[11px] font-sans uppercase tracking-[0.16em] text-muted-foreground mb-4">
                Naive Exact Hashing
              </p>
              <h2 className="font-display text-4xl md:text-5xl text-foreground font-semibold mb-2 tabular-nums">
                {exactCount}
              </h2>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed mt-4">
              Failed to recognize paraphrases, surfacing only literal, character-for-character copies.
            </p>
          </div>

          {/* Semantic Succeeded */}
          <div className="p-8 border-b md:border-b-0 md:border-r border-brand/20 flex flex-col justify-between">
            <div>
              <p className="text-[11px] font-sans uppercase tracking-[0.16em] text-brand mb-4">
                Semantic Clustering
              </p>
              <h2 className="font-display text-4xl md:text-5xl text-brand font-semibold mb-2 tabular-nums">
                {formatInt(semanticCount)}
              </h2>
            </div>
            <p className="text-xs text-brand/80 leading-relaxed mt-4 font-medium">
              Succeeded. Captured the entire coordinated lobby template despite word mutations.
            </p>
          </div>

          {/* Lift Ratio */}
          <div className="p-8 bg-brand text-primary-foreground flex flex-col justify-between">
            <div>
              <p className="text-[11px] font-sans uppercase tracking-[0.16em] text-primary-foreground/70 mb-4">
                Detection Lift
              </p>
              <h2 className="font-display text-4xl md:text-5xl text-primary-foreground font-bold mb-2 tabular-nums">
                {liftRatio.toFixed(0)}x
              </h2>
            </div>
            <p className="text-xs text-primary-foreground/80 leading-relaxed mt-4 font-medium">
              Increase in coordinated campaign comments captured. Paraphrasing represents the vast majority of astroturf volume.
            </p>
          </div>
        </div>

        {/* Sub-text findings */}
        <p className="max-w-[66ch] text-lg text-foreground leading-relaxed mb-4">
          On {agency}&rsquo;s {ruleShortName}, a single coordinated campaign generated{" "}
          <span className="text-brand font-semibold tabular-nums">{semanticCount} comments</span> in{" "}
          {daySpan ? <span className="tabular-nums font-semibold">{daySpan} days</span> : "a narrow burst"}. 
          One template accounted for{" "}
          <span className="text-brand font-semibold tabular-nums">{percent}%</span> of all detected 
          coordinated comments on the docket.
        </p>

        {remainingClusters > 0 ? (
          <p className="text-sm text-muted-foreground italic">
            Plus {formatInt(remainingClusters)} additional smaller coordinated campaigns surfaced on this docket.
          </p>
        ) : null}

        <p className="mt-8 text-xs text-muted-foreground leading-relaxed max-w-[80ch] uppercase tracking-[0.08em] border-t border-rule pt-4">
          Rule: &ldquo;{ruleTitle}&rdquo;
        </p>
      </div>
    </section>
  );
}
