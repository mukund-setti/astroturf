import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  formatDateRange,
  formatInt,
  truncate,
} from "@/lib/format";
import type { ClusterSummary } from "@/lib/types";

interface CampaignCardProps {
  cluster: ClusterSummary;
  variant: "featured" | "default";
}

const FEATURED_PREVIEW_CHARS = 280;
const DEFAULT_PREVIEW_CHARS = 140;

export function CampaignCard({ cluster, variant }: CampaignCardProps) {
  const isFeatured = variant === "featured";

  const preview = truncate(
    cluster.rep_text_preview,
    isFeatured ? FEATURED_PREVIEW_CHARS : DEFAULT_PREVIEW_CHARS,
  );

  const dateRange = formatDateRange(
    cluster.earliest_posted_date,
    cluster.latest_posted_date,
  );

  return (
    <Link
      href={`/campaign/${cluster.cluster_id}`}
      className="block group focus:outline-none"
    >
      <Card
        className={cn(
          "h-full bg-card border border-rule rounded-sm shadow-none gap-0 py-0 transition-colors",
          "group-hover:border-foreground/30 group-focus-visible:ring-2 group-focus-visible:ring-brand",
          isFeatured && "border-l-[3px] border-l-brand",
        )}
      >
        <CardContent
          className={cn(
            "h-full flex flex-col",
            isFeatured ? "p-8 md:p-10 gap-6" : "p-5 gap-3",
          )}
        >
          <div className="flex items-baseline gap-2">
            <span
              className={cn(
                "font-display tabular-nums leading-none",
                isFeatured
                  ? "text-7xl md:text-8xl text-brand"
                  : "text-5xl md:text-6xl text-foreground",
              )}
            >
              {formatInt(cluster.cluster_size)}
            </span>
            <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              {cluster.cluster_size === 1 ? "comment" : "comments"}
            </span>
          </div>

          <p
            className={cn(
              "text-foreground leading-relaxed",
              isFeatured
                ? "text-base md:text-lg max-w-[62ch]"
                : "text-sm leading-snug",
            )}
          >
            &ldquo;{preview}&rdquo;
          </p>

          <div
            className={cn(
              "mt-auto text-xs text-muted-foreground pt-2",
              isFeatured && "pt-4",
            )}
          >
            <span className="tabular-nums">{dateRange}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
