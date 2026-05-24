import { SiteHeader } from "@/components/site-header";
import { listDiscoveredDockets } from "@/lib/docket-catalog";
import { DiscoveriesClient } from "./discoveries-client";
import { getExecutionMode, getExecutionModeLabel } from "@/lib/execution-mode";

export const revalidate = 0; // Dynamic route

export default async function DiscoveriesPage() {
  const dockets = await listDiscoveredDockets();
  const mode = getExecutionMode();
  const modeLabel = getExecutionModeLabel(mode);

  // Present dockets that are in 'discovered' or 'failed' status as candidates for analysis request
  const discoveries = dockets.filter((d) => d.status === "discovered" || d.status === "failed");

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />
      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-10 flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                OVERSIGHT DISCOVERIES
              </span>
              <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-2">
                Discovered Rulemakings
              </h1>
              <p className="text-sm text-muted-foreground max-w-[76ch] leading-relaxed">
                Dockets discovered proactively by Autopilot crawler sweeps. Review priority scores, estimate sizes, 
                and trigger semantic analysis pipelines or add items to active watchlists.
              </p>
            </div>

            <div className="flex flex-col items-start md:items-end gap-1.5">
              <span className="text-[9px] uppercase tracking-wider text-muted-foreground font-mono">
                System Active Execution Tier
              </span>
              <span
                className={`text-[10px] uppercase font-sans tracking-wider px-2.5 py-1 rounded-sm font-bold border ${
                  mode === "databricks_job"
                    ? "bg-green-500/10 border-green-500/20 text-green-500"
                    : mode === "local_process"
                    ? "bg-blue-500/10 border-blue-500/20 text-blue-500"
                    : "bg-amber-500/10 border-amber-500/20 text-amber-500"
                }`}
              >
                {modeLabel}
              </span>
            </div>
          </div>

          <DiscoveriesClient initialDiscoveries={discoveries} executionMode={mode} />
        </section>
      </main>
    </>
  );
}
