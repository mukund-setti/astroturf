"use client";

import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useState, useRef, useCallback, Suspense } from "react";
import { ConsumerNav } from "@/components/consumer-nav";

interface ScoredTopic {
  slug: string;
  label: string;
  score: number;
}

interface ExploreResult {
  query: string;
  match: ScoredTopic;
  candidates: ScoredTopic[];
  threshold: number;
  should_redirect: boolean;
  redirect_url: string | null;
  algorithm: string;
}

interface QueueResult {
  request_id: string;
  docket_id: string;
  docket_title: string;
  status: string;
  estimated_minutes: number;
  needs_docket_match?: boolean;
}

function ExploreInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialQ = searchParams.get("q") ?? "";
  const forceQueue = searchParams.get("queue") === "1";
  const [query, setQuery] = useState(initialQ);
  const [result, setResult] = useState<ExploreResult | null>(null);
  const [loading, setLoading] = useState(!!initialQ);
  const [searched, setSearched] = useState(!!initialQ);
  const didInit = useRef(false);

  // Queue state for unmatched queries
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueResult, setQueueResult] = useState<QueueResult | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);

  const doSearch = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      setLoading(true);
      setSearched(true);
      setQueueResult(null);
      setQueueError(null);
      try {
        const res = await fetch(`/api/explore?q=${encodeURIComponent(trimmed)}`);
        if (!res.ok) return;
        const data: ExploreResult = await res.json();
        setResult(data);
        if (!forceQueue && data.should_redirect && data.redirect_url) {
          router.push(data.redirect_url);
        }
      } finally {
        setLoading(false);
      }
    },
    [router, forceQueue],
  );

  const searchRef = useCallback(
    (node: HTMLInputElement | null) => {
      if (node && !didInit.current && initialQ) {
        didInit.current = true;
        doSearch(initialQ);
      }
    },
    [initialQ, doSearch],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const url = new URL(window.location.href);
    url.searchParams.set("q", query.trim());
    window.history.replaceState(null, "", url.toString());
    doSearch(query);
  };

  async function handleQueueAnalysis() {
    setQueueLoading(true);
    setQueueError(null);
    try {
      const res = await fetch("/api/queue-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: result?.query ?? query.trim() }),
      });
      if (res.status === 404) {
        setQueueError("no_docket_match");
        return;
      }
      if (!res.ok) {
        setQueueError("server_error");
        return;
      }
      const data: QueueResult = await res.json();
      setQueueResult(data);
    } catch {
      setQueueError("server_error");
    } finally {
      setQueueLoading(false);
    }
  }

  const meaningful = result?.candidates.filter((c) => c.score > 0) ?? [];
  const shouldShowQueuePrompt =
    searched && !loading && result && (forceQueue || meaningful.length === 0);

  return (
    <>
      <ConsumerNav />

      <main className="flex-1 bg-background text-foreground">
        {/* Search section */}
        <section className="border-b border-rule py-12 md:py-16">
          <div className="mx-auto max-w-3xl px-6 space-y-6">
            <h1 className="font-display text-3xl md:text-4xl font-bold text-foreground leading-tight">
              Explore
            </h1>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-[52ch]">
              Search by policy topic, agency name, or issue area. We&apos;ll
              match your query to the topics we&apos;ve analyzed and show you
              what we&apos;ve found.
            </p>
            <form onSubmit={handleSubmit} className="flex gap-3 max-w-lg">
              <input
                ref={searchRef}
                id="explore-search-input"
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. internet regulation, climate change, student loans..."
                className="flex-1 bg-card border border-rule rounded-sm px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent transition-shadow"
                autoFocus
              />
              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="bg-brand text-white font-medium text-sm px-6 py-3 rounded-sm hover:bg-brand/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                {loading ? "Searching..." : "Search"}
              </button>
            </form>
          </div>
        </section>

        {/* Results */}
        <section className="py-10 md:py-12">
          <div className="mx-auto max-w-3xl px-6 space-y-4">
            {/* Matched topics */}
            {searched && !loading && result && meaningful.length > 0 && !forceQueue && (
              <>
                <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-6">
                  {meaningful.length} topic
                  {meaningful.length === 1 ? "" : "s"} matched &ldquo;
                  {result.query}&rdquo;
                </p>
                {meaningful.map((topic) => (
                  <Link
                    key={topic.slug}
                    href={`/topic/${topic.slug}`}
                    className="group block focus:outline-none"
                  >
                    <article className="bg-card border border-rule rounded-sm p-6 md:p-8 transition-colors group-hover:border-foreground/30 group-focus-visible:ring-2 group-focus-visible:ring-brand flex items-center gap-6">
                      <div className="flex-1 min-w-0">
                        <h2 className="font-display text-lg font-semibold text-foreground group-hover:text-brand transition-colors">
                          {topic.label}
                        </h2>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <div className="text-right">
                          <span className="font-display text-xl font-bold tabular-nums text-foreground">
                            {Math.round(topic.score * 100)}%
                          </span>
                          <span className="block text-[10px] text-muted-foreground uppercase tracking-wider">
                            match
                          </span>
                        </div>
                        <span className="text-brand text-sm font-medium group-hover:underline underline-offset-4">
                          {"->"}
                        </span>
                      </div>
                    </article>
                  </Link>
                ))}
              </>
            )}

            {/* No match - queue analysis CTA */}
            {shouldShowQueuePrompt && !queueResult && (
              <div className="py-10 space-y-6">
                <div className="bg-card border border-rule rounded-sm p-8 space-y-4">
                  <h2 className="font-display text-xl font-semibold text-foreground">
                    Analyze &ldquo;{result?.query}&rdquo;?
                  </h2>
                  <p className="text-sm text-muted-foreground leading-relaxed max-w-[52ch]">
                    We&apos;ll look for the strongest matching federal
                    rulemaking docket, queue a Databricks analysis run, and
                    track the request in your header. You can keep browsing
                    while it runs.
                  </p>
                  {meaningful.length > 0 && (
                    <p className="text-xs text-muted-foreground leading-relaxed max-w-[52ch]">
                      Closest analyzed topic:{" "}
                      <Link
                        href={`/topic/${meaningful[0].slug}`}
                        className="text-brand hover:underline underline-offset-4"
                      >
                        {meaningful[0].label}
                      </Link>
                      . Queue a fresh analysis if you want Astroturf to look
                      beyond what is already surfaced.
                    </p>
                  )}
                  <div className="flex gap-3 pt-2">
                    <button
                      type="button"
                      onClick={handleQueueAnalysis}
                      disabled={queueLoading}
                      className="bg-brand text-white font-medium text-sm px-6 py-3 rounded-sm hover:bg-brand/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {queueLoading
                        ? "Searching dockets..."
                        : "Yes, queue analysis"}
                    </button>
                    <Link
                      href="/advanced"
                      className="border border-rule text-muted-foreground font-medium text-sm px-6 py-3 rounded-sm hover:border-foreground/30 hover:text-foreground transition-colors"
                    >
                      Manual entry
                    </Link>
                  </div>
                  {queueError === "no_docket_match" && (
                    <p className="text-sm text-muted-foreground pt-2">
                      We could not reach the docket resolver. Try again in a
                      moment, or use{" "}
                      <Link href="/advanced" className="text-brand hover:underline">
                        advanced
                      </Link>{" "}
                      if you already know the docket ID.
                    </p>
                  )}
                  {queueError === "server_error" && (
                    <p className="text-sm text-red-600 pt-2">
                      Something went wrong. Please try again.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Queue success */}
            {queueResult && (
              <div className="py-10">
                <div className="bg-card border border-brand/30 rounded-sm p-8 space-y-4">
                  <div className="flex items-center gap-2">
                    <span className="flex h-2 w-2 relative">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
                    </span>
                    <h2 className="font-display text-lg font-semibold text-foreground">
                      Analysis queued
                    </h2>
                  </div>
                  {queueResult.needs_docket_match ? (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      We queued a docket search for{" "}
                      <span className="text-foreground font-medium">
                        {result?.query ?? query}
                      </span>
                      . An operator can map it to the strongest federal docket
                      before the analysis run starts.
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      We&apos;re analyzing{" "}
                      <span className="text-foreground font-medium">
                        {queueResult.docket_title}
                      </span>{" "}
                      ({queueResult.docket_id}). Estimated time:{" "}
                      ~{queueResult.estimated_minutes} minutes.
                    </p>
                  )}
                  <p className="text-sm text-muted-foreground">
                    Track progress in the{" "}
                    <span className="text-brand font-medium">
                      requests badge
                    </span>{" "}
                    in the header. We&apos;ll link you to the finding when
                    it&apos;s ready.
                  </p>
                  <Link
                    href="/"
                    className="inline-block text-sm text-brand hover:underline underline-offset-4 font-medium pt-2"
                  >
                    {"<-"} Back to home
                  </Link>
                </div>
              </div>
            )}

            {searched && !loading && !result && (
              <div className="py-16 text-center">
                <p className="text-muted-foreground text-sm">
                  Something went wrong. Please try again.
                </p>
              </div>
            )}
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
          <span>Explore</span>
        </div>
      </footer>
    </>
  );
}

export default function ExplorePage() {
  return (
    <Suspense>
      <ExploreInner />
    </Suspense>
  );
}
