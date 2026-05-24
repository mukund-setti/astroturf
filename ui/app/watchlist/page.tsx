import { SiteHeader } from "@/components/site-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { listWatchItems } from "@/lib/watchlist-store";
import { DOCKETS, TOPICS, AGENCIES } from "@/lib/fallback-data";
import { WatchlistClient } from "./watchlist-client";

export const revalidate = 0; // Dynamic route

export default async function WatchlistPage() {
  const watchItems = await listWatchItems();

  // Resolve coverage details for each watch item
  const hydratedItems = watchItems.map((item) => {
    let coverageStatus: "analyzed" | "baseline_only" | "monitoring" | "none" = "none";
    let coverageLabel = "No coverage";

    if (item.kind === "topic") {
      const topic = TOPICS.find((t) => t.id === item.value);
      if (topic) {
        if (topic.status === "analyzed") {
          coverageStatus = "analyzed";
          coverageLabel = "Analyzed";
        } else if (topic.status === "baseline_only") {
          coverageStatus = "baseline_only";
          coverageLabel = "Baseline Only";
        } else {
          coverageStatus = "monitoring";
          coverageLabel = "Monitoring Active";
        }
      }
    } else if (item.kind === "agency") {
      const agency = AGENCIES.find((a) => a.id.toLowerCase() === item.value.toLowerCase());
      if (agency) {
        if (agency.status === "analyzed") {
          coverageStatus = "analyzed";
          coverageLabel = "Analyzed";
        } else if (agency.status === "baseline_only") {
          coverageStatus = "baseline_only";
          coverageLabel = "Baseline Only";
        } else {
          coverageStatus = "monitoring";
          coverageLabel = "Monitoring Active";
        }
      }
    } else if (item.kind === "docket") {
      const docket = DOCKETS.find((d) => d.id.toLowerCase() === item.value.toLowerCase());
      if (docket) {
        if (docket.status === "analyzed") {
          coverageStatus = "analyzed";
          coverageLabel = "Analyzed";
        } else if (docket.status === "baseline_only") {
          coverageStatus = "baseline_only";
          coverageLabel = "Baseline Only";
        } else {
          coverageStatus = "monitoring";
          coverageLabel = "Monitoring Active";
        }
      }
    } else if (item.kind === "keyword") {
      // Find if any docket title matches keyword
      const match = DOCKETS.find(
        (d) =>
          d.title.toLowerCase().includes(item.value.toLowerCase()) ||
          d.description.toLowerCase().includes(item.value.toLowerCase())
      );
      if (match) {
        if (match.status === "analyzed") {
          coverageStatus = "analyzed";
          coverageLabel = `Matched: ${match.id} (Analyzed)`;
        } else {
          coverageStatus = "baseline_only";
          coverageLabel = `Matched: ${match.id} (Baseline Only)`;
        }
      } else {
        coverageStatus = "monitoring";
        coverageLabel = "Active Discovery Search";
      }
    }

    return {
      ...item,
      coverageStatus,
      coverageLabel,
    };
  });

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
