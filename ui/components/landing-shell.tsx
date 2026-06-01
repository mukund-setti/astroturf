"use client";

import { type ReactNode } from "react";
import { CampaignGrid } from "@/components/campaign-grid";
import { ConsumerNav } from "@/components/consumer-nav";
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
 * Client wrapper for the learn-more page. The top navigation intentionally
 * matches the consumer UI so the user can always return home.
 *
 * `afterGrid` is an optional slot for static sections rendered below the
 * cluster grid (e.g. architecture diagram, how-it-works, roadmap). They do
 * not participate in the search filtering.
 */
export function LandingShell({
  clusters,
  children,
  afterGrid,
}: LandingShellProps) {
  const query = "";

  return (
    <>
      <ConsumerNav />

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
