import Link from "next/link";
import { ArchitectureDiagram } from "@/components/architecture-diagram";
import { BenchmarkComparisonCard } from "@/components/benchmark-comparison-card";
import { Hero } from "@/components/hero";
import { HowItHides } from "@/components/how-it-hides";
import { HowItWorks } from "@/components/how-it-works";
import { LandingShell } from "@/components/landing-shell";
import { LimitationsSection } from "@/components/limitations-section";
import { ReviewerDemoFlow } from "@/components/reviewer-demo-flow";
import { ScaleFailureCard } from "@/components/scale-failure-card";
import { StatStrip } from "@/components/stat-strip";
import { WhyDatabricksSection } from "@/components/why-databricks-section";
import { Card, CardContent } from "@/components/ui/card";
import {
  getClustersSummary,
  getDataDiagnostics,
  getDataSourceLabel,
  getValidatedDemoClustersSummary,
  getValidatedDemoStatsPayload,
  getStatsPayload,
  isOfflineMode,
} from "@/lib/databricks";
import { getDocketCopy } from "@/lib/docket-copy";
import {
  PRIMARY_AGENCIES,
  PRIMARY_ANALYSIS_TOPICS,
  SUPPORTED_SOURCE_AGENCIES,
} from "@/lib/fallback-data";
import { daysBetweenInclusive, formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";

export const revalidate = 3600;
const FEATURED_DOCKET_ID = "17-108";

export default async function Home() {
  let [stats, clusters] = await Promise.all([
    getStatsPayload(FEATURED_DOCKET_ID),
    getClustersSummary(FEATURED_DOCKET_ID),
  ]);

  if (stats.cluster_count === 0 && stats.comments_in_clusters === 0 && clusters.length === 0) {
    stats = getValidatedDemoStatsPayload();
    clusters = getValidatedDemoClustersSummary();
  }

  const docketId = stats.docket_id || FEATURED_DOCKET_ID;
  const copy = getDocketCopy(docketId);
  const featured = clusters[0];
  const daySpan = featured
    ? daysBetweenInclusive(
        featured.earliest_posted_date,
        featured.latest_posted_date,
      )
    : null;
  const percent =
    stats.comments_in_clusters > 0
      ? Math.round((stats.largest_cluster_size / stats.comments_in_clusters) * 100)
      : 0;
  const remainingClusters = Math.max(0, stats.cluster_count - 1);
  const embeddingModel = featured?.embedding_model ?? "BAAI/bge-large-en-v1.5";
  const similarityThreshold = featured?.similarity_threshold ?? 0.92;
  const offline = isOfflineMode();
  const dataSourceLabel = getDataSourceLabel();
  const diagnostics = getDataDiagnostics();

  return (
    <>
      {offline && (
        <div className="bg-brand/10 border-b border-brand/20 text-brand text-[10px] md:text-[11px] font-sans uppercase tracking-[0.2em] py-2 px-6 text-center font-medium z-40 relative">
          Active: {dataSourceLabel}
        </div>
      )}

      <LandingShell
        clusters={clusters}
        dataSourceLabel={dataSourceLabel}
        diagnostics={diagnostics}
        afterGrid={
          <>
            <section className="border-b border-rule bg-card py-16 md:py-20">
              <div className="mx-auto max-w-6xl px-6">
                <div className="text-center max-w-[70ch] mx-auto mb-12">
                  <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                    MVP COVERAGE
                  </span>
                  <h2 className="font-display text-3xl md:text-4xl text-foreground font-semibold mt-4 mb-4">
                    Explore analyzed coverage
                  </h2>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    Primary browsing is limited to surfaces with evidence: FCC
                    semantic clustering and EPA exact-hash baseline results.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {PRIMARY_ANALYSIS_TOPICS.map((topic) => (
                    <Link
                      key={topic.id}
                      href={`/topics/${topic.id}`}
                      className="group block focus:outline-none h-full"
                    >
                      <Card className="h-full bg-background border border-rule rounded-sm shadow-none transition-colors p-5 flex flex-col justify-between group-hover:border-foreground/30">
                        <div>
                          <span
                            className={cn(
                              "text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-sans font-semibold",
                              topic.status === "analyzed"
                                ? "bg-brand/10 text-brand"
                                : "bg-amber-100 text-amber-800",
                            )}
                          >
                            {topic.statusLabel}
                          </span>
                          <h3 className="font-display text-base font-semibold text-foreground leading-tight group-hover:text-brand transition-colors mt-3">
                            {topic.name}
                          </h3>
                          <p className="text-[11px] text-muted-foreground leading-normal mt-2">
                            {topic.description}
                          </p>
                        </div>
                        <div className="border-t border-rule pt-3 mt-4 text-[9px] uppercase tracking-wider text-muted-foreground flex justify-between">
                          <span>Agencies: {topic.agencies.join(", ")}</span>
                          <span>Clusters: {topic.campaignsCount}</span>
                        </div>
                      </Card>
                    </Link>
                  ))}
                </div>

                <div className="text-center mt-8">
                  <Link
                    href="/topics"
                    className="text-xs uppercase tracking-wider text-muted-foreground hover:text-brand font-semibold transition-colors"
                  >
                    View analyzed coverage
                  </Link>
                </div>
              </div>
            </section>

            <section className="border-b border-rule bg-background py-16 md:py-20">
              <div className="mx-auto max-w-6xl px-6">
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_0.9fr] gap-8 items-start">
                  <div>
                    <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                      INGESTION ENTRY POINT
                    </span>
                    <h2 className="font-display text-3xl md:text-4xl text-foreground font-semibold mt-4 mb-4">
                      Analyze a docket
                    </h2>
                    <p className="text-sm text-muted-foreground leading-relaxed max-w-[70ch]">
                      Unsupported topics become configured ingestion runs, not
                      empty dashboards. Generate a docket registry snippet and
                      the command sequence for regulations.gov or FCC ECFS.
                    </p>
                    <Link
                      href="/analyze"
                      className="mt-6 inline-flex h-10 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 transition-colors"
                    >
                      Generate pipeline config
                    </Link>
                  </div>

                  <Card className="bg-card border border-rule rounded-sm shadow-none">
                    <CardContent className="p-6">
                      <h3 className="font-display text-xl font-semibold mb-3">
                        Supported source paths
                      </h3>
                      <p className="text-xs text-muted-foreground leading-relaxed mb-4">
                        These agencies can be registered through the pipeline
                        when a reviewer has a real docket ID and scale estimate.
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {SUPPORTED_SOURCE_AGENCIES.map((agency) => (
                          <Link
                            key={agency.id}
                            href={`/analyze?agency=${agency.id}`}
                            className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors"
                          >
                            {agency.id}
                          </Link>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </section>

            <section className="border-b border-rule bg-card py-16 md:py-20">
              <div className="mx-auto max-w-6xl px-6">
                <div className="text-center max-w-[70ch] mx-auto mb-12">
                  <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                    OVERSIGHT MATRIX
                  </span>
                  <h2 className="font-display text-3xl md:text-4xl text-foreground font-semibold mt-4 mb-4">
                    Agencies with evidence
                  </h2>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    FCC has live semantic validation. EPA has baseline-only
                    evidence. Other agencies are reachable through Analyze a
                    docket until a run produces results.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {PRIMARY_AGENCIES.map((agency) => (
                    <Link
                      key={agency.id}
                      href={`/agencies/${agency.id}`}
                      className="group block focus:outline-none h-full"
                    >
                      <Card className="h-full bg-background border border-rule rounded-sm shadow-none transition-colors p-5 flex flex-col justify-between group-hover:border-foreground/30">
                        <div>
                          <div className="flex items-center justify-between gap-2 mb-3">
                            <span className="text-[10px] font-mono text-muted-foreground">
                              {agency.id}
                            </span>
                            <span className="text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-sans bg-brand/10 text-brand font-semibold">
                              {agency.statusLabel}
                            </span>
                          </div>
                          <h3 className="font-display text-base font-semibold text-foreground leading-tight group-hover:text-brand transition-colors">
                            {agency.fullName}
                          </h3>
                        </div>
                        <div className="border-t border-rule pt-3 mt-4 text-[9px] uppercase tracking-wider text-muted-foreground flex justify-between">
                          <span>Dockets: {agency.docketsCount}</span>
                          <span>Comments: {formatInt(agency.totalComments)}</span>
                        </div>
                      </Card>
                    </Link>
                  ))}
                </div>

                <div className="text-center mt-8">
                  <Link
                    href="/agencies"
                    className="text-xs uppercase tracking-wider text-muted-foreground hover:text-brand font-semibold transition-colors"
                  >
                    View agency coverage
                  </Link>
                </div>
              </div>
            </section>

            <section className="border-b border-rule bg-background">
              <div className="mx-auto max-w-6xl px-6 py-16 md:py-20">
                <div className="text-center max-w-[70ch] mx-auto mb-16">
                  <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                    BENCHMARK PROOF
                  </span>
                  <h2 className="font-display text-3xl md:text-4xl text-foreground font-semibold mt-4 mb-4">
                    Exact-hash baselines vs. semantic models
                  </h2>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    The MVP keeps partial analysis visible without overstating
                    it, and uses Databricks where local pairwise clustering hits
                    a hard scaling wall.
                  </p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-12">
                  <BenchmarkComparisonCard />
                  <ScaleFailureCard />
                </div>

                <HowItHides />
              </div>
            </section>

            <WhyDatabricksSection />
            <ReviewerDemoFlow />
            <LimitationsSection />
            <ArchitectureDiagram />
            <HowItWorks />
          </>
        }
      >
        <section className="border-b border-rule bg-background text-foreground">
          <div className="mx-auto max-w-6xl px-6 py-16 md:py-20 text-center space-y-6">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-1 rounded-sm font-semibold inline-block">
              SHIPPABLE MVP
            </span>
            <h1 className="font-display text-4xl md:text-6xl font-bold leading-tight max-w-[32ch] mx-auto">
              Astroturf shows evidence where analysis exists, and creates an
              ingestion path where it does not.
            </h1>
            <p className="text-sm md:text-lg text-muted-foreground max-w-[75ch] mx-auto leading-relaxed font-sans">
              The platform surfaces real coordinated-comment analysis for
              federal rulemaking, labels partial baselines honestly, and routes
              unsupported sectors into docket registration rather than fake
              product pages.
            </p>
          </div>
        </section>

        <section className="border-b border-rule bg-card relative">
          <div className="absolute top-0 left-0 bg-brand text-primary-foreground font-sans text-[9px] uppercase tracking-[0.18em] px-4 py-1.5 font-bold z-10">
            Featured Investigation
          </div>
          <Hero
            largestSize={stats.largest_cluster_size}
            daySpan={daySpan}
            agency={copy.agency_short}
            percent={percent}
            ruleShortName={copy.rule_short_name}
            remainingClusters={remainingClusters}
            ruleTitle={copy.rule_title}
            docketId={docketId}
          />
        </section>

        <StatStrip
          largestCampaign={stats.largest_cluster_size}
          campaignsDetected={stats.cluster_count}
          commentsInCampaigns={stats.comments_in_clusters}
          totalComments={stats.total_comments}
        />
      </LandingShell>

      <footer className="border-t border-rule bg-card">
        <div className="mx-auto max-w-6xl px-6 py-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <span>Source: {dataSourceLabel}</span>
          <span>Embedding: {embeddingModel}</span>
          <span className="tabular-nums">
            Similarity threshold: {similarityThreshold.toFixed(2)}
          </span>
        </div>
      </footer>
    </>
  );
}
