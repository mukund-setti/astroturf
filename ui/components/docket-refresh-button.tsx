"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DocketRefreshButton() {
  const router = useRouter();
  const [isRefreshing, setIsRefreshing] = useState(false);

  function handleRefresh() {
    setIsRefreshing(true);
    router.refresh();
    setTimeout(() => setIsRefreshing(false), 800);
  }

  return (
    <button
      type="button"
      onClick={handleRefresh}
      disabled={isRefreshing}
      className="inline-flex h-9 items-center justify-center rounded-sm bg-brand text-white px-4 text-xs font-semibold uppercase tracking-wider hover:bg-brand/90 transition-colors disabled:opacity-50 cursor-pointer"
    >
      {isRefreshing ? "Checking..." : "Verify Table Sync"}
    </button>
  );
}
