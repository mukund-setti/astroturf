"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface RefreshButtonProps {
  requestId: string;
}

export function RefreshButton({ requestId }: RefreshButtonProps) {
  const router = useRouter();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRefresh() {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await fetch(`/api/analysis/${requestId}/refresh`, {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error("Failed to sync status with Databricks.");
      }
      // Force Next.js App Router to fetch latest server data and re-render the page
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync error occurred.");
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleRefresh}
        disabled={isRefreshing}
        className="inline-flex h-9 items-center justify-center rounded-sm bg-brand px-4 text-xs font-semibold uppercase tracking-wider text-white hover:bg-brand/90 transition-colors disabled:opacity-50 cursor-pointer"
      >
        {isRefreshing ? "Syncing..." : "Sync Databricks Run"}
      </button>
      {error && (
        <span className="block text-xs text-destructive">
          Error: {error}
        </span>
      )}
    </div>
  );
}
