import Link from "next/link";
import { TOPICS } from "@/lib/topics";
import {
  getFeaturedFindings,
  listAvailableTopicSlugs,
} from "@/lib/findings-store";
import type { Finding } from "@/lib/findings-store";
import { formatInt } from "@/lib/format";
import { TopicBubbles } from "@/components/topic-bubbles";
import { ConsumerNav } from "@/components/consumer-nav";

export const revalidate = 300;

export default async function HomePage() {
  const [featured, available] = await Promise.all([
    getFeaturedFindings(6),
    listAvailableTopicSlugs(),
  ]);

  // Initial bubbles: curated TOPICS that have content the user can
  // actually click through to — either at least one finding OR at least
  // one docket in docket_catalog. The topic page renders findings when
  // they exist and an actionable docket picker otherwise, so every
  // visible bubble lands on something real.
  const initialBubbles = TOPICS.filter((t) => available.has(t.slug)).map((t) => ({
    type: "topic" as const,
    label: t.label,
    href: `/topic/${t.slug}`,
  }));

  return (
    <>
      <ConsumerNav />

      <main className="flex-1 bg-background text-foreground">
        {/* Hero + morphing bubbles */}
        <section className="py-16 md:py-24 border-b border-rule">
          <div className="mx-auto max-w-3xl px-6 space-y-8">
            <div className="space-y-6">
              <h1 className="font-display text-4xl md:text-5xl font-bold text-foreground leading-[1.1] tracking-tight max-w-[18ch]">
                Who&apos;s lobbying your government?
              </h1>
              <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-[52ch]">
                Every year, thousands of coordinated form-letter campaigns
                flood federal rulemaking dockets. We detect them so you can
                see who&apos;s behind the noise.
              </p>
            </div>

            <TopicBubbles initial={initialBubbles} />
          </div>
        </section>

        {/* Featured findings */}
        {featured.length > 0 && (
          <section className="py-10 md:py-14">
            <div className="mx-auto max-w-3xl px-6 space-y-6">
              <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                Substantial recent findings
              </p>
              <div className="space-y-4">
                {featured.map((finding) => (
                  <FindingRow key={finding.id} finding={finding} />
                ))}
              </div>
            </div>
          </section>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-rule bg-card">
        <div className="mx-auto max-w-3xl px-6 py-8 space-y-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            <Link href="/" className="hover:text-brand transition-colors">
              Home
            </Link>
            <span aria-hidden className="text-rule">
              /
            </span>
            <Link
              href="/explore"
              className="hover:text-brand transition-colors"
            >
              Explore
            </Link>
            <span aria-hidden className="text-rule">
              /
            </span>
            <Link
              href="/learn-more"
              className="hover:text-brand transition-colors"
            >
              Learn more
            </Link>
            <span aria-hidden className="text-rule">
              /
            </span>
            <Link
              href="/advanced"
              className="hover:text-brand transition-colors"
            >
              Advanced
            </Link>
          </div>
          <p className="text-[11px] text-muted-foreground leading-relaxed max-w-[60ch]">
            Astroturf detects coordinated public comment campaigns in federal
            rulemaking. Findings are evidence packets with caveats, not
            accusations. Always verify before citing.
          </p>
        </div>
      </footer>
    </>
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <Link
      href={`/finding/${finding.slug}`}
      className="group block focus:outline-none"
    >
      <article className="bg-card border border-rule rounded-sm p-5 md:p-6 transition-colors group-hover:border-foreground/30 group-focus-visible:ring-2 group-focus-visible:ring-brand">
        <div className="flex items-start gap-4">
          <span className="font-display text-xl md:text-2xl font-bold tabular-nums text-foreground leading-none shrink-0 pt-0.5">
            {formatInt(finding.cluster_size)}
          </span>
          <div className="flex-1 min-w-0">
            <h2 className="font-display text-base md:text-lg font-semibold text-foreground leading-snug group-hover:text-brand transition-colors">
              {finding.headline}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground leading-relaxed line-clamp-2">
              {finding.one_liner}
            </p>
          </div>
          <span className="text-brand text-sm font-medium shrink-0 opacity-0 group-hover:opacity-100 transition-opacity hidden md:block">
            {"->"}
          </span>
        </div>
      </article>
    </Link>
  );
}
