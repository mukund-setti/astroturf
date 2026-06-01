import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { PRIMARY_AGENCIES, SUPPORTED_SOURCE_AGENCIES } from "@/lib/fallback-data";
import { Card, CardContent } from "@/components/ui/card";
import { formatInt } from "@/lib/format";

export const revalidate = 3600;

export default function AgenciesPage() {
  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-12">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              AGENCY COVERAGE
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              Agencies With Evidence
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[72ch] leading-relaxed">
              Primary agency pages are limited to real analyzed or baseline-only
              dockets. Other supported sources route users into docket ingestion
              instead of showing empty agency dashboards.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {PRIMARY_AGENCIES.map((agency) => (
              <Link
                key={agency.id}
                href={`/legacy/agencies/${agency.id}`}
                className="group block focus:outline-none"
              >
                <Card className="h-full bg-card border border-rule rounded-sm shadow-none transition-colors group-hover:border-foreground/30">
                  <CardContent className="p-6 flex h-full flex-col justify-between gap-5">
                    <div>
                      <div className="flex items-start justify-between gap-3 mb-3">
                        <div>
                          <span className="text-[10px] font-mono text-muted-foreground block mb-0.5">
                            {agency.id}
                          </span>
                          <h3 className="font-display text-xl font-semibold text-foreground group-hover:text-brand transition-colors leading-tight">
                            {agency.fullName}
                          </h3>
                        </div>
                        <span className="text-[9px] uppercase tracking-wider bg-brand/10 text-brand px-2 py-0.5 rounded-sm font-sans font-semibold">
                          {agency.statusLabel}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {agency.policyDomains.join(", ")}
                      </p>
                    </div>

                    <div className="border-t border-rule pt-4 grid grid-cols-3 gap-4 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <span>Comments: {formatInt(agency.totalComments)}</span>
                      <span>Dockets: {agency.docketsCount}</span>
                      <span>Clusters: {agency.campaignsCount}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>

          <section className="mt-12 bg-card border border-rule rounded-sm p-6 md:p-8">
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-6">
              <div>
                <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                  SUPPORTED SOURCES
                </span>
                <h2 className="font-display text-2xl md:text-3xl font-semibold mt-4 mb-3">
                  Register another agency docket
                </h2>
                <p className="text-sm text-muted-foreground leading-relaxed max-w-[70ch]">
                  These agencies are supported by the ingestion path or docket
                  registry, but they do not appear as dashboards until a run has
                  produced analytical evidence.
                </p>
              </div>
              <Link
                href="/legacy/analyze"
                className="inline-flex h-10 shrink-0 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 transition-colors"
              >
                Analyze a docket
              </Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-2">
              {SUPPORTED_SOURCE_AGENCIES.map((agency) => (
                <Link
                  key={agency.id}
                  href={`/legacy/analyze?agency=${agency.id}`}
                  className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors"
                >
                  {agency.id}: {agency.statusLabel}
                </Link>
              ))}
            </div>
          </section>
        </section>
      </main>
    </>
  );
}
