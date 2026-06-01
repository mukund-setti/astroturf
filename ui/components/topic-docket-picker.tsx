"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";

interface DocketLite {
  docket_id: string;
  title: string;
  agency_id: string;
  comment_count_estimate: number;
}

interface TopicDocketPickerProps {
  topicLabel: string;
  topicSlug: string;
  heading: string;
  description: string;
  dockets: DocketLite[];
}

interface QueueResult {
  request_id: string;
  docket_id: string;
  docket_title: string;
  status: string;
}

/**
 * Renders a list of cataloged-but-unanalyzed dockets for a topic page,
 * each with a "Queue this" button. On click we POST /api/queue-analysis
 * with the specific docket_id (skipping the LLM/catalog-search step that
 * the homepage CTA goes through) and surface the row's request_id so the
 * user knows it landed. The badge in the header picks it up via its
 * normal poll cycle.
 */
export function TopicDocketPicker({
  topicLabel,
  topicSlug,
  heading,
  description,
  dockets,
}: TopicDocketPickerProps) {
  const [queued, setQueued] = useState<Record<string, QueueResult | "pending" | "error">>({});

  async function queueDocket(d: DocketLite) {
    setQueued((q) => ({ ...q, [d.docket_id]: "pending" }));
    try {
      const res = await fetch("/api/queue-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docket_id: d.docket_id,
          query: `${topicLabel}: ${d.title}`,
          topic_slug: topicSlug,
        }),
      });
      if (!res.ok) {
        setQueued((q) => ({ ...q, [d.docket_id]: "error" }));
        return;
      }
      const data = (await res.json()) as QueueResult;
      setQueued((q) => ({ ...q, [d.docket_id]: data }));
    } catch {
      setQueued((q) => ({ ...q, [d.docket_id]: "error" }));
    }
  }

  return (
    <div className="bg-card border border-rule rounded-sm p-6 md:p-8 space-y-5">
      <div className="space-y-2">
        <h2 className="font-display text-xl font-semibold text-foreground">
          {heading}
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed max-w-[60ch]">
          {description}
        </p>
      </div>
      <ul className="divide-y divide-rule">
        {dockets.map((d) => {
          const state = queued[d.docket_id];
          const pending = state === "pending";
          const queuedOk = state && typeof state === "object";
          const error = state === "error";
          return (
            <li
              key={d.docket_id}
              className="py-4 flex flex-col sm:flex-row sm:items-center gap-3"
            >
              <div className="flex-1 min-w-0">
                <p className="font-medium text-foreground leading-snug">
                  {d.title}
                </p>
                <p className="mt-1 text-[11px] font-mono text-muted-foreground">
                  {d.docket_id}
                  <span aria-hidden className="mx-1.5 text-rule">
                    /
                  </span>
                  {d.agency_id}
                  {d.comment_count_estimate > 0 && (
                    <>
                      <span aria-hidden className="mx-1.5 text-rule">
                        /
                      </span>
                      <span className="tabular-nums">
                        ~{formatInt(d.comment_count_estimate)} comments
                      </span>
                    </>
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => queueDocket(d)}
                disabled={pending || Boolean(queuedOk)}
                className={cn(
                  "shrink-0 inline-flex items-center justify-center rounded-sm px-4 py-2 text-xs font-medium transition-colors min-w-[10rem]",
                  queuedOk
                    ? "bg-card border border-brand/40 text-brand cursor-default"
                    : "bg-brand text-white hover:bg-brand/90 disabled:opacity-50 disabled:cursor-not-allowed",
                )}
              >
                {pending
                  ? "Queuing..."
                  : queuedOk
                    ? "Queued"
                    : error
                      ? "Try again"
                      : "Queue analysis"}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="text-[11px] text-muted-foreground/80">
        Queued requests appear in the badge at the top of the page. The
        Databricks pipeline runs on a separate queue; status updates as it
        progresses.
      </p>
    </div>
  );
}
