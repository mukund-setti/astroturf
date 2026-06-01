"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

// Poll interval for checking user's analysis request status.
const POLL_INTERVAL_MS = 30_000;

interface UserRequest {
  request_id: string;
  query_text: string | null;
  docket_id: string;
  title: string;
  status: string;
  created_at: string;
  finding_slug: string | null;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "Queued", color: "text-muted-foreground" },
  submitted: { label: "Submitted", color: "text-brand" },
  running: { label: "Running", color: "text-brand" },
  succeeded: { label: "Complete", color: "text-green-700" },
  failed: { label: "Failed", color: "text-red-600" },
  canceled: { label: "Canceled", color: "text-muted-foreground" },
};

export function UserRequestsBadge() {
  const [requests, setRequests] = useState<UserRequest[]>([]);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchRequests = useCallback(async () => {
    try {
      const res = await fetch("/api/user-requests");
      if (!res.ok) return;
      const data = await res.json();
      setRequests(Array.isArray(data.requests) ? data.requests : []);
    } catch {
      // Silent - badge just shows stale data.
    }
  }, []);

  // Poll on mount + interval. We use an IIFE inside the effect to avoid
  // the "setState in effect body" lint rule - the actual setState call
  // happens inside the async callback, not synchronously in the effect.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      if (cancelled) return;
      await fetchRequests();
    }
    // Fire first poll via microtask (not synchronous in the effect body).
    void Promise.resolve().then(poll);
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [fetchRequests]);

  // Close panel on outside click.
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const pending = requests.filter(
    (r) => r.status === "draft" || r.status === "submitted" || r.status === "running",
  );

  // Don't render anything if the user has never queued.
  if (requests.length === 0) return null;

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-xs font-medium transition-colors",
          "border border-rule hover:border-foreground/30",
          pending.length > 0
            ? "text-brand border-brand/40"
            : "text-muted-foreground",
        )}
        title={`${requests.length} analysis request${requests.length === 1 ? "" : "s"}`}
      >
        <span className="relative flex h-2 w-2">
          {pending.length > 0 && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75" />
          )}
          <span
            className={cn(
              "relative inline-flex h-2 w-2 rounded-full",
              pending.length > 0 ? "bg-brand" : "bg-muted-foreground/40",
            )}
          />
        </span>
        <span>
          {pending.length > 0 ? `${pending.length} running` : "requests"}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-80 max-h-96 overflow-y-auto bg-card border border-rule rounded-sm shadow-lg">
          <div className="px-4 py-3 border-b border-rule">
            <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              Your analysis requests
            </p>
          </div>
          {requests.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">
              No requests yet.
            </p>
          ) : (
            <ul className="divide-y divide-rule">
              {requests.map((r) => (
                <li key={r.request_id} className="px-4 py-3 space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-foreground leading-snug line-clamp-2">
                      {r.query_text || r.title}
                    </p>
                    <span
                      className={cn(
                        "text-[10px] uppercase tracking-wider font-medium shrink-0",
                        STATUS_LABELS[r.status]?.color ?? "text-muted-foreground",
                      )}
                    >
                      {STATUS_LABELS[r.status]?.label ?? r.status}
                    </span>
                  </div>
                  <p className="text-[11px] text-muted-foreground font-mono">
                    {r.docket_id}
                  </p>
                  {r.status === "succeeded" && r.finding_slug && (
                    <Link
                      href={`/finding/${r.finding_slug}`}
                      className="text-xs text-brand hover:underline underline-offset-4 font-medium"
                      onClick={() => setOpen(false)}
                    >
                      View finding {"->"}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
