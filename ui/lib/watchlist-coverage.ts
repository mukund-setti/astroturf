import { AGENCIES, DOCKETS, TOPICS } from "./fallback-data";
import type { WatchItem } from "./watchlist-store";

export type WatchCoverageStatus =
  | "analyzed"
  | "baseline_only"
  | "monitoring"
  | "none";

export interface WatchCoverage {
  coverageStatus: WatchCoverageStatus;
  coverageLabel: string;
}

export type HydratedWatchItem = WatchItem & WatchCoverage;

export function resolveWatchCoverage(item: Pick<WatchItem, "kind" | "value">): WatchCoverage {
  const normalizedValue = item.value.trim().toLowerCase();

  if (item.kind === "topic") {
    const topic = TOPICS.find((t) => t.id.toLowerCase() === normalizedValue);
    return coverageFromStatus(topic?.status);
  }

  if (item.kind === "agency") {
    const agency = AGENCIES.find((a) => a.id.toLowerCase() === normalizedValue);
    return coverageFromStatus(agency?.status);
  }

  if (item.kind === "docket") {
    const docket = DOCKETS.find((d) => d.id.toLowerCase() === normalizedValue);
    return coverageFromStatus(docket?.status);
  }

  const match = DOCKETS.find(
    (docket) =>
      docket.title.toLowerCase().includes(normalizedValue) ||
      docket.description.toLowerCase().includes(normalizedValue),
  );

  if (!match) {
    return {
      coverageStatus: "monitoring",
      coverageLabel: "Active Discovery Search",
    };
  }

  if (match.status === "analyzed") {
    return {
      coverageStatus: "analyzed",
      coverageLabel: `Matched: ${match.id} (Analyzed)`,
    };
  }

  if (match.status === "baseline_only") {
    return {
      coverageStatus: "baseline_only",
      coverageLabel: `Matched: ${match.id} (Baseline Only)`,
    };
  }

  return {
    coverageStatus: "monitoring",
    coverageLabel: `Matched: ${match.id} (Monitoring Active)`,
  };
}

export function hydrateWatchItem(item: WatchItem): HydratedWatchItem {
  return {
    ...item,
    ...resolveWatchCoverage(item),
  };
}

function coverageFromStatus(status: string | undefined): WatchCoverage {
  if (status === "analyzed") {
    return {
      coverageStatus: "analyzed",
      coverageLabel: "Analyzed",
    };
  }

  if (status === "baseline_only") {
    return {
      coverageStatus: "baseline_only",
      coverageLabel: "Baseline Only",
    };
  }

  if (status) {
    return {
      coverageStatus: "monitoring",
      coverageLabel: "Monitoring Active",
    };
  }

  return {
    coverageStatus: "none",
    coverageLabel: "No coverage",
  };
}
