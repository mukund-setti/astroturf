import { SiteHeader } from "@/components/site-header";
import { AnalyzeForm, type DocketPreset } from "@/components/analyze-form";
import type { ReactNode } from "react";
import {
  AGENCIES,
  DOCKETS,
  INGESTION_TEMPLATE_TOPICS,
  PRIMARY_ANALYSIS_TOPICS,
  getDocketById,
  getDocketsForAgency,
  getDocketsForTopic,
} from "@/lib/fallback-data";

interface PageProps {
  searchParams: Promise<{
    docket?: string;
    source?: string;
    topic?: string;
    agency?: string;
    query?: string;
  }>;
}

export const revalidate = 3600;

/** Map UI agency ID to the canonical bronze `source` value. */
function sourceForAgency(agencyId: string | undefined): string {
  if (!agencyId) return "regulations_gov";
  return agencyId.toUpperCase() === "FCC" ? "ecfs" : "regulations_gov";
}

/** Project a Docket entity onto the AnalyzeForm preset shape. */
function docketToPreset(
  docket: ReturnType<typeof getDocketById>,
): DocketPreset | null {
  if (!docket) return null;
  return {
    docketId: docket.id,
    source: sourceForAgency(docket.agencyId),
    topicId: docket.topicId,
    agencyId: docket.agencyId,
    title: docket.ruleShortName
      ? docket.ruleTitle ?? docket.title
      : docket.title,
    expectedScale: docket.totalComments ? String(docket.totalComments) : "",
    notes:
      docket.validationSummary ||
      "Registered from the Astroturf Analyze a docket workflow.",
  };
}

import { getExecutionMode, getExecutionModeLabel } from "@/lib/execution-mode";

export default async function AnalyzePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const docketIdParam = params.docket ?? "";
  const selectedTopic = params.topic ?? "";
  const selectedAgency = params.agency ?? "";
  const requestedSource = params.source ?? "";
  const title = params.query
    ? `Analyze a docket for "${params.query}"`
    : "Analyze a docket";

  // Resolve the active execution mode and label
  const mode = getExecutionMode();
  const modeLabel = getExecutionModeLabel(mode);

  // Resolve the best autofill match from URL params, in priority order:
  // explicit docket > agency+topic > agency > topic.
  let preset: DocketPreset | null = null;
  if (docketIdParam) {
    preset = docketToPreset(getDocketById(docketIdParam));
  }
  if (!preset && selectedAgency && selectedTopic) {
    const candidates = getDocketsForAgency(selectedAgency).filter(
      (d) => d.topicId === selectedTopic,
    );
    preset = docketToPreset(candidates[0]);
  }
  if (!preset && selectedAgency) {
    preset = docketToPreset(getDocketsForAgency(selectedAgency)[0]);
  }
  if (!preset && selectedTopic) {
    preset = docketToPreset(getDocketsForTopic(selectedTopic)[0]);
  }

  // Final defaults: anything in the URL beats the resolved preset for the
  // explicit fields the user asked for, but the rest of the preset wins.
  const initial: DocketPreset = {
    docketId: docketIdParam || preset?.docketId || "",
    source:
      requestedSource ||
      preset?.source ||
      sourceForAgency(selectedAgency) ||
      "regulations_gov",
    topicId: selectedTopic || preset?.topicId || "",
    agencyId: selectedAgency || preset?.agencyId || "",
    title: preset?.title ?? "",
    expectedScale: preset?.expectedScale ?? "",
    notes:
      preset?.notes ??
      "Registered from the Astroturf Analyze a docket workflow.",
  };

  // Quick-pick options: every known docket in fallback-data.
  const knownDockets: DocketPreset[] = DOCKETS.map(
    (docket) => docketToPreset(docket) as DocketPreset,
  );

  return (
    <>
      <SiteHeader backHref="/" backLabel="Landing" />
      <main className="flex-1 bg-background text-foreground pb-20">
        <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
          <div className="border-b border-rule pb-8 mb-10 flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <span className="text-[10px] font-sans uppercase tracking-[0.24em] text-brand bg-brand/10 px-2 py-0.5 rounded-sm font-medium">
                ADVANCED CONFIGURATION
              </span>
              <h1 className="font-display text-4xl md:text-5xl font-semibold mt-4 mb-2">
                {title}
              </h1>
              <p className="text-sm text-muted-foreground max-w-[76ch] leading-relaxed">
                Configure rulemakings manually to generate Unity Catalog Delta tables, date windows, and custom ingestion parameters. 
                For broad topic monitoring, use the <a href="/watchlist" className="text-brand hover:underline font-semibold">Watchlist</a> or 
                the <a href="/discoveries" className="text-brand hover:underline font-semibold">Discovered Rulemakings</a> panel.
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

          <AnalyzeForm
            key={JSON.stringify(initial)}
            initial={initial}
            knownDockets={knownDockets}
            executionMode={mode}
          />

          <section className="mt-10 border-t border-rule pt-8">
            <h2 className="font-display text-2xl font-semibold mb-4">
              Coverage policy
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-muted-foreground leading-relaxed">
              <Policy title="Analyzed">
                Appears in primary browsing with semantic clusters and validation
                receipts.
              </Policy>
              <Policy title="Baseline only">
                Appears with exact-hash metrics and an explicit semantic
                clustering next step.
              </Policy>
              <Policy title="Ingestion ready">
                Appears as a workflow or template, never as a zero-result
                dashboard.
              </Policy>
            </div>
          </section>

          <section className="mt-10 bg-card border border-rule rounded-sm p-6">
            <h2 className="font-display text-xl font-semibold mb-3">
              Template topics
            </h2>
            <div className="flex flex-wrap gap-2">
              {[...PRIMARY_ANALYSIS_TOPICS, ...INGESTION_TEMPLATE_TOPICS].map((topic) => (
                <a
                  key={topic.id}
                  href={`/analyze?topic=${topic.id}`}
                  className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors"
                >
                  {topic.name}
                </a>
              ))}
            </div>
            <h3 className="font-display text-xl font-semibold mt-6 mb-3">
              Supported agencies
            </h3>
            <div className="flex flex-wrap gap-2">
              {AGENCIES.filter((agency) => agency.visibility !== "hidden").map((agency) => (
                <a
                  key={agency.id}
                  href={`/analyze?agency=${agency.id}`}
                  className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors"
                >
                  {agency.id}
                </a>
              ))}
            </div>
            <p className="mt-4 text-[11px] text-muted-foreground leading-relaxed">
              Tip: clicking a chip pre-fills the form by finding a known docket
              for that agency or topic (e.g.
              <code className="font-mono mx-1">/analyze?agency=SEC</code>
              autofills the SEC digital-asset-custody docket).
            </p>
          </section>
        </section>
      </main>
    </>
  );
}

function Policy({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-rule bg-card rounded-sm p-4">
      <h3 className="font-sans text-[11px] uppercase tracking-wider text-foreground font-semibold mb-2">
        {title}
      </h3>
      <p>{children}</p>
    </div>
  );
}
