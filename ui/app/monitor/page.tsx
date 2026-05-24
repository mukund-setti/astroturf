import { SiteHeader } from "@/components/site-header";
import { Card, CardContent } from "@/components/ui/card";
import { listDiscoveredDockets } from "@/lib/docket-catalog";
import { listAnalysisRequests } from "@/lib/analysis-store";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";
import { MonitorClient } from "./monitor-client";

export const revalidate = 0; // Dynamic route

import { getExecutionMode, getExecutionModeLabel } from "@/lib/execution-mode";

export default async function MonitorPage() {
  const [dockets, analysisRequests] = await Promise.all([
    listDiscoveredDockets(),
    listAnalysisRequests(),
  ]);

  const mode = getExecutionMode();
  const modeLabel = getExecutionModeLabel(mode);

  // Monitored dockets are those actively set to status: 'monitoring', 'queued', 'analyzing', 'analyzed', 'stale'
  const monitoredDockets = dockets.filter(
    (d) => d.status !== "discovered" && d.status !== "failed"
  );

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />
      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-10 flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                SYSTEM OVERSIGHT
              </span>
              <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-2">
                Pipeline Monitor
              </h1>
              <p className="text-sm text-muted-foreground max-w-[76ch] leading-relaxed">
                Real-time monitoring panel showing active ingestion/clustering runs, Unity Catalog synchronization status, 
                freshness indicators, and active pipeline triggers.
              </p>
            </div>

            <div className="flex flex-col items-start md:items-end gap-1.5">
              <span className="text-[9px] uppercase tracking-wider text-muted-foreground font-mono">
                System Active Execution Tier
              </span>
              <span
                className={`text-[10px] uppercase font-sans tracking-wider px-2.5 py-1 rounded-sm font-bold border ${
                  mode === "databricks_job"
                    ? "bg-green-500/10 border-green-500/20 text-green-500"
                    : mode === "local_process"
                    ? "bg-blue-500/10 border-blue-500/20 text-blue-500"
                    : "bg-amber-500/10 border-amber-500/20 text-amber-500"
                }`}
              >
                {modeLabel}
              </span>
            </div>
          </div>

          <div className="space-y-10">
            {/* KPI Stat Strip */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <KpiCard label="Monitored Rulemakings" value={monitoredDockets.length} status="active" />
              <KpiCard
                label="Active Ingestion Runs"
                value={analysisRequests.filter((r) => r.status === "running").length}
                status="pending"
              />
              <KpiCard
                label="Succeeded Runs"
                value={analysisRequests.filter((r) => r.status === "succeeded").length}
                status="success"
              />
              <KpiCard
                label="Stale/Failed Audits"
                value={dockets.filter((d) => d.status === "stale" || d.status === "failed").length}
                status="danger"
              />
            </div>

            <MonitorClient
              monitoredDockets={monitoredDockets}
              analysisRequests={analysisRequests}
              executionMode={mode}
            />
          </div>
        </section>
      </main>
    </>
  );
}

function KpiCard({
  label,
  value,
  status,
}: {
  label: string;
  value: number;
  status: "active" | "pending" | "success" | "danger";
}) {
  return (
    <Card className="bg-card border border-rule rounded-sm shadow-none p-5 flex flex-col justify-between">
      <span className="text-[10px] font-sans uppercase tracking-wider text-muted-foreground font-semibold">
        {label}
      </span>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="font-display text-3xl font-bold tabular-nums text-foreground">
          {value}
        </span>
        <span
          className={cn(
            "w-2 h-2 rounded-full",
            status === "success"
              ? "bg-green-500"
              : status === "pending"
              ? "bg-amber-500"
              : status === "danger"
              ? "bg-red-500"
              : "bg-brand"
          )}
        />
      </div>
    </Card>
  );
}
