import Link from "next/link";
import type { Metadata } from "next";
import { ConsumerNav } from "@/components/consumer-nav";

export const metadata: Metadata = {
  title: "Advanced tools - Astroturf",
  description:
    "Power-user tools for docket analysis, pipeline configuration, and watchlist management.",
};

const TOOLS = [
  {
    title: "Discoveries",
    href: "/legacy/discoveries",
    description:
      "Browse dockets we've already analyzed or request analysis on a new one.",
  },
  {
    title: "Pipeline configurator",
    href: "/legacy/analyze",
    description:
      "Configure and launch the full ingestion -> embedding -> clustering pipeline for any supported docket.",
  },
  {
    title: "Analysis queue",
    href: "/legacy/analysis",
    description:
      "View the status of queued and running analysis requests, with real-time stage progress.",
  },
  {
    title: "Watchlist",
    href: "/legacy/watchlist",
    description:
      "Track dockets over time and get notified when new coordinated campaigns are detected.",
  },
  {
    title: "System monitor",
    href: "/legacy/monitor",
    description:
      "Operational dashboard showing discovered dockets, pipeline health, and execution history.",
  },
];

export default function AdvancedPage() {
  return (
    <>
      <ConsumerNav />

      <main className="flex-1 bg-background text-foreground">
        <section className="border-b border-rule py-12 md:py-16">
          <div className="mx-auto max-w-3xl px-6 space-y-3">
            <h1 className="font-display text-3xl md:text-4xl font-bold text-foreground leading-tight">
              Advanced tools
            </h1>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-[52ch]">
              Power-user interfaces for pipeline configuration, docket
              analysis, and operational monitoring.
            </p>
          </div>
        </section>

        <section className="py-10 md:py-12">
          <div className="mx-auto max-w-3xl px-6 space-y-4">
            {TOOLS.map((tool) => (
              <Link
                key={tool.href}
                href={tool.href}
                className="group block focus:outline-none"
              >
                <article className="bg-card border border-rule rounded-sm p-6 md:p-8 transition-colors group-hover:border-foreground/30 group-focus-visible:ring-2 group-focus-visible:ring-brand">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="font-display text-lg font-semibold text-foreground group-hover:text-brand transition-colors">
                        {tool.title}
                      </h2>
                      <p className="mt-1 text-sm text-muted-foreground leading-relaxed max-w-[52ch]">
                        {tool.description}
                      </p>
                    </div>
                    <span className="text-brand text-sm font-medium shrink-0 mt-1">
                      {"->"}
                    </span>
                  </div>
                </article>
              </Link>
            ))}
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
          <Link href="/explore" className="hover:text-brand transition-colors">
            Explore
          </Link>
          <span aria-hidden className="text-rule">
            /
          </span>
          <Link href="/learn-more" className="hover:text-brand transition-colors">
            Learn more
          </Link>
          <span aria-hidden className="text-rule">
            /
          </span>
          <span>Advanced</span>
        </div>
      </footer>
    </>
  );
}
