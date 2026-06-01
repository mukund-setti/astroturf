import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import {
  INGESTION_TEMPLATE_TOPICS,
  PRIMARY_ANALYSIS_TOPICS,
} from "@/lib/fallback-data";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const revalidate = 3600;

function statusClass(status: string): string {
  if (status === "analyzed") return "bg-brand/10 text-brand";
  if (status === "baseline_only") return "bg-amber-100 text-amber-800";
  return "bg-blue-100 text-blue-800";
}

export default function TopicsPage() {
  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-12">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              MVP COVERAGE
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              Analyzed Policy Coverage
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[72ch] leading-relaxed">
              Primary browsing only includes topics with real analytical output.
              Future sectors are handled as ingestion templates so reviewers never
              land on an empty dashboard.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {PRIMARY_ANALYSIS_TOPICS.map((topic) => (
              <Link
                key={topic.id}
                href={`/legacy/topics/${topic.id}`}
                className="group block focus:outline-none"
              >
                <Card className="h-full bg-card border border-rule rounded-sm shadow-none transition-colors group-hover:border-foreground/30">
                  <CardContent className="p-6 flex h-full flex-col justify-between gap-5">
                    <div>
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <h3 className="font-display text-xl font-semibold text-foreground group-hover:text-brand transition-colors">
                          {topic.name}
                        </h3>
                        <span
                          className={cn(
                            "text-[9px] uppercase tracking-wider px-2 py-0.5 rounded-sm font-sans font-semibold",
                            statusClass(topic.status),
                          )}
                        >
                          {topic.statusLabel}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {topic.description}
                      </p>
                    </div>

                    <div className="border-t border-rule pt-4 grid grid-cols-3 gap-4 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <span>Agencies: {topic.agencies.join(", ")}</span>
                      <span>Dockets: {topic.docketsCount}</span>
                      <span>Clusters: {topic.campaignsCount}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>

          <section className="mt-12 border-t border-rule pt-10">
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_0.9fr] gap-8">
              <div>
                <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                  INGESTION ENTRY POINT
                </span>
                <h2 className="font-display text-2xl md:text-3xl font-semibold mt-4 mb-3">
                  Analyze another docket
                </h2>
                <p className="text-sm text-muted-foreground leading-relaxed max-w-[68ch]">
                  Unsupported topics should start as registered docket runs, not
                  empty sector pages. Generate a config snippet and pipeline
                  command for regulations.gov or FCC ECFS.
                </p>
                <Link
                  href="/legacy/analyze"
                  className="mt-5 inline-flex h-10 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 transition-colors"
                >
                  Analyze a docket
                </Link>
              </div>

              <div className="bg-card border border-rule rounded-sm p-6">
                <h3 className="font-display text-lg font-semibold mb-3">
                  Example Future Coverage
                </h3>
                <p className="text-xs text-muted-foreground leading-relaxed mb-4">
                  These are templates only. They are searchable as ingestion
                  starting points, but not promoted as analyzed dashboards.
                </p>
                <div className="flex flex-wrap gap-2">
                  {INGESTION_TEMPLATE_TOPICS.map((topic) => (
                    <Link
                      key={topic.id}
                      href={`/legacy/analyze?topic=${topic.id}`}
                      className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors"
                    >
                      {topic.name}
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </section>
      </main>
    </>
  );
}
