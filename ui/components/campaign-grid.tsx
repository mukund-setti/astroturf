"use client";

import { useMemo } from "react";
import { CampaignCard } from "@/components/campaign-card";
import type { ClusterSummary } from "@/lib/types";
import { formatInt } from "@/lib/format";

interface CampaignGridProps {
  clusters: ClusterSummary[];
  query: string;
}

export function CampaignGrid({ clusters, query }: CampaignGridProps) {
  const q = query.trim().toLowerCase();

  const filtered = useMemo(() => {
    if (!q) return clusters;
    return clusters.filter((c) => {
      const text = (c.rep_text_preview ?? "").toLowerCase();
      const name = (c.rep_submitter_name ?? "").toLowerCase();
      return text.includes(q) || name.includes(q);
    });
  }, [q, clusters]);

  const [featured, ...rest] = filtered;
  const totalLabel =
    filtered.length === clusters.length
      ? `Showing all ${formatInt(clusters.length)} clusters`
      : `Showing ${formatInt(filtered.length)} of ${formatInt(
          clusters.length,
        )} clusters`;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-4 flex-wrap mb-10">
        <h2 className="font-display text-2xl md:text-3xl tracking-tight text-foreground">
          Detected clusters
        </h2>
        <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
          {totalLabel}
        </span>
      </div>

      {filtered.length === 0 ? (
        <p className="py-12 text-center text-muted-foreground">
          No clusters match &ldquo;{query}&rdquo;.
        </p>
      ) : (
        <>
          {featured ? (
            <CampaignCard
              key={featured.cluster_id}
              cluster={featured}
              variant="featured"
            />
          ) : null}

          {rest.length > 0 ? (
            <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {rest.map((c) => (
                <CampaignCard
                  key={c.cluster_id}
                  cluster={c}
                  variant="default"
                />
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
