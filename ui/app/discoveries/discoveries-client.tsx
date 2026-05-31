"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";
import type { DiscoveredDocket } from "@/lib/docket-catalog";
import { estimateRuntime, formatRuntime } from "@/lib/runtime-estimate";

// How often the discoveries page re-asks the server for the latest catalog.
// Two things need to happen on every poll:
//   1) Any docket the user just requested for analysis should drop out of
//      the visible list (the server filter joins against analysis_requests).
//   2) Any new docket the autopilot has added should appear without a manual
//      reload.
// 30s feels responsive without hammering Postgres; tune via env if needed.
const DISCOVERIES_POLL_INTERVAL_MS = 30_000;

type ExecutionMode = "command" | "local_process" | "databricks_job";

interface DiscoveriesClientProps {
  initialDiscoveries: DiscoveredDocket[];
  executionMode?: ExecutionMode;
}

// Validation badge surfaces whether the docket actually exists on its source
// API. Reviewers should never click "Request Analysis" on an unvalidated or
// not_found docket and expect real data back. See ui/db/migrations/003 and
// scripts/validate_discoveries.py.
function ValidationBadge({ doc }: { doc: DiscoveredDocket }) {
  const base =
    "inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full border";
  if (doc.validation_status === "validated_real") {
    return (
      <span
        title={
          doc.validated_comment_count !== null
            ? `Source API confirmed ${doc.validated_comment_count.toLocaleString()} comments at last check.`
            : "Confirmed real by source API."
        }
        className={`${base} bg-emerald-500/10 border-emerald-500/25 text-emerald-700`}
      >
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Validated
      </span>
    );
  }
  if (doc.validation_status === "not_found" || doc.validation_status === "validated_empty") {
    return (
      <span
        title="Source API has no record (or zero comments) for this docket. A run will produce zero reviewable comments."
        className={`${base} bg-destructive/10 border-destructive/25 text-destructive`}
      >
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-destructive" />
        Source: no data
      </span>
    );
  }
  if (doc.validation_status === "error") {
    return (
      <span
        title="Last validation check failed (network / rate limit / parse). Source-side status unknown."
        className={`${base} bg-amber-500/10 border-amber-500/25 text-amber-700`}
      >
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
        Validate err
      </span>
    );
  }
  return (
    <span
      title="Not yet validated against the source API. Run scripts/validate_discoveries.py."
      className={`${base} bg-muted/60 border-rule text-muted-foreground`}
    >
      <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
      Unvalidated
    </span>
  );
}

// Where the "Request Analysis" button will send the request. The badge keeps
// reviewers honest about whether the click triggers a real Databricks run,
// a local-machine python spawn, or just a command-generation no-op.
const EXECUTION_MODE_BADGE: Record<ExecutionMode, { label: string; className: string }> = {
  databricks_job: {
    label: "Runs on Databricks",
    className: "bg-green-500/10 border-green-500/20 text-green-600",
  },
  local_process: {
    label: "Spawns local process",
    className: "bg-blue-500/10 border-blue-500/20 text-blue-600",
  },
  command: {
    label: "Command-only (no execution)",
    className: "bg-amber-500/10 border-amber-500/20 text-amber-600",
  },
};

