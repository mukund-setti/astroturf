import { notFound } from "next/navigation";
import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { getAgencyById, getDocketsForAgency } from "@/lib/fallback-data";
import { getStatsPayload } from "@/lib/databricks";
import { Card, CardContent } from "@/components/ui/card";
import { formatInt } from "@/lib/format";

interface PageProps {
  params: Promise<{ agency_id: string }>;
}

export const revalidate = 3600;

export default async function AgencyDetailPage({ params }: PageProps) {
  const { agency_id } = await params;
  const agency = getAgencyById(agency_id);

  if (!agency) {
    notFound();
  }

  if (agency.visibility !== "primary") {
    return (
      <>
        <SiteHeader backHref="/legacy/agencies" backLabel="Agencies" />
        <main className="flex-1 bg-background text-foreground pb-20">
          <section className="mx-auto max-w-4xl px-6 py-12 md:py-16">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              {agency.statusLabel.toUpperCase()}
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              {agency.fullName} ({agency.id})
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[70ch] leading-relaxed">
              This agency is not shown as a product dashboard because there is no
              promoted analyzed docket for it yet. Register a docket to create
              the next pipeline run.
            </p>
            <Link
              href={`/legacy/analyze?agency=${agency.id}`}
              className="mt-6 inline-flex h-10 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 transition-colors"
            >
              Generate ingestion config
            </Link>
          </section>
        </main>
      </>
    );
  }

  const dockets = getDocketsForAgency(agency.id);
  const isFcc = agency.id === "FCC";
  const realStats = isFcc ? await getStatsPayload() : null;
  const commentsMonitored =
    realStats?.total_comments ??
    dockets.reduce((sum, docket) => sum + docket.totalComments, 0);
  const campaignsDetected =
    realStats?.cluster_count ??
    dockets.reduce((sum, docket) => sum + docket.clusterCount, 0);

  return (
    <>
      <SiteHeader backHref="/legacy/agencies" backLabel="Agencies" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-12">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              AGENCY DOSSIER
            </span>
            <span className="text-[10px] font-mono tracking-wider text-muted-foreground block mt-1">
              Federal Oversight
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              {agency.fullName} ({agency.id})
            </h1>
            <div className="flex flex-wrap gap-2 mt-4">
              {agency.policyDomains.map((domain) => (
                <span
                  key={domain}
                  className="text-xs bg-secondary text-foreground/80 px-2 py-0.5 rounded-sm font-sans"
                >
                  {domain}
                </span>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-12">
            <Metric label="Dockets With Evidence" value={agency.docketsCount} />
            <Metric label="Clusters Surfaced" value={campaignsDetected} />
            <Metric label="Comments Checked" value={formatInt(commentsMonitored)} />
            <Metric label="Platform Status" value={agency.statusLabel} emphasized />
          </div>

          <h2 className="font-display text-2xl md:text-3xl font-semibold mb-6">
            Dockets With Product Evidence
          </h2>

          <div className="space-y-6">
            {dockets.map((docket) => {
              const displayTotal = isFcc && realStats ? realStats.total_comments : docket.totalComments;
              const displayClusters = isFcc && realStats ? realStats.cluster_count : docket.clusterCount;

              return (
                <Card key={docket.id} className="bg-card border border-rule rounded-sm shadow-none overflow-hidden">
                  <CardContent className="p-6 md:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="space-y-3 max-w-[65ch]">
                      <div className="flex items-center gap-3 flex-wrap">
                        <span className="text-[10px] font-mono tracking-wider text-muted-foreground">
                          Docket {docket.id}
                        </span>
                        <span className="text-[9px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-0.5 rounded-sm font-sans font-semibold">
                          {docket.statusLabel}
                        </span>
                      </div>

                      <h3 className="font-display text-xl font-semibold text-foreground">
                        {docket.ruleTitle}
                      </h3>

                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {docket.validationSummary}
                      </p>
                    </div>

                    <div className="flex items-center gap-6 shrink-0 pt-4 md:pt-0 border-t md:border-t-0 border-rule md:pl-6">
                      <MiniMetric label="Comments" value={formatInt(displayTotal)} />
                      <MiniMetric label="Clusters" value={displayClusters} />
                      <Link
                        href={`/legacy/dockets/${docket.id}`}
                        className="inline-flex items-center justify-center h-9 px-4 rounded-sm bg-brand text-primary-foreground text-xs uppercase tracking-wider font-semibold hover:bg-brand/90 transition-colors"
                      >
                        Explore dossier
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>
      </main>
    </>
  );
}

function Metric({
  label,
  value,
  emphasized = false,
}: {
  label: string;
  value: number | string;
  emphasized?: boolean;
}) {
  return (
    <div className="flex flex-col border-r border-rule pr-4 last:border-0">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        className={`font-display font-bold mt-1 ${
          emphasized
            ? "text-lg text-brand uppercase tracking-wider"
            : "text-3xl text-foreground tabular-nums"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="text-center md:text-right">
      <span className="block text-[9px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="font-display text-xl font-bold text-foreground tabular-nums">
        {value}
      </span>
    </div>
  );
}
