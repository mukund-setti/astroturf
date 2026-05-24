"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";
import type { DiscoveredDocket } from "@/lib/docket-catalog";

interface DiscoveriesClientProps {
  initialDiscoveries: DiscoveredDocket[];
  executionMode?: "command" | "local_process" | "databricks_job";
}

export function DiscoveriesClient({ initialDiscoveries, executionMode = "command" }: DiscoveriesClientProps) {
  const [discoveries, setDiscoveries] = useState<DiscoveredDocket[]>(initialDiscoveries);
  const [loadingIds, setLoadingIds] = useState<string[]>([]);
  const [successIds, setSuccessIds] = useState<string[]>([]);

  const handleRequest = async (docketId: string, label: string) => {
    setLoadingIds((prev) => [...prev, docketId]);
    try {
      // 1. Increment request count in discovered catalog
      const res = await fetch("/api/discoveries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "request", docketId }),
      });

      if (!res.ok) {
        throw new Error("Failed to request analysis.");
      }

      // 2. Automatically add to watchlist
      await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "docket",
          value: docketId,
          label: label,
          notes: "Requested via discovered rulemakings panel.",
        }),
      });

      // Update state locally
      setSuccessIds((prev) => [...prev, docketId]);
      setDiscoveries((prev) =>
        prev.map((d) =>
          d.docket_id === docketId
            ? { ...d, user_requested_count: d.user_requested_count + 1, status: "queued" }
            : d
        )
      );

      setTimeout(() => {
        setSuccessIds((prev) => prev.filter((id) => id !== docketId));
      }, 3000);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to submit request.");
    } finally {
      setLoadingIds((prev) => prev.filter((id) => id !== docketId));
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="font-display text-xl font-semibold text-foreground">
        Newly Discovered Rulemakings ({discoveries.length})
      </h2>

      {discoveries.length === 0 ? (
        <div className="border border-dashed border-rule rounded-sm p-12 text-center text-muted-foreground text-sm">
          No new discovered rulemakings found. Autopilot discovery task is active.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {discoveries.map((doc) => {
            const isLoading = loadingIds.includes(doc.docket_id);
            const isSuccess = successIds.includes(doc.docket_id);

            return (
              <Card
                key={doc.docket_id}
                className="bg-card border border-rule rounded-sm shadow-none hover:border-foreground/20 transition-colors"
              >
                <CardContent className="p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                  <div className="space-y-3 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-foreground font-bold">{doc.docket_id}</span>
                      <span className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-secondary text-foreground/80 font-bold">
                        {doc.source}
                      </span>
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
                      onClick={() => handleRequest(doc.docket_id, doc.title)}
                      disabled={isLoading || doc.status === "queued" || doc.status === "analyzing"}
                      className={cn(
                        "h-9 inline-flex items-center justify-center rounded-sm px-4 text-[10px] font-semibold uppercase tracking-wider transition-colors",
                        isSuccess
                          ? "bg-green-600 text-primary-foreground hover:bg-green-700"
                          : doc.status === "queued" || doc.status === "analyzing"
                          ? "bg-secondary text-foreground/50 cursor-not-allowed"
                          : "bg-brand text-primary-foreground hover:bg-brand/90"
                      )}
                    >
                      {isSuccess
                        ? "Requested & Watched!"
                        : doc.status === "queued"
                        ? "Queued for Analysis"
                        : doc.status === "analyzing"
                        ? "Analyzing..."
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
