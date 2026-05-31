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
      <header className="sticky top-0 z-30 border-b border-rule/60 bg-background/85 backdrop-blur-md">
        <div className="mx-auto max-w-6xl px-6 py-3.5 flex items-center justify-between gap-6">
          <div className="flex items-center gap-7 min-w-0">
            <Link
              href="/"
              className="group flex items-center gap-2 font-display text-lg tracking-tight text-foreground shrink-0"
            >
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 rounded-full bg-brand transition-transform duration-200 group-hover:scale-125"
              />
              <span className="group-hover:text-brand transition-colors">Astroturf</span>
            </Link>
            <nav className="hidden md:flex items-center gap-1 text-sm">
              <NavLink href="/discoveries">Discoveries</NavLink>
              <NavLink href="/watchlist">Watchlist</NavLink>
              <NavLink href="/monitor">Monitor</NavLink>
              <NavLink href="/analyze">Advanced</NavLink>
              <NavLink href="/analysis">Queue</NavLink>
            </nav>
          </div>

          <SearchAutocomplete
            clusters={clusters}
            query={query}
            onQueryChange={setQuery}
          />
        </div>
        {dataSourceLabel ? (
          <div className="border-t border-rule/40 bg-card/50">
            <div className="mx-auto max-w-6xl px-6 py-1.5 flex items-center justify-between gap-4 text-xs text-muted-foreground/80">
              <span className="inline-flex items-center gap-2">
                <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500/70" />
                <span>{dataSourceLabel}</span>
              </span>
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

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-md px-2.5 py-1.5 text-sm font-medium text-foreground/70 hover:text-foreground hover:bg-secondary/60 transition-colors"
    >
      {children}
    </Link>
  );
}
