import Link from "next/link";
import { notFound } from "next/navigation";
import { SiteHeader } from "@/components/site-header";
import { getAnalysisRequest } from "@/lib/analysis-store";
import { RefreshButton } from "@/components/refresh-button";
import { AnalysisProgress } from "@/components/analysis-progress";
import { getPipelineOutputCounts, type PipelineOutputCounts } from "@/lib/databricks";
import { getExecutionMode, getExecutionModeLabel } from "@/lib/execution-mode";

interface PageProps {
  params: Promise<{
    request_id: string;
  }>;
}

export const revalidate = 0; // Dynamic page

export default async function RequestDetailPage({ params }: PageProps) {
  const { request_id } = await params;
  const req = await getAnalysisRequest(request_id);

  if (!req) {
    notFound();
  }

  // Resolve the active execution mode and label
  const mode = getExecutionMode();
  const modeLabel = getExecutionModeLabel(mode);
  // outputCounts can be:
  //   - PipelineOutputCounts: live lakehouse counts queried successfully
  //   - null: counts could not be verified (mock mode, no SQL warehouse
  //     env, or live query failure). Treat as "unknown", NOT as zero.
  //   - undefined (initial value): we did not attempt verification
  //     because the request is not in a succeeded state.
  let outputCounts: PipelineOutputCounts | null | undefined;
  if (req.status === "succeeded") {
    try {
      outputCounts = await getPipelineOutputCounts(req.docket_id);
    } catch (err) {
      console.warn(`Failed to inspect pipeline output counts for ${req.docket_id}`, err);
      outputCounts = null;
    }
  }
  const succeededWithData = Boolean(
    req.status === "succeeded" &&
      outputCounts &&
      outputCounts.raw_comments > 0 &&
      outputCounts.parsed_comments > 0
  );
  const succeededWithoutVerification =
    req.status === "succeeded" && outputCounts === null;
  const succeededWithEmptyLakehouse = Boolean(
    req.status === "succeeded" &&
      outputCounts &&
      (outputCounts.raw_comments === 0 || outputCounts.parsed_comments === 0)
  );

  // Pre-generate the fallback local execution command snippet for dev/reviewers
  const commandSnippet = [
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_ingestion.py --docket-id ${req.docket_id}`,
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_embedding.py --docket-id ${req.docket_id} --backend databricks`,
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_clustering.py --docket-id ${req.docket_id} --clustering-mode vector_search`,
  ].join("\n");

  return (
    <>
      <SiteHeader backHref="/legacy/analysis" backLabel="Request Queue" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-4xl px-6 py-12 md:py-16">
          {/* Header section with title and status */}
          <div className="pb-8 mb-10 flex flex-col md:flex-row md:items-start justify-between gap-6 border-b border-rule/60">
            <div>
              <p className="text-sm text-brand font-medium mb-3">Analysis request</p>
              <h1 className="font-display text-3xl md:text-4xl font-semibold tracking-tight leading-tight mb-3">
                {req.title}
              </h1>
              <p className="text-xs text-muted-foreground font-mono">
                {req.request_id} / created {new Date(req.created_at).toLocaleString()}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border ${
                  mode === "databricks_job"
                    ? "bg-emerald-500/10 border-emerald-500/25 text-emerald-700"
                    : mode === "local_process"
                    ? "bg-blue-500/10 border-blue-500/25 text-blue-700"
                    : "bg-amber-500/10 border-amber-500/25 text-amber-700"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    mode === "databricks_job"
                      ? "bg-emerald-500"
                      : mode === "local_process"
                      ? "bg-blue-500"
                      : "bg-amber-500"
                  }`}
                />
                {modeLabel}
              </span>
              <span className={`text-xs font-semibold rounded-full px-3 py-1 border ${getStatusClass(req.status)}`}>
                {req.status}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Metadata Card */}
            <div className="md:col-span-2 space-y-6">
              <section className="bg-card border border-rule/60 rounded-xl p-6 md:p-7 space-y-4" style={{ boxShadow: "var(--shadow-soft)" }}>
                <h2 className="font-display text-lg font-semibold border-b border-rule pb-2">
                  Rulemaking Metadata
                </h2>

                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Docket ID
                    </span>
                    <span className="font-mono text-foreground font-semibold">{req.docket_id}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Agency ID
                    </span>
                    <span className="font-semibold text-foreground">{req.agency_id}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Topic
                    </span>
                    <span className="font-semibold text-foreground">{req.topic_id}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Data Source
                    </span>
                    <span className="font-semibold text-foreground uppercase">{req.source}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Expected Scale
                    </span>
                    <span className="font-semibold text-foreground">~{req.expected_scale} comments</span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                      Date Window
                    </span>
                    <span className="font-semibold text-foreground">
                      {req.date_start || req.date_end
                        ? `${req.date_start || "Any"} to ${req.date_end || "Any"}`
                        : "Full Historical Ingestion"}
                    </span>
                  </div>
                </div>

                <div className="pt-2 text-xs">
                  <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                    Notes / Reviewer Context
                  </span>
                  <p className="text-muted-foreground leading-relaxed italic bg-secondary/30 p-3 rounded-sm">
                    &quot;{req.notes}&quot;
                  </p>
                </div>
              </section>

              {/* Status details & actions */}
              <section className="bg-card border border-rule/60 rounded-xl p-6 md:p-7 space-y-4" style={{ boxShadow: "var(--shadow-soft)" }}>
                <h2 className="font-display text-lg font-semibold border-b border-rule pb-2">
                  Status & Control Plane
                </h2>

                {req.status === "failed" && req.error_message && (
                  <div className="p-4 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-sm space-y-1">
                    <span className="font-semibold block">Execution Failure:</span>
                    <p className="font-mono bg-destructive/5 p-2 rounded-sm text-foreground/90 overflow-x-auto whitespace-pre">
                      {req.error_message}
                    </p>
                  </div>
                )}

                {req.status === "draft" && (
                  <div className="p-3 bg-amber-500/10 border border-amber-500/20 text-amber-500 text-xs rounded-sm space-y-1">
                    <span className="font-semibold block text-[11px] uppercase tracking-wider">Command-Generation Mode</span>
                    <p className="text-foreground/80 leading-relaxed">
                      This analysis request is registered. Use the terminal sequence displayed on the right to trigger local comment ingestion, parsing, embedding, and clustering manually, or register via the Local Ingestion trigger.
                    </p>
                  </div>
                )}

                {req.status === "canceled" && (
                  <div className="p-3 bg-muted border border-rule text-muted-foreground text-xs rounded-sm">
                    <span className="font-semibold block mb-1 text-foreground/90 text-[11px] uppercase tracking-wider">Run Canceled</span>
                    The Databricks workflow task run was canceled or terminated prematurely. You can submit a new request to start fresh.
                  </div>
                )}

                {(req.status === "submitted" || req.status === "running") && (
                  <AnalysisProgress
                    requestId={req.request_id}
                    initialStatus={req.status}
                    source={req.source}
                    expectedScale={req.expected_scale}
                    createdAt={req.created_at}
                  />
                )}

                {succeededWithEmptyLakehouse && (
                  <div className="space-y-4">
                    <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-sm">
                      Databricks reported success, but no reviewable comments were loaded for this docket.
                    </div>
                    {outputCounts && (
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        Raw rows: <strong>{outputCounts.raw_comments}</strong>; parsed rows: <strong>{outputCounts.parsed_comments}</strong>; exported rows: <strong>{outputCounts.export_rows}</strong>; clusters: <strong>{outputCounts.export_clusters}</strong>.
                      </p>
                    )}
                    <RefreshButton requestId={req.request_id} />
                  </div>
                )}

                {succeededWithoutVerification && (
                  <div className="space-y-4">
                    <div className="p-3 bg-amber-500/10 border border-amber-500/20 text-amber-700 text-xs rounded-sm">
                      Pipeline run succeeded on Databricks. The UI could not verify lakehouse row counts from this environment (no live Databricks SQL warehouse configured), so reviewer counts are not cross-checked here.
                    </div>
                    <Link
                      href={`/legacy/dockets/${req.docket_id}`}
                      className="inline-flex h-10 w-full items-center justify-center rounded-sm bg-brand text-white text-xs font-semibold uppercase tracking-wider hover:bg-brand/90 transition-colors"
                    >
                      View Docket Analysis
                    </Link>
                  </div>
                )}

                {succeededWithData && (
                  <div className="space-y-4">
                    <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs rounded-sm">
                      Pipeline run successfully completed! Campaign data is fully exported.
                    </div>
                    <Link
                      href={`/legacy/dockets/${req.docket_id}`}
                      className="inline-flex h-10 w-full items-center justify-center rounded-sm bg-brand text-white text-xs font-semibold uppercase tracking-wider hover:bg-brand/90 transition-colors"
                    >
                      View Docket Analysis
                    </Link>
                  </div>
                )}

                <div className="flex flex-col gap-3 pt-2 text-xs">
                  <div>
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                      Databricks Workspace Integration
                    </span>
                    {req.databricks_run_id ? (
                      <div className="space-y-3">
                        <span className="block text-xs">
                          Active Databricks Run ID: <strong className="font-mono">{req.databricks_run_id}</strong>
                        </span>
                        {req.result_url && (
                          <a
                            href={req.result_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-brand hover:underline font-semibold block"
                          >
                            Open Run in Databricks Workspace (opens externally)</a>
                        )}
                        {/* Manual sync kept as a fallback only. The
                            AnalysisProgress component above auto-polls the
                            progress endpoint every 10s while the run is in
                            flight, so this button should almost never need
                            to be used. */}
                        {(req.status === "succeeded" || req.status === "failed" || req.status === "canceled") && (
                          <RefreshButton requestId={req.request_id} />
                        )}
                      </div>
                    ) : (
                      <span className="text-muted-foreground block text-[11px] leading-relaxed">
                        Offline Command-Generation mode. No hosted Databricks run ID mapped.
                      </span>
                    )}
                  </div>
                </div>
              </section>
            </div>

            {/* Fallback CLI execution card */}
            <div className="space-y-6">
              <section className="bg-card border border-rule/60 rounded-xl p-6 md:p-7 space-y-4" style={{ boxShadow: "var(--shadow-soft)" }}>
                <h2 className="font-display text-lg font-semibold border-b border-rule pb-2">
                  Command-Generation Mode
                </h2>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  If you want to run this pipeline locally on your system instead of hosted Databricks, run the following sequence in your terminal:
                </p>
                <pre className="overflow-x-auto whitespace-pre rounded-sm bg-background border border-rule p-3 text-[10px] leading-relaxed text-foreground font-mono">
                  {commandSnippet}
                </pre>
                <p className="text-[10px] text-muted-foreground leading-normal">
                  Command-generation mode allows running comment ingestion and clustering locally via python scripts, writing directly to your local delta lakehouse.
                </p>
              </section>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}

function getStatusClass(status: string): string {
  switch (status) {
    case "draft":
      return "bg-amber-500/10 border-amber-500/20 text-amber-500";
    case "submitted":
      return "bg-blue-500/10 border-blue-500/20 text-blue-500";
    case "running":
      return "bg-blue-500/10 border-blue-500/20 text-blue-500 animate-pulse";
    case "succeeded":
      return "bg-emerald-500/10 border-emerald-500/20 text-emerald-500";
    case "failed":
      return "bg-destructive/10 border-destructive/20 text-destructive";
    case "canceled":
      return "bg-muted border-rule text-muted-foreground";
    default:
      return "bg-secondary border-rule text-foreground/80";
  }
}
