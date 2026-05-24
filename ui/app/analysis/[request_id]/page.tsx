import Link from "next/link";
import { notFound } from "next/navigation";
import { SiteHeader } from "@/components/site-header";
import { getAnalysisRequest } from "@/lib/analysis-store";
import { RefreshButton } from "@/components/refresh-button";
import { Card, CardContent } from "@/components/ui/card";
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

  // Pre-generate the fallback local execution command snippet for dev/reviewers
  const commandSnippet = [
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_ingestion.py --docket-id ${req.docket_id}`,
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_embedding.py --docket-id ${req.docket_id} --backend databricks`,
    `.uv-test-venv\\Scripts\\python.exe scripts\\run_clustering.py --docket-id ${req.docket_id} --clustering-mode vector_search`,
  ].join("\n");

  return (
    <>
      <SiteHeader backHref="/analysis" backLabel="Request Queue" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-4xl px-6 py-12 md:py-16">
          {/* Header section with title and status */}
          <div className="border-b border-rule pb-6 mb-8 flex flex-col md:flex-row md:items-start justify-between gap-4">
            <div>
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                REQUEST DETAILS
              </span>
              <h1 className="font-display text-3xl font-semibold mt-4 mb-2">
                {req.title}
              </h1>
              <p className="text-xs text-muted-foreground font-mono">
                ID: {req.request_id} • Created {new Date(req.created_at).toLocaleString()}
              </p>
            </div>

            <div className="flex flex-col md:flex-row items-start md:items-center gap-3">
              <span
                className={`text-[10px] uppercase font-sans tracking-wider px-2 py-0.5 rounded-sm font-bold border ${
                  mode === "databricks_job"
                    ? "bg-green-500/10 border-green-500/20 text-green-500"
                    : mode === "local_process"
                    ? "bg-blue-500/10 border-blue-500/20 text-blue-500"
                    : "bg-amber-500/10 border-amber-500/20 text-amber-500"
                }`}
              >
                {modeLabel}
              </span>
              <span className={`text-xs uppercase tracking-wider px-3 py-1 rounded-sm font-sans font-semibold border ${getStatusClass(req.status)}`}>
                {req.status}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Metadata Card */}
            <div className="md:col-span-2 space-y-6">
              <section className="bg-card border border-rule rounded-sm p-6 space-y-4">
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
              <section className="bg-card border border-rule rounded-sm p-6 space-y-4">
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

                {req.status === "submitted" && (
                  <div className="p-3 bg-blue-500/10 border border-blue-500/20 text-blue-500 text-xs rounded-sm space-y-2">
                    <span className="font-semibold block text-[11px] uppercase tracking-wider">Job Submitted</span>
                    <p className="text-foreground/80 leading-relaxed">
                      The docket analysis job has been sent to Databricks and is currently pending in the workspace scheduler queue.
                    </p>
                    <div className="pt-1">
                      <RefreshButton requestId={req.request_id} />
                    </div>
                  </div>
                )}

                {req.status === "canceled" && (
                  <div className="p-3 bg-muted border border-rule text-muted-foreground text-xs rounded-sm">
                    <span className="font-semibold block mb-1 text-foreground/90 text-[11px] uppercase tracking-wider">Run Canceled</span>
                    The Databricks workflow task run was canceled or terminated prematurely. You can submit a new request to start fresh.
                  </div>
                )}

                {req.status === "running" && (
                  <div className="space-y-4">
                    <div className="p-3 bg-blue-500/10 border border-blue-500/20 text-blue-500 text-xs rounded-sm animate-pulse">
                      Databricks serverless compute is currently executing the ingestion pipeline.
                    </div>
                    {/* Medallion Pipeline Progress representation */}
                    <div className="border border-rule rounded-sm p-4 bg-secondary/20 space-y-3">
                      <span className="block text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                        Medallion Pipeline Stages
                      </span>
                      <div className="flex flex-col gap-2 text-xs">
                        <StageItem label="1. Ingest" desc="Fetch comments from API to raw bronze Delta table" active />
                        <StageItem label="2. Parse" desc="LLM attachment title/body extraction into silver tables" active />
                        <StageItem label="3. Embed" desc="Generate BGE embeddings via Foundation Model endpoints" active />
                        <StageItem label="4. Cluster" desc="Calculate pairwise cosine / connected components in Gold" active />
                        <StageItem label="5. Export" desc="Generate denormalized UI review exports in UC catalog" active />
                      </div>
                    </div>
                  </div>
                )}

                {req.status === "succeeded" && (
                  <div className="space-y-4">
                    <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs rounded-sm">
                      Pipeline run successfully completed! Campaign data is fully exported.
                    </div>
                    <Link
                      href={`/dockets/${req.docket_id}`}
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
                            Open Run in Databricks Workspace ↗
                          </a>
                        )}
                        <RefreshButton requestId={req.request_id} />
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
              <section className="bg-card border border-rule rounded-sm p-6 space-y-4">
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

function StageItem({ label, desc, active }: { label: string; desc: string; active?: boolean }) {
  return (
    <div className="flex items-start gap-2 border-l-2 border-brand/40 pl-3 py-1">
      <div className="space-y-0.5">
        <span className={`block font-semibold ${active ? "text-brand" : "text-muted-foreground"}`}>{label}</span>
        <span className="block text-[10px] text-muted-foreground leading-tight">{desc}</span>
      </div>
    </div>
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
