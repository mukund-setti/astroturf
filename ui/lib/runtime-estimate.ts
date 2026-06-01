/**
 * Runtime estimator for a hosted analysis pipeline run.
 *
 * Cost model originally calibrated 2026-05-25 from the live 14-28 ECFS
 * run, when the bottleneck was the delta-rs FUSE bypass (O(table_size)
 * rmtree + copytree on every page write - see ADR-0017). After H1 swapped
 * that writer for native Spark MERGE, ingestion rates jumped from ~250
 * rows/min to (expected) several thousand rows/min, so these constants
 * are due for recalibration once we have post-H1 observations (tracked
 * by S5 in the production-blocker plan).
 *
 * regs.gov per-comment detail fetches remain gated by api.data.gov at
 * 1,000 req/hour; that's an upstream constraint unchanged by H1.
 *
 * The model is deliberately conservative - better to over-estimate the
 * initial quote and let the live run's `projectFromObservation()` revise
 * it downward as data comes in than to promise a 25-min run that takes
 * 90 min. Treat returned numbers as order-of-magnitude guidance.
 */

export type AnalysisSource = "regulations_gov" | "ecfs";

export interface RuntimeEstimate {
  totalMinutes: number;
  stageMinutes: {
    setup: number;
    ingestion: number;
    parsing: number;
    embedding: number;
    clustering: number;
    export: number;
  };
  bottleneckStage: keyof RuntimeEstimate["stageMinutes"];
  bottleneckReason: string;
  warnings: string[];
}

// Setup is dominated by Databricks Serverless cold start + warehouse spin,
// which is consistently ~3-4 min in the runs we've observed. We bake it into
// every quoted total so the user isn't surprised by 4 min of "nothing
// happening" right after submission.
const SETUP_MINUTES = 4;
// Clustering with vector_search is approximately scale-independent: index
// sync + nearest-neighbour scan + write back. ~4 min is a safe upper bound
// on the runs we've seen.
const CLUSTERING_MINUTES = 4;
// Export materializes the demo table from gold. Sub-minute on small runs,
// budget 2 to be safe.
const EXPORT_MINUTES = 2;

// Per-source per-stage rates expressed in rows/min. These reflect *steady-
// state* throughput observed live, not a theoretical maximum. They include
// the FUSE bypass overhead which dominates write-side stages on Databricks
// Serverless. Tighter values are better extracted at runtime via
// `projectFromObservation()` once enough data exists.
const STAGE_RATES: Record<
  AnalysisSource,
  { ingestion: number; parsing: number; embedding: number }
> = {
  regulations_gov: {
    // ~250 rows/min steady-state ingestion for the same FUSE-bypass reason
    // as ECFS. Earlier ~480 estimate was based on a small slice without
    // the linear-cost decay kicking in.
    ingestion: 250,
    parsing: 17, // api.data.gov 1000 req/hour cap, dominant cost
    embedding: 1200,
  },
  ecfs: {
    // Calibrated from 14-28 live run: 5,250 rows in ~22 min (after a ~2 min
    // cold start) = ~240 rows/min effective. Rounded down to be safe.
    ingestion: 220,
    parsing: 4000, // ECFS list response carries full text, no detail fetch
    embedding: 1200,
  },
};