export function DiscoveriesClient({ initialDiscoveries, executionMode = "command" }: DiscoveriesClientProps) {
  const router = useRouter();
  const [loadingIds, setLoadingIds] = useState<string[]>([]);
  const [successIds, setSuccessIds] = useState<string[]>([]);
  // Dockets we've optimistically removed pending a server refresh. The set is
  // applied as a filter over the live `initialDiscoveries` prop so we don't
  // have to mirror the whole list in local state (which would otherwise need
  // a setState-in-effect sync — flagged by react-hooks/set-state-in-effect).
  const [optimisticallyRemoved, setOptimisticallyRemoved] = useState<Set<string>>(
    () => new Set(),
  );
  const [lastPollAt, setLastPollAt] = useState<Date | null>(null);
  const modeBadge = EXECUTION_MODE_BADGE[executionMode];

  // Auto-poll the server route. router.refresh() re-runs the server component
  // for /discoveries which re-queries listAvailableDiscoveries(), so we don't
  // need a parallel JSON endpoint — the existing server render is the source
  // of truth and the only thing we have to do on the client is ask for it.
  useEffect(() => {
    const tick = () => {
      router.refresh();
      setLastPollAt(new Date());
    };
    const id = setInterval(tick, DISCOVERIES_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [router]);

  // Once the server-side filter excludes a docket on the next poll, the
  // optimistic entry becomes a no-op filter (it's not in the incoming list
  // anyway). The set therefore grows only by user-click rate and never
  // unboundedly, so no explicit cleanup pass is needed.
  const discoveries = initialDiscoveries.filter(
    (d) => !optimisticallyRemoved.has(d.docket_id),
  );

  const handleRequest = async (doc: DiscoveredDocket) => {
    const docketId = doc.docket_id;

    // Show an honest ETA before firing the request. We trust the user to
    // accept a multi-hour run as long as we told them up front it would be
    // multi-hour. Source must be a recognised pipeline source for the
    // estimator; anything else falls back to a generic warning.
    const source = doc.source as "regulations_gov" | "ecfs";
    if (source === "regulations_gov" || source === "ecfs") {
      const eta = estimateRuntime(source, doc.comment_count_estimate || 1000);
      const warnings = [...eta.warnings];

      // If this docket has not been verified to actually exist on its
      // source API, surface a hard warning. Synthetic / fallback seeds
      // returned zero rows in earlier sessions and the older deployed
      // notebook reported SUCCESS anyway. The fix is to not let the user
      // sleepwalk into another zero-row run.
      if (doc.validation_status !== "validated_real") {
        const label =
          doc.validation_status === "not_found"
            ? "DOES NOT EXIST on the source API per the last check"
            : doc.validation_status === "validated_empty"
            ? "EXISTS but has zero public comments"
            : doc.validation_status === "error"
            ? "could not be validated last attempt (network/rate-limit)"
            : "has NOT been validated against the source API yet";
        warnings.unshift(
          `This docket ${label}. The pipeline may run for the full estimated time and produce zero reviewable comments. Run scripts/validate_discoveries.py to check before submitting.`,
        );
      }

      const warningBlock = warnings.length
        ? `\n\nHeads up:\n  - ${warnings.join("\n  - ")}`
        : "";
      const ok = window.confirm(
        `Request analysis of ${docketId} ("${doc.title}")?\n\n` +
          `Source: ${source}\n` +
          `Comments to ingest: ${(doc.comment_count_estimate || 1000).toLocaleString()}\n` +
          `Estimated runtime: ${formatRuntime(eta.totalMinutes)} ` +
          `(bottleneck: stage ${eta.bottleneckStage}).${warningBlock}\n\n` +
          `You can keep using the site while it runs — the request page will auto-update with live progress.`,
      );
      if (!ok) return;
    }

    setLoadingIds((prev) => [...prev, docketId]);
    try {
      // 1. Create a tracked analysis request and trigger the pipeline
      const analysisRes = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docketId: doc.docket_id,
          source: doc.source,
          topicId: doc.topic_id,
          agencyId: doc.agency_id,
          title: doc.title,
          // Pass through the docket's full catalog comment-count estimate.
          // The user already confirmed the ETA in `confirmRequest()` below
          // before this fetch fires, so we trust them. The server logs the
          // quoted ETA in the request notes for later inspection.
          expectedScale: String(doc.comment_count_estimate || 1000),
          notes: "Requested via discovered rulemakings panel.",
        }),
      });

      if (!analysisRes.ok) {
        const errData = await analysisRes.json().catch(() => ({}));
        throw new Error(errData.error || "Failed to create analysis request.");
      }

      const analysisData = await analysisRes.json();

      // 2. Increment request count in discovered catalog (side-effect, non-blocking)
      fetch("/api/discoveries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "request", docketId }),
      }).catch(() => {});

      // 3. Automatically add to watchlist (side-effect, non-blocking)
      fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "docket",
          value: docketId,
          label: doc.title,
          notes: "Requested via discovered rulemakings panel.",
        }),
      }).catch(() => {});

      // Optimistically remove the requested docket from the visible list.
      // The server-side listAvailableDiscoveries() filter will also exclude
      // it on the next poll because an analysis_requests row now exists with
      // status='submitted', but optimistically removing here means the card
      // vanishes instantly instead of waiting up to 30s for the next refresh.
      // The cleanup useEffect above drops the id from this set once the
      // server confirms it's gone.
      setSuccessIds((prev) => [...prev, docketId]);
      setOptimisticallyRemoved((prev) => {
        const next = new Set(prev);
        next.add(docketId);
        return next;
      });

      // Redirect to the analysis request tracking page so the user can watch
      // live progress. When they navigate back to /discoveries the requested
      // docket will still be gone because the server filter handles it.
      if (analysisData.request_id) {
        router.push(`/analysis/${analysisData.request_id}`);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to submit request.");
    } finally {
      setLoadingIds((prev) => prev.filter((id) => id !== docketId));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold text-foreground">
          Newly Discovered Rulemakings ({discoveries.length})
        </h2>
        <div className="flex items-center gap-2">
          <span
            className="text-[9px] uppercase tracking-wider text-muted-foreground font-mono"
            title="The discoveries list auto-refreshes; freshly-requested dockets vanish and new ones appear without reloading."
          >
            Auto-refresh every {Math.round(DISCOVERIES_POLL_INTERVAL_MS / 1000)}s
            {lastPollAt && (
              <span className="ml-1">
                · last {lastPollAt.toLocaleTimeString()}
              </span>
            )}
          </span>
          <span
            className={cn(
              "text-[10px] uppercase font-sans tracking-wider px-2 py-0.5 rounded-sm font-bold border",
              modeBadge.className
            )}
            title="Execution mode in effect when you click Request Analysis."
          >
            {modeBadge.label}
          </span>
        </div>
      </div>

      {discoveries.length === 0 ? (
        <div
          className="rounded-xl border border-rule/60 bg-card p-10 md:p-12 text-center space-y-4"
          style={{ boxShadow: "var(--shadow-soft)" }}
        >
          <p className="text-base text-foreground/80">
            Every validated docket in the catalog is already being analyzed.
          </p>
          <p className="text-sm text-muted-foreground max-w-[60ch] mx-auto leading-relaxed">
            That&rsquo;s a healthy state for the discovery autopilot — there are no validated
            federal rulemakings on the watchlist waiting for a first run. New candidates show up
            here as the autopilot crawls regulations.gov and FCC ECFS, and as{" "}
            <Link href="/analyze" className="text-brand hover:underline font-medium">/analyze</Link>{" "}
            registers user-requested dockets.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <Link
              href="/analysis"
              className="inline-flex h-10 items-center justify-center rounded-full bg-brand px-5 text-sm font-semibold text-primary-foreground hover:bg-brand/90 transition-colors"
              style={{ boxShadow: "var(--shadow-soft)" }}
            >
              See what we&rsquo;ve analyzed →
            </Link>
            <Link
              href="/analyze"
              className="inline-flex h-10 items-center justify-center rounded-full border border-brand/40 px-5 text-sm font-semibold text-brand hover:bg-brand/5 transition-colors"
            >
              Request a new docket
            </Link>
          </div>
          <p className="text-xs text-muted-foreground/60 pt-2">
            Catalog auto-refreshes every {Math.round(DISCOVERIES_POLL_INTERVAL_MS / 1000)}s.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {discoveries.map((doc) => {
            const isLoading = loadingIds.includes(doc.docket_id);
            const isSuccess = successIds.includes(doc.docket_id);

            return (
              <Card
                key={doc.docket_id}
                className="bg-card border border-rule/60 rounded-xl shadow-none hover:-translate-y-0.5 transition-all duration-200"
                style={{ boxShadow: "var(--shadow-soft)" }}
              >
                <CardContent className="p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                  <div className="space-y-3 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-foreground font-bold">{doc.docket_id}</span>
                      <span className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-secondary text-foreground/80 font-bold">
                        {doc.source}
                      </span>
                      <ValidationBadge doc={doc} />
                      <span className="text-[9px] text-muted-foreground uppercase">
                        Discovery tags: {doc.tags}
                      </span>
                    </div>

                    <h3 className="font-display text-base font-semibold text-foreground leading-tight">
                      {doc.title}
                    </h3>

                    {doc.summary && (
                      <p className="text-xs text-muted-foreground leading-relaxed max-w-[85ch]">
                        {doc.summary}
                      </p>
                    )}

                    <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                      <span>Est. Comments: {formatInt(doc.comment_count_estimate)}</span>
                      <span>Priority Rank Score: <strong className="text-foreground">{doc.priority_score}</strong></span>
                      <span>User Requests: <strong className="text-foreground">{doc.user_requested_count}</strong></span>
                    </div>
                  </div>

                  <div className="flex gap-2 self-stretch md:self-auto items-center justify-end">
                    <button
                      onClick={() => handleRequest(doc)}
                      disabled={isLoading || isSuccess}
                      className={cn(
                        "h-9 inline-flex items-center justify-center rounded-sm px-4 text-[10px] font-semibold uppercase tracking-wider transition-colors",
                        isSuccess
                          ? "bg-green-600 text-primary-foreground cursor-not-allowed"
                          : "bg-brand text-primary-foreground hover:bg-brand/90"
                      )}
                    >
                      {isSuccess
                        ? "Submitted"
                        : isLoading
                        ? "Submitting..."
                        : "Request Analysis"}
                    </button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
