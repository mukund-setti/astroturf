"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";
import type { DiscoveredDocket } from "@/lib/docket-catalog";
import type { AnalysisRequest } from "@/lib/analysis-store";

type ExecutionMode = "command" | "local_process" | "databricks_job";

interface MonitorClientProps {
  monitoredDockets: DiscoveredDocket[];
  analysisRequests: AnalysisRequest[];
  executionMode?: ExecutionMode;
}

// Where the "Trigger Autopilot Sweep" button will send the request. Surfaced
// next to the button so reviewers see whether a click submits a real
// Databricks job, spawns a local python process, or is a no-op.
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

export function MonitorClient({ monitoredDockets, analysisRequests, executionMode = "command" }: MonitorClientProps) {
  const [activeTab, setActiveTab] = useState<"dockets" | "jobs">("dockets");
  const [isSwiping, setIsSwiping] = useState(false);
  const [swipeStatus, setSwipeStatus] = useState<string | null>(null);
  const modeBadge = EXECUTION_MODE_BADGE[executionMode];

  const handleAutopilotSwipe = async () => {
    setIsSwiping(true);
    setSwipeStatus("Initiating discovery scan...");
    try {
      const res = await fetch("/api/discoveries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "trigger" }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Autopilot execution failed.");
      }

      setSwipeStatus(data.message || "Autopilot scan succeeded! Freshness scores updated.");
      setTimeout(() => {
        setSwipeStatus(null);
        window.location.reload();
      }, 3000);
    } catch (err) {
      setSwipeStatus(err instanceof Error ? err.message : "Autopilot execution failed. Check system logs.");
      setTimeout(() => setSwipeStatus(null), 4000);
    } finally {
      setIsSwiping(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between border-b border-rule pb-3 flex-wrap gap-4">
        <div className="flex gap-4">
          <button
            onClick={() => setActiveTab("dockets")}
            className={cn(
              "text-xs font-sans uppercase tracking-wider font-semibold pb-2 border-b-2 transition-all",
              activeTab === "dockets"
                ? "border-brand text-brand"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            Monitored Ruled ({monitoredDockets.length})
          </button>
          <button
            onClick={() => setActiveTab("jobs")}
            className={cn(
              "text-xs font-sans uppercase tracking-wider font-semibold pb-2 border-b-2 transition-all",
              activeTab === "jobs"
                ? "border-brand text-brand"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            Job Runs ({analysisRequests.length})
          </button>
        </div>

        <div className="flex items-center gap-3">
          {swipeStatus && (
            <span className="text-[10px] text-brand uppercase font-mono animate-pulse">
              {swipeStatus}
            </span>
          )}
          <span
            className={cn(
              "text-[10px] uppercase font-sans tracking-wider px-2 py-0.5 rounded-sm font-bold border",
              modeBadge.className
            )}
            title="Execution mode in effect when you click Trigger Autopilot Sweep."
          >
            {modeBadge.label}
          </span>
          <button
            onClick={handleAutopilotSwipe}
            disabled={isSwiping}
            className="inline-flex h-8 items-center justify-center rounded-sm bg-brand px-3 text-[10px] font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 disabled:opacity-50 transition-colors"
          >
            Trigger Autopilot Sweep
          </button>
        </div>
      </div>

      {activeTab === "dockets" ? (
        <div className="space-y-4">
          {monitoredDockets.length === 0 ? (
            <div className="border border-dashed border-rule rounded-sm p-12 text-center text-muted-foreground text-sm">
              No dockets are currently being monitored. Add dockets from the Discoveries panel.
            </div>
          ) : (
            monitoredDockets.map((doc) => (
              <Card key={doc.docket_id} className="bg-card border border-rule rounded-sm shadow-none hover:border-foreground/20 transition-colors">
                <CardContent className="p-5 flex items-start justify-between gap-4 flex-wrap md:flex-nowrap">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-foreground font-bold">{doc.docket_id}</span>
                      <span className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-secondary text-foreground/80 font-bold">
                        {doc.source}
                      </span>
                      <span
                        className={cn(
                          "text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-semibold",
                          doc.status === "analyzed"
                            ? "bg-green-100 text-green-800"
                            : doc.status === "analyzing"
                            ? "bg-blue-100 text-blue-800"
                            : doc.status === "queued"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-secondary text-foreground/70"
                        )}
                      >
                        {doc.status}
                      </span>
                      <span className="text-[9px] text-muted-foreground uppercase">
                        Freshness: {doc.freshness_label}
                      </span>
                    </div>

                    <h3 className="font-display text-base font-semibold text-foreground leading-tight">
                      {doc.title}
                    </h3>

                    <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                      <span>Est. Comments: {formatInt(doc.comment_count_estimate)}</span>
                      <span>Priority Score: <strong className="text-foreground">{doc.priority_score}</strong></span>
                      {doc.last_analyzed_at && (
                        <span>Last Analyzed: {new Date(doc.last_analyzed_at).toLocaleString()}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col items-end justify-between self-stretch gap-2 text-right">
                    <span className="text-[10px] font-sans text-muted-foreground">
                      Updated: {new Date(doc.updated_at).toLocaleDateString()}
                    </span>
                    <a
                      href={doc.status === "analyzed" ? `/dockets/${doc.docket_id}` : `/analyze?docket=${doc.docket_id}`}
                      className="text-[10px] font-sans font-bold uppercase tracking-wider text-brand hover:underline"
                    >
                      {doc.status === "analyzed" ? "View Dossier" : "Configure Pipeline"}
                    </a>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {analysisRequests.length === 0 ? (
            <div className="border border-dashed border-rule rounded-sm p-12 text-center text-muted-foreground text-sm">
              No historical pipeline run logs found.
            </div>
          ) : (
            analysisRequests.map((req) => (
              <Card key={req.request_id} className="bg-card border border-rule rounded-sm shadow-none">
                <CardContent className="p-5 flex items-start justify-between gap-4 flex-wrap md:flex-nowrap">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-foreground font-bold">{req.request_id}</span>
                      <span className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-secondary text-foreground/80 font-bold">
                        {req.docket_id}
                      </span>
                      <span
                        className={cn(
                          "text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-semibold",
                          req.status === "succeeded"
                            ? "bg-green-100 text-green-800"
                            : req.status === "running"
                            ? "bg-blue-100 text-blue-800"
                            : req.status === "failed"
                            ? "bg-red-100 text-red-800"
                            : "bg-secondary text-foreground/70"
                        )}
                      >
                        {req.status}
                      </span>
                    </div>

                    <h3 className="font-display text-sm font-semibold text-foreground leading-tight">
                      {req.title}
                    </h3>

                    {req.error_message && (
                      <div className="p-3 bg-red-50 border border-red-200 text-[11px] font-mono text-red-800 rounded-sm">
                        Error: {req.error_message}
                      </div>
                    )}

                    <div className="text-[10px] text-muted-foreground flex gap-4">
                      <span>Expected Scale: {formatInt(req.expected_scale)}</span>
                      <span>Triggered: {new Date(req.created_at).toLocaleString()}</span>
                      {req.databricks_run_id && (
                        <span>Databricks Run ID: <code className="font-mono">{req.databricks_run_id}</code></span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col items-end justify-between self-stretch gap-2 text-right">
                    <span className="text-[10px] font-sans text-muted-foreground">
                      Updated: {new Date(req.updated_at).toLocaleTimeString()}
                    </span>
                    <a
                      href={`/analyze?docket=${req.docket_id}`}
                      className="text-[10px] font-sans font-bold uppercase tracking-wider text-brand hover:underline"
                    >
                      Audit Config
                    </a>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
