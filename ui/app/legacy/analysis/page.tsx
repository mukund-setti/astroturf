import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { listAnalysisRequests } from "@/lib/analysis-store";
import { Card, CardContent } from "@/components/ui/card";

export const revalidate = 0; // Dynamic route so requests are always fresh

export default async function AnalysisQueuePage() {
  const requests = await listAnalysisRequests();
  // Sort by created_at descending
  requests.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="pb-10 mb-10 flex flex-col md:flex-row md:items-end md:justify-between gap-6 border-b border-rule/60">
            <div>
              <p className="text-sm text-brand font-medium mb-3">Orchestration pipeline</p>
              <h1 className="font-display text-4xl md:text-5xl font-semibold tracking-tight leading-tight mb-4">
                Analysis request queue
              </h1>
              <p className="text-base text-foreground/70 max-w-[64ch] leading-relaxed">
                Every federal comment analysis ever submitted - to Databricks compute or to a local
                pipeline. Click any row for stage-by-stage row counts, the Databricks run page,
                and exported cluster data.
              </p>
            </div>
            <Link
              href="/legacy/analyze"
              className="inline-flex h-10 shrink-0 items-center justify-center rounded-full bg-brand px-5 text-sm font-semibold text-primary-foreground hover:bg-brand/90 transition-colors"
              style={{ boxShadow: "var(--shadow-soft)" }}
            >
              + Analyze new docket
            </Link>
          </div>

          {requests.length === 0 ? (
            <div
              className="bg-card border border-rule/60 rounded-xl p-12 text-center"
              style={{ boxShadow: "var(--shadow-soft)" }}
            >
              <h3 className="font-display text-xl font-semibold text-foreground mb-2">
                No analysis requests yet
              </h3>
              <p className="text-sm text-muted-foreground max-w-md mx-auto mb-6">
                Register a regulations.gov or FCC ECFS docket from the Analyze page to start the
                first pipeline run.
              </p>
              <Link
                href="/legacy/analyze"
                className="inline-flex h-10 items-center justify-center rounded-full border border-brand text-brand px-5 text-sm font-semibold hover:bg-brand/5 transition-colors"
              >
                Analyze a docket
              </Link>
            </div>
          ) : (
            <div className="space-y-4">
              {requests.map((req) => (
                <Link
                  key={req.request_id}
                  href={`/legacy/analysis/${req.request_id}`}
                  className="group block focus:outline-none"
                >
                  <Card
                    className="bg-card border border-rule/60 rounded-xl shadow-none transition-all duration-200 group-hover:-translate-y-0.5"
                    style={{ boxShadow: "var(--shadow-soft)" }}
                  >
                    <CardContent className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-3">
                          <span className="text-xs font-mono bg-secondary text-foreground/80 px-2 py-0.5 rounded-sm">
                            {req.docket_id}
                          </span>
                          <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-mono">
                            {req.agency_id} * {req.topic_id}
                          </span>
                        </div>
                        <h3 className="font-display text-lg font-semibold text-foreground group-hover:text-brand transition-colors">
                          {req.title}
                        </h3>
                        <p className="text-xs text-muted-foreground line-clamp-1 max-w-[80ch]">
                          {req.notes}
                        </p>
                      </div>

                      <div className="flex flex-row md:flex-col items-start md:items-end justify-between md:justify-center gap-2">
                        <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm font-sans font-semibold border ${getStatusClass(req.status)}`}>
                          {req.status}
                        </span>
                        <div className="text-[10px] text-muted-foreground text-right">
                          <span className="block font-mono">
                            {req.databricks_run_id ? `Run: ${req.databricks_run_id}` : "Local / Config Mode"}
                          </span>
                          <span className="block mt-0.5">
                            {new Date(req.created_at).toLocaleString()}
                          </span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          )}
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
