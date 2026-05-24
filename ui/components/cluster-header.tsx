import { ReactNode } from "react";
import {
  daysBetweenInclusive,
  formatDate,
  formatDateRange,
  formatInt,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ClusterRow } from "@/lib/types";

interface ClusterHeaderProps {
  clusterId: string;
  clusterSize: number;
  representative: ClusterRow;
  earliestPostedDate: string | null;
  latestPostedDate: string | null;
  embeddingModel: string;
  similarityThreshold: number;
  source: string;
}

export function ClusterHeader({
  clusterId,
  clusterSize,
  representative,
  earliestPostedDate,
  latestPostedDate,
  embeddingModel,
  similarityThreshold,
  source,
}: ClusterHeaderProps) {
  const shortId = clusterId.slice(0, 12);
  const repDate = formatDate(representative.posted_date);
  const dayCount = daysBetweenInclusive(earliestPostedDate, latestPostedDate);
  const dateRange = formatDateRange(earliestPostedDate, latestPostedDate);

  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-20">
        <p
          className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-6"
          title={`Full cluster_id: ${clusterId}`}
        >
          Cluster{" "}
          <span className="font-mono normal-case tracking-normal text-[12px]">
            {shortId}…
          </span>{" "}
          · {source}
        </p>

        <h1 className="font-display text-5xl md:text-7xl leading-[1.04] tracking-[-0.015em] text-foreground">
          Cluster of{" "}
          <span className="text-brand tabular-nums">
            {formatInt(clusterSize)}
          </span>{" "}
          {clusterSize === 1 ? "comment" : "comments"}
        </h1>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-6 max-w-3xl">
          <Meta label="Representative">
            {representative.submitter_name ? (
              <span>{representative.submitter_name}</span>
            ) : (
              <span className="italic">(unsigned)</span>
            )}
            {repDate ? (
              <span className="text-muted-foreground"> · {repDate}</span>
            ) : null}
          </Meta>

          <Meta label="Date range">
            <span className="tabular-nums">{dateRange}</span>
            {dayCount && dayCount > 1 ? (
              <span className="text-muted-foreground tabular-nums">
                {" "}
                · {dayCount} days
              </span>
            ) : null}
          </Meta>

          <Meta label="Embedding model" mono>
            {embeddingModel}
          </Meta>

          <Meta label="Similarity threshold">
            <span className="tabular-nums">
              {similarityThreshold.toFixed(2)}
            </span>
          </Meta>
        </div>
      </div>
    </section>
  );
}

function Meta({
  label,
  children,
  mono,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-1.5">
        {label}
      </p>
      <p
        className={cn(
          "text-sm md:text-base text-foreground",
          mono && "font-mono text-sm",
        )}
      >
        {children}
      </p>
    </div>
  );
}
