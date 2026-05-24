"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { SearchAutocomplete } from "@/components/search-autocomplete";
import { CampaignGrid } from "@/components/campaign-grid";
import { DataDiagnostics } from "@/components/data-diagnostics";
import type { ClusterSummary } from "@/lib/types";
import type { DataDiagnostics as DataDiagnosticsPayload } from "@/lib/databricks";

interface LandingShellProps {
  clusters: ClusterSummary[];
  children: ReactNode;
  afterGrid?: ReactNode;
  dataSourceLabel?: string;
  diagnostics?: DataDiagnosticsPayload;
}

/**
 * Client wrapper for the landing page. Owns the search-query state so the
 * masthead autocomplete and the cluster grid below stay in sync. Hero, stat
 * strip, and other server-rendered sections are passed through as children
 * and are not re-rendered when the search changes — only the grid filters.
 *
 * `afterGrid` is an optional slot for static sections rendered below the
 * cluster grid (e.g. architecture diagram, how-it-works, roadmap). They do
 * not participate in the search filtering.
 */
export function LandingShell({
  clusters,
  children,
  afterGrid,
  dataSourceLabel,
  diagnostics,
}: LandingShellProps) {
  const [query, setQuery] = useState("");

  return (
    <>
      <header className="border-b border-rule bg-background relative z-30">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between gap-4">
          <Link
            href="/"
            className="font-display text-lg tracking-tight text-foreground hover:text-brand transition-colors"
          >
            Astroturf
          </Link>

          <SearchAutocomplete
            clusters={clusters}
            query={query}
            onQueryChange={setQuery}
          />
        </div>
        {dataSourceLabel ? (
          <div className="border-t border-rule/60 bg-card/40">
            <div className="mx-auto max-w-6xl px-6 py-1.5 flex items-center justify-between gap-4 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              <span>{dataSourceLabel}</span>
              {diagnostics ? <DataDiagnostics diagnostics={diagnostics} /> : null}
            </div>
          </div>
        ) : null}
      </header>

      <main className="flex-1">
        {children}
        <section className="mx-auto max-w-6xl px-6 py-16 md:py-20">
          <CampaignGrid clusters={clusters} query={query} />
        </section>
        {afterGrid}
      </main>
    </>
  );
}
