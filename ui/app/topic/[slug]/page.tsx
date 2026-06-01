import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { QueueAnalysisCard } from "@/components/queue-analysis-card";
import { TopicDocketPicker } from "@/components/topic-docket-picker";
import { ConsumerNav } from "@/components/consumer-nav";
import { getTopicBySlug } from "@/lib/topics";
import { listFindingsByTopic } from "@/lib/findings-store";
import type { Finding } from "@/lib/findings-store";
import { listDocketsForTopic } from "@/lib/docket-catalog";
import { formatInt } from "@/lib/format";

export const revalidate = 300;

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const topic = getTopicBySlug(slug);
  if (!topic) return { title: "Topic not found - Astroturf" };
  return {
    title: `Coordinated influence on ${topic.label} - Astroturf`,
    description: `Findings of coordinated public comment campaigns related to ${topic.label} in federal rulemaking.`,
  };
}

export default async function TopicPage({ params }: PageProps) {
  const { slug } = await params;
  const topic = getTopicBySlug(slug);
  if (!topic) notFound();

  const [findings, catalogDockets] = await Promise.all([
    listFindingsByTopic(slug),
    listDocketsForTopic(slug),
  ]);
  const docketIds = new Set(findings.map((f) => f.docket_id));
  const templateCount = findings.length;
  // Dockets we have in the catalog but haven't analyzed yet (no finding).
  // These are the actionable "queue me" candidates shown on otherwise-empty
  // topic pages.
  const unanalyzedDockets = catalogDockets.filter(
    (d) => !docketIds.has(d.docket_id),
  );

  return (
    <>
      <ConsumerNav />

      <main className="flex-1 bg-background text-foreground">
        <section className="border-b border-rule py-12 md:py-16">
          <div className="mx-auto max-w-3xl px-6 space-y-3">
            <h1 className="font-display text-3xl md:text-4xl font-bold text-foreground leading-tight">
              Coordinated influence on {topic.label}
            </h1>
            {findings.length > 0 && (
              <p className="text-sm text-muted-foreground leading-relaxed">
                We found {templateCount} template
                {templateCount === 1 ? "" : "s"} across {docketIds.size}{" "}
                rulemaking{docketIds.size === 1 ? "" : "s"} on {topic.label}.
              </p>
            )}
          </div>
        </section>

        <section className="py-10 md:py-12">
          <div className="mx-auto max-w-3xl px-6 space-y-6">
            {findings.length > 0 &&
              findings.map((finding) => (
                <FindingCard key={finding.id} finding={finding} />
              ))}

            {unanalyzedDockets.length > 0 && (
              <TopicDocketPicker
                topicLabel={topic.label}
                topicSlug={topic.slug}
                heading={
                  findings.length > 0
                    ? `${unanalyzedDockets.length} more docket${unanalyzedDockets.length === 1 ? "" : "s"} ready to analyze`
                    : `${unanalyzedDockets.length} docket${unanalyzedDockets.length === 1 ? "" : "s"} we can analyze for you`
                }
                description={
                  findings.length > 0
                    ? `Astroturf has more federal rulemakings on ${topic.label} cataloged but not yet analyzed. Queue any of them and we'll run the pipeline.`
                    : `We don't have a published finding for ${topic.label} yet, but we have ${unanalyzedDockets.length} federal rulemaking${unanalyzedDockets.length === 1 ? "" : "s"} cataloged. Pick one to queue an analysis.`
                }
                dockets={unanalyzedDockets.map((d) => ({
                  docket_id: d.docket_id,
                  title: d.title,
                  agency_id: d.agency_id,
                  comment_count_estimate: d.comment_count_estimate,
                }))}
              />
            )}

            {findings.length === 0 && unanalyzedDockets.length === 0 && (
              <div className="py-8">
                <QueueAnalysisCard
                  query={topic.label}
                  topicSlug={topic.slug}
                  title={`Want Astroturf to analyze ${topic.label}?`}
                  description={`We do not have a published finding or cataloged docket for ${topic.label} yet. Queue a search and Astroturf will look for a matching federal docket, run the analysis pipeline, and track it in the header.`}
                />
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="border-t border-rule bg-card">
        <div className="mx-auto max-w-3xl px-6 py-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <Link href="/" className="hover:text-brand transition-colors">
            Home
          </Link>
          <span aria-hidden className="text-rule">
            /
          </span>
          <span>{topic.label}</span>
          <span aria-hidden className="text-rule">
            /
          </span>
          <span>
            {templateCount} finding{templateCount === 1 ? "" : "s"}
          </span>
        </div>
      </footer>
    </>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <Link
      href={`/finding/${finding.slug}`}
      className="group block focus:outline-none"
    >
      <article className="bg-card border border-rule rounded-sm p-6 md:p-8 transition-colors group-hover:border-foreground/30 group-focus-visible:ring-2 group-focus-visible:ring-brand">
        <h2 className="font-display text-lg md:text-xl font-semibold text-foreground leading-snug group-hover:text-brand transition-colors">
          {finding.headline}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground leading-relaxed max-w-[64ch]">
          {finding.one_liner}
        </p>
        <div className="mt-4 flex items-center gap-3 text-xs text-muted-foreground">
          <span className="font-display text-base font-bold tabular-nums text-foreground">
            {formatInt(finding.cluster_size)}
          </span>
          <span>comments</span>
          {finding.posted_date_range && (
            <>
              <span aria-hidden className="text-rule">
                /
              </span>
              <span className="tabular-nums">{finding.posted_date_range}</span>
            </>
          )}
          <span className="ml-auto text-brand font-medium group-hover:underline underline-offset-4">
            See the finding
          </span>
        </div>
      </article>
    </Link>
  );
}
