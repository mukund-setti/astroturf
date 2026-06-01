import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { getFindingBySlug } from "@/lib/findings-store";
import { getTopicBySlug } from "@/lib/topics";
import { getClusterDetail, getStatsPayload } from "@/lib/databricks";
import type { ClusterRow } from "@/lib/types";
import { formatInt } from "@/lib/format";
import { ConsumerNav } from "@/components/consumer-nav";

export const revalidate = 300;

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const finding = await getFindingBySlug(slug);
  if (!finding) return { title: "Finding not found - Astroturf" };
  return {
    title: `${finding.headline} - Astroturf`,
    description: finding.one_liner,
  };
}

export default async function FindingPage({ params }: PageProps) {
  const { slug } = await params;
  const finding = await getFindingBySlug(slug);
  if (!finding) notFound();

  const topic = getTopicBySlug(finding.topic_slug);

  // Fetch cluster detail for the template quote and total docket stats for the scale bar
  const [clusterData, stats] = await Promise.all([
    getClusterDetail(finding.cluster_id).catch(() => null),
    getStatsPayload(finding.docket_id).catch(() => null),
  ]);

  const representative: ClusterRow | null =
    clusterData?.rows.find((r) => r.is_representative) ??
    clusterData?.rows[0] ??
    null;

  const totalComments = stats?.total_comments ?? 0;
  const coordinated = finding.cluster_size;
  const pctCoordinated =
    totalComments > 0 ? Math.round((coordinated / totalComments) * 100) : 0;

  return (
    <>
      <ConsumerNav />

      <main className="flex-1 bg-background text-foreground">
        {/* Headline section */}
        <section className="border-b border-rule py-12 md:py-16">
          <div className="mx-auto max-w-3xl px-6 space-y-4">
            <h1 className="font-display text-3xl md:text-4xl font-bold text-foreground leading-tight uppercase tracking-wide">
              {finding.headline}
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-[64ch]">
              {finding.one_liner}
            </p>
          </div>
        </section>

        {/* Scale visualization */}
        {totalComments > 0 && (
          <section className="border-b border-rule py-10">
            <div className="mx-auto max-w-3xl px-6 space-y-4">
              <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                Scale
              </p>
              <div className="space-y-2">
                <div className="flex items-baseline gap-2 text-sm">
                  <span className="font-display text-2xl font-bold tabular-nums text-foreground">
                    {formatInt(coordinated)}
                  </span>
                  <span className="text-muted-foreground">
                    of {formatInt(totalComments)} total comments in this docket
                  </span>
                </div>
                {/* Horizontal bar */}
                <div className="w-full h-6 bg-secondary rounded-sm overflow-hidden flex">
                  <div
                    className="bg-brand h-full transition-all duration-500 ease-out rounded-l-sm"
                    style={{
                      width: `${Math.max(pctCoordinated, 2)}%`,
                    }}
                  />
                </div>
                <div className="flex gap-4 text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-sm bg-brand" />
                    Coordinated ({pctCoordinated}%)
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-sm bg-secondary border border-rule" />
                    Other ({100 - pctCoordinated}%)
                  </span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Template quote */}
        {representative?.text_preview && (
          <section className="border-b border-rule py-10 md:py-12">
            <div className="mx-auto max-w-3xl px-6">
              <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-6">
                The template
              </p>
              <blockquote className="relative bg-brand-soft border-l-[3px] border-l-brand p-8 md:p-10">
                <p className="font-display text-base md:text-lg text-foreground leading-relaxed max-w-[64ch] whitespace-pre-wrap">
                  &ldquo;{representative.text_preview}&rdquo;
                </p>
                {representative.submitter_name && (
                  <footer className="mt-6 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                    Representative comment /{" "}
                    {representative.submitter_name}
                  </footer>
                )}
              </blockquote>
            </div>
          </section>
        )}

        {/* Attribution stub */}
        <section className="border-b border-rule py-10 md:py-12">
          <div className="mx-auto max-w-3xl px-6">
            <h2 className="font-display text-xl font-semibold text-foreground mb-3">
              Who organized this?
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-[60ch]">
              We&apos;re still investigating this campaign. Attribution analysis
              looks for evidence linking coordinated comment templates to known
              advocacy organizations - but it does not assume motives or assign
              blame.
            </p>
          </div>
        </section>

        {/* Migration stub */}
        <section className="border-b border-rule py-10 md:py-12 bg-card">
          <div className="mx-auto max-w-3xl px-6">
            <h2 className="font-display text-xl font-semibold text-foreground mb-3">
              Did it influence the final rule?
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-[60ch]">
              Migration analysis has not yet been run for this docket. When
              available, it compares the campaign&apos;s language to the final
              rule text - looking for phrase-level overlap, not claiming causal
              influence.
            </p>
          </div>
        </section>

        {/* Technical details (collapsed) */}
        <section className="py-10 md:py-12">
          <div className="mx-auto max-w-3xl px-6">
            <details className="group">
              <summary className="cursor-pointer select-none text-sm font-medium text-muted-foreground hover:text-foreground transition-colors list-none">
                <span className="inline-flex items-center gap-2">
                  <span className="text-xs transition-transform duration-200 group-open:rotate-90">
                    {" > "}
                  </span>
                  Technical details
                </span>
              </summary>
              <div className="mt-6 space-y-3 text-xs text-muted-foreground">
                <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                  <span className="font-medium text-foreground/70">
                    Cluster ID
                  </span>
                  <code className="font-mono text-[11px] break-all">
                    {finding.cluster_id}
                  </code>

                  <span className="font-medium text-foreground/70">
                    Docket ID
                  </span>
                  <code className="font-mono text-[11px]">
                    {finding.docket_id}
                  </code>

                  {representative && (
                    <>
                      <span className="font-medium text-foreground/70">
                        Embedding model
                      </span>
                      <code className="font-mono text-[11px]">
                        {representative.embedding_model}
                      </code>

                      <span className="font-medium text-foreground/70">
                        Similarity threshold
                      </span>
                      <code className="font-mono text-[11px] tabular-nums">
                        {representative.similarity_threshold.toFixed(4)}
                      </code>
                    </>
                  )}

                  <span className="font-medium text-foreground/70">
                    Finding slug
                  </span>
                  <code className="font-mono text-[11px]">{finding.slug}</code>

                  <span className="font-medium text-foreground/70">
                    Generated
                  </span>
                  <span className="tabular-nums">
                    {finding.auto_generated ? "Auto" : "Manual"}
                    {finding.manually_edited ? " (edited)" : ""}
                  </span>
                </div>

                <div className="pt-4">
                  <Link
                    href={`/legacy/campaign/${finding.cluster_id}`}
                    className="inline-flex items-center gap-2 text-brand hover:underline underline-offset-4 text-sm font-medium transition-colors"
                  >
                    View all {formatInt(finding.cluster_size)} member comments {"->"}
                  </Link>
                </div>
              </div>
            </details>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-rule bg-card">
        <div className="mx-auto max-w-3xl px-6 py-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <Link href="/" className="hover:text-brand transition-colors">
            Home
          </Link>
          <span aria-hidden className="text-rule">
            /
          </span>
          {topic && (
            <>
              <Link
                href={`/topic/${finding.topic_slug}`}
                className="hover:text-brand transition-colors"
              >
                {topic.label}
              </Link>
              <span aria-hidden className="text-rule">
                /
              </span>
            </>
          )}
          <span>Docket {finding.docket_id}</span>
        </div>
      </footer>
    </>
  );
}
