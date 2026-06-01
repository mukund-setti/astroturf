import { SiteHeader } from "@/components/site-header";
import { listWatchItems } from "@/lib/watchlist-store";
import { hydrateWatchItem } from "@/lib/watchlist-coverage";
import { WatchlistClient } from "./watchlist-client";

export const revalidate = 0; // Dynamic route

export default async function WatchlistPage() {
  const watchItems = await listWatchItems();
  const hydratedItems = watchItems.map(hydrateWatchItem);

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />
      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-10">
            <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
              OVERSIGHT CENTER
            </span>
            <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-4">
              Watchlist
            </h1>
            <p className="text-sm md:text-base text-muted-foreground max-w-[76ch] leading-relaxed">
              Monitored rulemaking watchlists. Add custom keywords, specific agencies, topics, or dockets. 
              Autopilot continuously audits new filings against active items and alerts when relevant clusters are detected.
            </p>
          </div>

          <WatchlistClient initialItems={hydratedItems} />
        </section>
      </main>
    </>
  );
}
