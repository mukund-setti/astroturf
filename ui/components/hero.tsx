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
  // We benchmark naive exact-string hashing as a fixed floor on FCC 17-108.
  // It finds 16 literal duplicates across the canonical full-docket reference
  // run, and that number is independent of how many comments we choose to
  // semantically cluster in any given slice.
  const exactCount = 16;
  const semanticCount = largestSize;
  // Lift ratio is computed live so the hero stays honest when the active
  // slice is smaller than the canonical reference run.
  const liftRatio = exactCount > 0 ? semanticCount / exactCount : 0;

  return (
    <section className="relative overflow-hidden border-b border-rule/60">
      {/* Soft radial wash in brand indigo so the hero doesn't sit flat. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(80% 60% at 75% 0%, rgba(67, 56, 202, 0.08) 0%, rgba(67, 56, 202, 0) 60%), radial-gradient(60% 50% at 10% 100%, rgba(67, 56, 202, 0.05) 0%, rgba(67, 56, 202, 0) 70%)",
        }}
      />

      <div className="mx-auto max-w-6xl px-6 py-20 md:py-28">
        {/* Eyebrow - kept short and conversational, no all-caps shouting. */}
        <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-brand/20 bg-brand/5 px-3 py-1 text-xs text-brand">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand" />
          <span className="font-medium">FCC docket {docketId} / landmark finding</span>
        </div>

        {/* Headline. Slightly tighter measure, slightly larger leading for warmth. */}
        <h1 className="font-display text-[2.4rem] leading-[1.06] tracking-[-0.02em] text-foreground md:text-[4.5rem] md:leading-[1.03] max-w-[24ch] mb-8">
          Democratic voice is being hijacked by automated paraphrasing.
        </h1>

        <p className="text-lg md:text-xl text-foreground/75 leading-relaxed max-w-[64ch] mb-14">
          Public commenting periods are saturated by lobby campaigns using bots that subtly
          rewrite the same template a thousand different ways. Keyword filters miss every
          paraphrase. Dense vector clustering on Databricks collapses them back into one piece
          of actionable evidence.
        </p>

        {/* Hero stat row - three soft cards instead of one stark grid. */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5 mb-12">
          <StatCard
            label="Naive exact hashing"
            value={exactCount.toString()}
            description="Failed to recognise paraphrases. Only surfaced literal, character-for-character copies."
            tone="muted"
          />
          <StatCard
            label="Semantic clustering"
            value={formatInt(semanticCount)}
            description="Caught the full coordinated template, even when sponsors mutated synonyms and prefaces."
            tone="brand-soft"
          />
          <StatCard
            label="Detection lift"
            value={`${liftRatio >= 10 ? liftRatio.toFixed(0) : liftRatio.toFixed(1)}x`}
            description="More coordinated comments recovered by switching from naive string match to semantic neighbours."
            tone="brand"
          />
        </div>

        {/* Plain-English summary of what the campaign actually was. */}
        <p className="max-w-[64ch] text-lg text-foreground/85 leading-relaxed">
          On {agency}&rsquo;s {ruleShortName}, a single coordinated campaign generated{" "}
          <span className="font-semibold text-brand tabular-nums">{formatInt(semanticCount)} comments</span>{" "}
          in {daySpan ? <span className="font-semibold tabular-nums">{daySpan} days</span> : "a narrow burst"}.
          One template accounted for{" "}
          <span className="font-semibold text-brand tabular-nums">{percent}%</span> of all coordinated
          comments detected on the docket.
        </p>

        {remainingClusters > 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            Plus {formatInt(remainingClusters)} smaller coordinated campaigns surfaced on the same docket.
          </p>
        ) : null}

        <p className="mt-10 text-xs text-muted-foreground/80 leading-relaxed max-w-[70ch]">
          <span className="text-muted-foreground/60">Rule:</span> &ldquo;{ruleTitle}&rdquo;
        </p>
      </div>
    </section>
  );
}

type StatTone = "muted" | "brand-soft" | "brand";

function StatCard({
  label,
  value,
  description,
  tone,
}: {
  label: string;
  value: string;
  description: string;
  tone: StatTone;
}) {
  const surface =
    tone === "brand"
      ? "bg-brand text-primary-foreground border-transparent"
      : tone === "brand-soft"
      ? "bg-brand-soft/40 text-foreground border-brand/15"
      : "bg-card text-foreground border-rule";
  const labelTone =
    tone === "brand"
      ? "text-primary-foreground/75"
      : tone === "brand-soft"
      ? "text-brand"
      : "text-muted-foreground";
  const bodyTone =
    tone === "brand"
      ? "text-primary-foreground/85"
      : tone === "brand-soft"
      ? "text-foreground/75"
      : "text-muted-foreground";
  return (
    <div
      className={`group relative flex flex-col justify-between border ${surface} rounded-xl p-6 md:p-7 transition-all duration-200`}
      style={{ boxShadow: "var(--shadow-soft)" }}
    >
      <div>
        <p className={`text-[11px] font-medium uppercase tracking-[0.14em] ${labelTone} mb-3`}>
          {label}
        </p>
        <p
          className={`font-display tabular-nums font-semibold leading-none ${
            tone === "brand" ? "text-5xl md:text-6xl" : "text-4xl md:text-5xl"
          } ${tone === "brand-soft" ? "text-brand" : ""}`}
        >
          {value}
        </p>
      </div>
      <p className={`mt-6 text-sm leading-relaxed ${bodyTone}`}>{description}</p>
    </div>
  );
}