export function estimateRuntime(
  source: AnalysisSource,
  expectedScale: number,
): RuntimeEstimate {
  const scale = Math.max(1, Math.floor(expectedScale));
  const rates = STAGE_RATES[source];

  const ingestion = scale / rates.ingestion;
  const parsing = scale / rates.parsing;
  const embedding = scale / rates.embedding;

  const stageMinutes = {
    setup: SETUP_MINUTES,
    ingestion: round1(ingestion),
    parsing: round1(parsing),
    embedding: round1(embedding),
    clustering: CLUSTERING_MINUTES,
    export: EXPORT_MINUTES,
  };

  const totalMinutes = Math.round(
    stageMinutes.setup +
      stageMinutes.ingestion +
      stageMinutes.parsing +
      stageMinutes.embedding +
      stageMinutes.clustering +
      stageMinutes.export,
  );

  const bottleneckStage = (
    Object.entries(stageMinutes) as [
      keyof RuntimeEstimate["stageMinutes"],
      number,
    ][]
  ).reduce(
    (acc, [k, v]) => (v > acc.v ? { k, v } : acc),
    {
      k: "setup" as keyof RuntimeEstimate["stageMinutes"],
      v: 0,
    },
  ).k;

  const bottleneckReason = explainBottleneck(source, bottleneckStage);

  const warnings: string[] = [];
  if (source === "regulations_gov" && scale >= 5000) {
    warnings.push(
      `regulations.gov parsing is rate-limited at api.data.gov (1000 req/hr). ${scale.toLocaleString()} comments -> at least ${Math.ceil(scale / 1000)}h just for stage 2 detail fetches. Consider starting smaller or splitting the run.`,
    );
  }
  if (totalMinutes >= 120) {
    warnings.push(
      "Runs over 2 hours are higher risk: a cluster restart or transient failure can lose in-flight parser work because the current ParserAgent doesn't checkpoint mid-loop.",
    );
  }

  return {
    totalMinutes,
    stageMinutes,
    bottleneckStage,
    bottleneckReason,
    warnings,
  };
}

/**
 * Re-project total runtime from a live run's observed progress.
 *
 * Called by the auto-polling progress component every poll. As the run
 * accumulates rows, `progressFraction` becomes a more reliable signal of
 * how far through the work we are than the up-front rates. We blend:
 *
 *  - The original quoted ETA (used at request time)
 *  - The naive projection: elapsed / progressFraction = total
 *
 * weighted toward the projection as we get more confident in it (i.e. as
 * progressFraction grows). Below a 5% threshold we don't trust the
 * projection at all because cold-start noise dominates.
 *
 * The returned value is intentionally always >= elapsed: even when the run
 * is clearly going to finish quickly, the displayed total never shrinks
 * below "where we are now", which would be confusing.
 */
export function projectFromObservation(
  elapsedMinutes: number,
  progressFraction: number,
  initialEtaMinutes: number,
): { projectedMinutes: number; confidence: "low" | "medium" | "high" } {
  if (progressFraction < 0.05 || elapsedMinutes < 0.5) {
    return { projectedMinutes: initialEtaMinutes, confidence: "low" };
  }
  const naiveTotal = elapsedMinutes / progressFraction;
  // weight grows from 0 at frac=0.05 to 1 at frac=0.40
  const weight = Math.min(1, Math.max(0, (progressFraction - 0.05) / 0.35));
  const projected = initialEtaMinutes * (1 - weight) + naiveTotal * weight;
  // Clamp so the displayed total is always at least as long as elapsed.
  const projectedMinutes = Math.max(elapsedMinutes, projected);
  const confidence: "low" | "medium" | "high" =
    progressFraction >= 0.4 ? "high" : progressFraction >= 0.15 ? "medium" : "low";
  return { projectedMinutes, confidence };
}

export function formatRuntime(totalMinutes: number): string {
  if (totalMinutes < 1) return "under 1 min";
  if (totalMinutes < 60) return `~${Math.round(totalMinutes)} min`;
  const hours = totalMinutes / 60;
  if (hours < 10) return `~${round1(hours)} hr`;
  return `~${Math.round(hours)} hr`;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function explainBottleneck(
  source: AnalysisSource,
  stage: keyof RuntimeEstimate["stageMinutes"],
): string {
  if (stage === "parsing" && source === "regulations_gov") {
    return "Stage 2 sequentially fetches one detail page per comment from regulations.gov, capped at ~1000 req/hour by api.data.gov.";
  }
  if (stage === "ingestion") {
    return "Stage 1 paginates the source API and writes each page to a FUSE-backed Delta path; per-page write cost grows with the table size.";
  }
  if (stage === "embedding") {
    return "Stage 3 calls the databricks-bge-large-en Foundation Model endpoint in batches of 16.";
  }
  if (stage === "setup") {
    return "Most of the wall-clock cost is the Databricks Serverless cold start.";
  }
  return "Mixed; no single stage dominates.";
}
