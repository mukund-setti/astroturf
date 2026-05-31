import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import {
  listAvailableDiscoveries,
  listAnalyzedDockets,
} from "@/lib/docket-catalog";
import { DiscoveriesClient } from "./discoveries-client";
import { getExecutionMode, getExecutionModeLabel } from "@/lib/execution-mode";
import { formatInt } from "@/lib/format";

export const revalidate = 0; // Dynamic route

export default async function DiscoveriesPage() {
  // Fetch both lists in parallel:
  //   - listAvailableDiscoveries: dockets validated against the source API
  //     but not yet sent through the pipeline.
  //   - listAnalyzedDockets: dockets with at least one succeeded pipeline run
  //     so we can render a "Recently analyzed" section. The page is never
  //     empty as long as the catalog has at least one validated docket.
  const [discoveries, analyzed] = await Promise.all([
    listAvailableDiscoveries(),
    listAnalyzedDockets(),
  ]);
  const mode = getExecutionMode();
  const modeLabel = getExecutionModeLabel(mode);

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />
      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="pb-10 mb-10 flex flex-col md:flex-row md:items-end justify-between gap-6 border-b border-rule/60">
            <div>
              <p className="text-sm text-brand font-medium mb-3">Oversight discoveries</p>
              <h1 className="font-display text-4xl md:text-5xl font-semibold tracking-tight leading-tight mb-3">
                Discovered rulemakings
              </h1>
              <p className="text-base text-foreground/70 max-w-[64ch] leading-relaxed">
                Federal dockets surfaced by the discovery autopilot and validated against{" "}
                regulations.gov + the FCC ECFS public API. Click any card to spin up a real
                pipeline run on Databricks.
              </p>
            </div>

            <span
              className={`inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-3 py-1.5 border self-start ${
                mode === "databricks_job"
                  ? "bg-emerald-500/10 border-emerald-500/25 text-emerald-700"
                  : mode === "local_process"
                  ? "bg-blue-500/10 border-blue-500/25 text-blue-700"
                  : "bg-amber-500/10 border-amber-500/25 text-amber-700"
              }`}
              title="What clicking a docket card actually triggers."
            >
              <span
                aria-hidden="true"
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  mode === "databricks_job"
                    ? "bg-emerald-500"
                    : mode === "local_process"
                    ? "bg-blue-500"
                    : "bg-amber-500"
                }`}
              />
              {modeLabel}
            </span>
          </div>

          <DiscoveriesClient initialDiscoveries={discoveries} executionMode={mode} />

          {analyzed.length > 0 ? (
            <section className="mt-16">
              <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
                <div>
                  <p className="text-sm text-brand font-medium mb-2">Already analyzed</p>
                  <h2 className="font-display text-2xl md:text-3xl font-semibold tracking-tight">
                    Recently analyzed rulemakings ({analyzed.length})
                  </h2>
                </div>
                <Link
                  href="/analysis"
                  className="text-sm text-brand font-medium hover:underline"
                >
                  See full queue →
                </Link>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {analyzed.map((doc) => {
                  const completed = new Date(doc.latest_run_completed_at);
                  return (
                    <Link
                      key={doc.docket_id}
                      href={`/analysis/${doc.latest_request_id}`}
                      className="group block rounded-xl border border-rule/60 bg-card p-5 transition-all duration-200 hover:-translate-y-0.5"
                      style={{ boxShadow: "var(--shadow-soft)" }}
                    >
                      <div className="flex items-start justify-between gap-3 mb-3">
                        <span className="font-mono text-xs text-foreground/80 font-semibold">
                          {doc.docket_id}
                        </span>
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2 py-0.5 border bg-emerald-500/10 border-emerald-500/25 text-emerald-700">
                          <span
                            aria-hidden="true"
                            className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"
                          />
                          Analyzed
                        </span>
                      </div>
                      <h3 className="font-display text-base font-semibold text-foreground leading-tight mb-2 group-hover:text-brand transition-colors">
                        {doc.title}
                      </h3>
                      <p className="text-xs text-muted-foreground leading-relaxed mb-3 line-clamp-2">
                        {doc.summary}
                      </p>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>{doc.agency_id}</span>
                        <span aria-hidden="true">·</span>
                        <span>{doc.source === "ecfs" ? "FCC ECFS" : "regulations.gov"}</span>
                        {doc.validated_comment_count !== null ? (
                          <>
                            <span aria-hidden="true">·</span>
                            <span className="tabular-nums">
                              {formatInt(doc.validated_comment_count)} on record
                            </span>
                          </>
                        ) : null}
                        <span aria-hidden="true">·</span>
                        <span>{completed.toLocaleDateString()}</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </section>
          ) : null}
        </section>
      </main>
    </>
  );
}
