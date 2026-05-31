"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  estimateRuntime,
  formatRuntime,
  projectFromObservation,
  type AnalysisSource,
} from "@/lib/runtime-estimate";

interface StageCounts {
  raw_comments: number;
  parsed_comments: number;
  comment_embeddings: number;
  clusters: number;
  cluster_memberships: number;
  export_rows: number;
  export_clusters: number;
}

interface ProgressResponse {
  request_id: string;
  docket_id: string;
  source: string;
  expected_scale: number;
  status: "draft" | "submitted" | "running" | "succeeded" | "failed" | "canceled";
  error_message: string | null;
  databricks_run_id: string | null;
  result_url: string | null;
  created_at: string;
  elapsed_ms: number;
  counts: StageCounts | null;
  is_terminal: boolean;
}

interface AnalysisProgressProps {
  requestId: string;
  initialStatus: string;
  source: string;
  expectedScale: number;
  createdAt: string;
}

const POLL_INTERVAL_MS = 10000;

/**
 * Auto-polling progress panel for an analysis request. Replaces the manual
 * "Sync Databricks Run" babysitting button:
 *
 *   - Polls /api/analysis/[id]/progress every 10s while the run is in flight.
 *   - Shows live per-stage row counts updating in place.
 *   - Computes "expected by N rows" using ui/lib/runtime-estimate so the user
 *     can see "stage 2/5: 12,431 of expected ~20,697 rows".
 *   - Stops polling when the run is terminal, then forces a server-side
 *     re-render of the surrounding page so any data-dependent UI updates.
 *   - Renders -1 as "syncing…" because Delta writes can transiently leave
 *     a path in a half-written state for the duration of a single MERGE
 *     transaction; we treat that as "in progress", not "empty". (The
 *     historical reason was the delta-rs FUSE bypass — see ADR-0017 for
 *     why we replaced it with Spark-native writes and why this -1 sentinel
 *     is still useful even after the bypass is gone.)
 */
