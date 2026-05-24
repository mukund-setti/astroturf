import { notFound } from "next/navigation";
import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { getAgencyById, getDocketsForTopic, getTopicById } from "@/lib/fallback-data";
import { getClustersSummary, getStatsPayload } from "@/lib/databricks";
import { Card, CardContent } from "@/components/ui/card";
import { formatInt } from "@/lib/format";

interface PageProps {
  params: Promise<{ topic_id: string }>;
}

export const revalidate = 3600;

export default async function TopicDetailPage({ params }: PageProps) {
  const { topic_id } = await params;
  const topic = getTopicById(topic_id);

  if (!topic) {
    notFound();
  }

  if (topic.visibility !== "primary" || topic.id === "analyze") {
    return (
      <>
        <SiteHeader backHref="/topics" backLabel="Analyzed coverage" />
        <main className="flex-1 bg-background text-foreground pb-20">
          <section className="mx-auto max-w-4xl px-6 py-12 md:py-16">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              NOT YET ANALYZED
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              {topic.name}
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[70ch] leading-relaxed">
              This topic is not a primary dashboard because no analyzed docket
              has been promoted for it. Start with a docket registration instead.
            </p>
            <Link
              href={`/analyze?topic=${topic.id}`}
              className="mt-6 inline-flex h-10 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 transition-colors"
            >
              Generate ingestion config
            </Link>
          </section>
        </main>
      </>
    );
  }

  const dockets = getDocketsForTopic(topic_id);
  const isTelecom = topic_id === "telecom";
  const realStats = isTelecom ? await getStatsPayload() : null;
  const clusters = isTelecom ? await getClustersSummary() : [];

  const commentsChecked =
    realStats?.total_comments ??
    dockets.reduce((sum, docket) => sum + docket.totalComments, 0);
  const campaigns =
    realStats?.cluster_count ??
    dockets.reduce((sum, docket) => sum + docket.clusterCount, 0);
  const commentsInCampaigns =
    realStats?.comments_in_clusters ??
    dockets.reduce((sum, docket) => sum + docket.commentsInClusters, 0);

  return (
    <>
      <SiteHeader backHref="/topics" backLabel="Analyzed coverage" />

      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-12">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              SECTOR ANALYSIS
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              {topic.name}
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[70ch] leading-relaxed">
              {topic.description}
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-12">
            <Metric label="Registered Dockets" value={topic.docketsCount} />
            <Metric label="Clusters Surfaced" value={campaigns} />
            <Metric label="Comments Checked" value={formatInt(commentsChecked)} />
            <Metric label="Coverage Status" value={topic.statusLabel} emphasized />
          </div>

          {isTelecom ? (
            <section className="mb-12 bg-card border border-rule rounded-sm p-6 md:p-8">
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                LATEST VALIDATION
              </span>
              <h2 className="font-display text-2xl md:text-3xl font-semibold mt-4 mb-3">
                Semantic campaign detection is live on the FCC docket
              </h2>
              <p className="text-sm text-muted-foreground leading-relaxed max-w-[80ch]">
                The validated Databricks path loaded, embedded, clustered, and
                exported a 500-comment controlled FCC 17-108 slice. The product
                view can hydrate from Databricks SQL or from reviewer artifacts.
              </p>
              <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                <strong>{formatInt(commentsInCampaigns)} comments in clusters</strong>
                <strong>{clusters.length} campaign cards available</strong>
                <strong>Vector Search clustering validated</strong>
              </div>
            </section>
          ) : (
            <section className="mb-12 bg-amber-50 border border-amber-200 rounded-sm p-6 md:p-8">
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-amber-800 bg-amber-100 px-2 py-0.5 rounded-sm font-medium">
                BASELINE ONLY
              </span>
              <h2 className="font-display text-2xl md:text-3xl font-semibold mt-4 mb-3">
                Exact-hash duplicate detection is complete
              </h2>
              <p className="text-sm text-amber-950/80 leading-relaxed max-w-[80ch]">
                EPA methane has a bounded exact-string baseline: 396 parsed rows,
                7 duplicate-hash clusters, 16 memberships, and largest cluster
                size 4. Semantic clustering is queued and should not be implied.
              </p>
              <code className="mt-5 block overflow-x-auto whitespace-pre rounded-sm bg-background border border-rule p-4 text-[11px] text-foreground">
                .uv-test-venv\Scripts\python.exe scripts\run_clustering.py --docket-id EPA-HQ-OAR-2021-0317 --clustering-mode vector_search
              </code>
            </section>
          )}

          <h2 className="font-display text-2xl md:text-3xl font-semibold mb-6">
            Dockets With Product Evidence
          </h2>

          <div className="space-y-6">
            {dockets.map((docket) => {
              const agency = getAgencyById(docket.agencyId);
              const displayTotal = isTelecom && realStats ? realStats.total_comments : docket.totalComments;
              const displayCoordinated = isTelecom && realStats ? realStats.comments_in_clusters : docket.commentsInClusters;
              const displayClusters = isTelecom && realStats ? realStats.cluster_count : docket.clusterCount;

              return (
                <Card key={docket.id} className="bg-card border border-rule rounded-sm shadow-none overflow-hidden">
                  <CardContent className="p-6 md:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="space-y-3 max-w-[65ch]">
                      <div className="flex items-center gap-3 flex-wrap">
                        <span className="text-[10px] font-sans uppercase tracking-wider text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-semibold">
                          {agency?.name ?? docket.agencyId}
                        </span>
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
                      <MiniMetric label="In clusters" value={formatInt(displayCoordinated)} />
                      <MiniMetric label="Clusters" value={displayClusters} />
                      <Link
                        href={`/dockets/${docket.id}`}
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