export function AnalysisProgress({
  requestId,
  initialStatus,
  source,
  expectedScale,
  createdAt,
}: AnalysisProgressProps) {
  const router = useRouter();
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [lastPollAt, setLastPollAt] = useState<Date | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const wasTerminalRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const res = await fetch(`/api/analysis/${requestId}/progress`, {
          cache: "no-store",
        });
        if (!res.ok) {
          throw new Error(`progress endpoint returned HTTP ${res.status}`);
        }
        const data = (await res.json()) as ProgressResponse;
        if (cancelled) return;
        setProgress(data);
        setLastPollAt(new Date());
        setPollError(null);

        if (data.is_terminal) {
          // First time we observe terminal: re-render the parent server
          // component once so it can pull in fresh row counts, fresh notes
          // (the API now writes ETA into notes), and updated status badges.
          if (!wasTerminalRef.current) {
            wasTerminalRef.current = true;
            router.refresh();
          }
          return; // stop scheduling
        }

        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        setPollError(err instanceof Error ? err.message : "Unknown poll error");
        // Back off slightly on error but keep trying — transient SQL failures
        // are expected (FUSE bypass intermittent reads).
        timer = setTimeout(poll, POLL_INTERVAL_MS * 2);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [requestId, router]);

  const status = progress?.status ?? initialStatus;
  const counts = progress?.counts;
  // Tick the local clock once a second so the time-based progress fallback
  // actually advances between polls (the 10s poll cadence is too coarse for
  // the bar to feel alive otherwise).
  const initialAnchor = useMemo(() => new Date(createdAt).getTime(), [createdAt]);
  const [clientNow, setClientNow] = useState(initialAnchor);
  useEffect(() => {
    const tick = () => setClientNow(Date.now());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  // We deliberately recompute elapsedMs from clientNow on every tick (not
  // from the server-supplied elapsed_ms, which is only fresh once per poll).
  // The server value is still useful as a sanity floor for when the client
  // and server clocks disagree, so we take the max of the two.
  const clientElapsed = Math.max(0, clientNow - initialAnchor);
  const elapsedMs = Math.max(clientElapsed, progress?.elapsed_ms ?? 0);

  const validSource: AnalysisSource =
    source === "regulations_gov" || source === "ecfs"
      ? (source as AnalysisSource)
      : "regulations_gov";
  const eta = estimateRuntime(validSource, expectedScale);

  const elapsedMin = Math.max(0, elapsedMs / 60000);

  // Honest progress accounting. When ANY stage row count is observable
  // (>= 0), use the row-based fraction — that's the lakehouse truth. When
  // every stage read is the -1 sentinel (FUSE bypass mid-write), fall back
  // to a small time-derived placeholder capped at 0.5 so we don't imply
  // near-completion. Terminal status pins to 100% with a colour change.
  const isTerminal = status === "succeeded" || status === "failed" || status === "canceled";
  const rowBasedFraction = computeProgressFraction(counts ?? null, expectedScale);
  const haveAnyObservableRows = counts
    ? [
        counts.raw_comments,
        counts.parsed_comments,
        counts.comment_embeddings,
        counts.clusters,
        counts.export_rows,
      ].some((n) => n >= 0)
    : false;
  const timeFallbackFraction = Math.min(0.5, elapsedMin / Math.max(1, eta.totalMinutes));
  const progressFraction = isTerminal
    ? 1
    : haveAnyObservableRows
    ? rowBasedFraction
    : timeFallbackFraction;

  // Re-project the total runtime from observed progress. This is what makes
  // the displayed estimate grow honestly with reality instead of staying
  // pinned to a stale up-front quote.
  const projection = projectFromObservation(elapsedMin, progressFraction, eta.totalMinutes);
  const displayedTotalMinutes = isTerminal ? elapsedMin : projection.projectedMinutes;
  const projectionShifted =
    !isTerminal &&
    projection.confidence !== "low" &&
    Math.abs(projection.projectedMinutes - eta.totalMinutes) >= Math.max(2, eta.totalMinutes * 0.15);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <span className="block text-[10px] uppercase tracking-[0.24em] text-muted-foreground font-semibold mb-0.5">
            Live pipeline progress
          </span>
          <span className="text-xs text-muted-foreground">
            Auto-refreshing every {Math.round(POLL_INTERVAL_MS / 1000)}s — no manual sync needed.
            {lastPollAt && (
              <>
                {" "}
                Last poll: <span className="font-mono">{lastPollAt.toLocaleTimeString()}</span>
              </>
            )}
          </span>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Elapsed / Projected total
          </div>
          <div className="font-mono text-sm text-foreground">
            <strong>{formatRuntime(elapsedMin)}</strong>{" "}
            <span className="text-muted-foreground">/ {formatRuntime(displayedTotalMinutes)}</span>
          </div>
          {projectionShifted && (
            <div className="text-[10px] text-muted-foreground/80 mt-0.5">
              revised from initial ~{formatRuntime(eta.totalMinutes)} estimate
            </div>
          )}
        </div>
      </div>

      {/* Top-level progress bar based on overall pipeline fraction */}
      <div className="h-2 bg-secondary rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-700 ${
            status === "failed" || status === "canceled"
              ? "bg-destructive"
              : status === "succeeded"
              ? "bg-emerald-500"
              : "bg-brand animate-pulse"
          }`}
          style={{ width: `${Math.min(100, Math.max(2, progressFraction * 100))}%` }}
        />
      </div>

      {/* Pick exactly one ACTIVE stage based on what the pipeline has
          actually filled in. The pipeline runs strictly serially in
          web_analysis_job.py (ingest -> parse -> embed -> cluster -> export),
          so two stages can never genuinely be in flight at the same time.
          Marking multiple stages active was misleading. */}
      {(() => {
        const c = counts;
        const ingest = c?.raw_comments ?? 0;
        const parse = c?.parsed_comments ?? 0;
        const embed = c?.comment_embeddings ?? 0;
        const clusters = c?.clusters ?? 0;
        const exportRows = c?.export_rows ?? 0;
        const inFlight = !isTerminal && (status === "submitted" || status === "running");
        let activeStage: 1 | 2 | 3 | 4 | 5 | null = null;
        if (inFlight) {
          if (ingest < expectedScale) activeStage = 1;
          else if (parse < expectedScale) activeStage = 2;
          else if (embed < expectedScale) activeStage = 3;
          else if (clusters === 0) activeStage = 4;
          else if (exportRows === 0) activeStage = 5;
          else activeStage = 5;
        }
        return (
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            <StageBox n={1} label="Ingest" rows={c?.raw_comments} expected={expectedScale} active={activeStage === 1} />
            <StageBox n={2} label="Parse" rows={c?.parsed_comments} expected={expectedScale} active={activeStage === 2} />
            <StageBox n={3} label="Embed" rows={c?.comment_embeddings} expected={expectedScale} active={activeStage === 3} />
            <StageBox
              n={4}
              label="Cluster"
              rows={c?.cluster_memberships}
              expected={Math.max(1, c?.comment_embeddings ?? expectedScale)}
              showAsCount
              active={activeStage === 4}
            />
            <StageBox
              n={5}
              label="Export"
              rows={c?.export_rows}
              expected={Math.max(1, c?.cluster_memberships ?? expectedScale)}
              showAsCount
              active={activeStage === 5}
            />
          </div>
        );
      })()}

      {/* Calm status banner. Default is "everything is fine" — we only
          escalate to amber/red when the pipeline genuinely hits trouble
          (terminal failed/canceled state). Slower-than-ETA is not a
          problem — that's why we re-project the total above. */}
      {!isTerminal && (
        <div className="text-[11px] text-emerald-700 bg-emerald-500/5 border border-emerald-500/20 rounded-sm p-2 leading-snug">
          <strong>Pipeline is running normally.</strong>{" "}
          {haveAnyObservableRows
            ? `Currently in stage ${currentStageDescription(counts, expectedScale)}. Projected to finish at ~${formatRuntime(displayedTotalMinutes)} elapsed.`
            : `Databricks compute is warming up (Serverless cold start typically takes 2-4 min). The first row counts will appear shortly.`}
          {" "}You can leave this page open or come back later — progress is auto-saved.
        </div>
      )}
      {status === "failed" && progress?.error_message && (
        <div className="text-[11px] text-destructive bg-destructive/5 border border-destructive/20 rounded-sm p-2 leading-snug whitespace-pre-wrap">
          <strong>Run failed.</strong> {progress.error_message}
        </div>
      )}
      {status === "canceled" && (
        <div className="text-[11px] text-muted-foreground bg-muted/30 border border-rule rounded-sm p-2 leading-snug">
          Run was canceled. You can submit a new request from /analyze or /discoveries.
        </div>
      )}

      {pollError && (
        <div className="text-[11px] text-amber-500 font-mono">
          Poll error (transient, will retry): {pollError}
        </div>
      )}
    </div>
  );
}

function computeProgressFraction(counts: StageCounts | null, expectedScale: number): number {
  if (!counts) return 0.02;
  // Treat the pipeline as 5 equal-weight stages for the top-level bar. Each
  // stage contributes its share based on rows-vs-expected, capped at 1.0.
  // -1 (sentinel for "couldn't read") counts as 0 for progress but keeps the
  // bar visible.
  const stageFractions = [
    clampFrac(counts.raw_comments, expectedScale),
    clampFrac(counts.parsed_comments, expectedScale),
    clampFrac(counts.comment_embeddings, expectedScale),
    clampFrac(counts.clusters > 0 ? expectedScale : 0, expectedScale),
    clampFrac(counts.export_rows, expectedScale),
  ];
  return stageFractions.reduce((a, b) => a + b, 0) / stageFractions.length;
}

function clampFrac(n: number, expected: number): number {
  if (n < 0) return 0;
  if (expected <= 0) return 0;
  return Math.max(0, Math.min(1, n / expected));
}

function currentStageDescription(
  counts: StageCounts | null | undefined,
  expectedScale: number,
): string {
  if (!counts) return "1 (ingest)";
  const ingest = counts.raw_comments < 0 ? 0 : counts.raw_comments;
  const parse = counts.parsed_comments < 0 ? 0 : counts.parsed_comments;
  const embed = counts.comment_embeddings < 0 ? 0 : counts.comment_embeddings;
  const clusters = counts.clusters < 0 ? 0 : counts.clusters;
  const exportRows = counts.export_rows < 0 ? 0 : counts.export_rows;
  if (ingest < expectedScale) return `1 of 5 (ingesting comments — ${ingest.toLocaleString()} of ~${expectedScale.toLocaleString()})`;
  if (parse < expectedScale) return `2 of 5 (parsing — ${parse.toLocaleString()} of ${ingest.toLocaleString()})`;
  if (embed < expectedScale) return `3 of 5 (embedding — ${embed.toLocaleString()} of ${parse.toLocaleString()})`;
  if (clusters === 0) return "4 of 5 (clustering)";
  if (exportRows === 0) return "5 of 5 (exporting to demo table)";
  return "5 of 5 (finalizing)";
}

function StageBox({
  n,
  label,
  rows,
  expected,
  active,
  showAsCount,
}: {
  n: number;
  label: string;
  rows: number | undefined;
  expected: number;
  active?: boolean;
  showAsCount?: boolean;
}) {
  const isSyncing = rows === -1;
  const safeRows = rows ?? 0;
  const fraction = safeRows < 0 ? 0 : expected > 0 ? safeRows / expected : 0;

  return (
    <div
      className={`p-3 border rounded-sm bg-card transition-colors ${
        active ? "border-brand/60" : "border-rule"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
          {n}. {label}
        </span>
        {active && (
          <span className="text-[8px] uppercase font-bold text-brand bg-brand/10 px-1 py-0.5 rounded-sm">
            ACTIVE
          </span>
        )}
      </div>
      <div className="font-mono text-sm text-foreground">
        {isSyncing ? (
          <span className="text-muted-foreground italic text-xs">syncing…</span>
        ) : showAsCount ? (
          safeRows.toLocaleString()
        ) : (
          <>
            <strong>{safeRows.toLocaleString()}</strong>
            <span className="text-muted-foreground">
              {" "}
              / {expected.toLocaleString()}
            </span>
          </>
        )}
      </div>
      {!showAsCount && expected > 0 && (
        <div className="h-1 bg-secondary rounded-full overflow-hidden mt-2">
          {isSyncing && active ? (
            // Row count is the -1 sentinel and the stage is still active —
            // the FUSE bypass is mid-rmtree/copytree so reads transiently
            // fail. Show an indeterminate shimmer so the user can see
            // "something is happening" instead of a flat empty bar.
            <div className="h-full w-1/3 bg-brand animate-pulse rounded-full" />
          ) : (
            <div
              className={`h-full transition-all duration-700 ${active ? "bg-brand animate-pulse" : "bg-foreground/40"}`}
              style={{ width: `${Math.min(100, Math.max(0, fraction * 100))}%` }}
            />
          )}
        </div>
      )}
    </div>
  );
}
