"use client";

import Link from "next/link";
import { useState } from "react";

interface QueueAnalysisCardProps {
  query: string;
  topicSlug?: string;
  title?: string;
  description?: string;
}

interface QueueResult {
  request_id: string;
  docket_id: string;
  docket_title: string;
  status: string;
  estimated_minutes: number;
  needs_docket_match?: boolean;
}

export function QueueAnalysisCard({
  query,
  topicSlug,
  title = `Analyze "${query}"?`,
  description = "Astroturf will look for the strongest matching federal rulemaking docket, queue a Databricks analysis run, and track the request in your header.",
}: QueueAnalysisCardProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueueResult | null>(null);
  const [error, setError] = useState<"no_docket_match" | "server_error" | null>(null);

  async function queueAnalysis() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/queue-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, topic_slug: topicSlug }),
      });
      if (res.status === 404) {
        setError("no_docket_match");
        return;
      }
      if (!res.ok) {
        setError("server_error");
        return;
      }
      setResult((await res.json()) as QueueResult);
    } catch {
      setError("server_error");
    } finally {
      setLoading(false);
    }
  }

  if (result) {
    return (
      <div className="bg-card border border-brand/30 rounded-sm p-6 md:p-8 space-y-3 text-left">
        <h2 className="font-display text-lg font-semibold text-foreground">
          Analysis queued
        </h2>
        {result.needs_docket_match ? (
          <p className="text-sm text-muted-foreground leading-relaxed">
            We queued a docket search for{" "}
            <span className="text-foreground font-medium">{query}</span>. Track
            it in the requests badge while it gets mapped to a federal docket.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground leading-relaxed">
            We&apos;re analyzing{" "}
            <span className="text-foreground font-medium">{result.docket_title}</span>{" "}
            ({result.docket_id}). Track progress in the requests badge in the header.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="bg-card border border-rule rounded-sm p-6 md:p-8 space-y-4 text-left">
      <h2 className="font-display text-xl font-semibold text-foreground">{title}</h2>
      <p className="text-sm text-muted-foreground leading-relaxed max-w-[52ch]">
        {description}
      </p>
      <div className="flex flex-wrap gap-3 pt-2">
        <button
          type="button"
          onClick={queueAnalysis}
          disabled={loading}
          className="bg-brand text-white font-medium text-sm px-6 py-3 rounded-sm hover:bg-brand/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Searching dockets..." : "Yes, queue analysis"}
        </button>
        <Link
          href="/advanced"
          className="border border-rule text-muted-foreground font-medium text-sm px-6 py-3 rounded-sm hover:border-foreground/30 hover:text-foreground transition-colors"
        >
          Manual entry
        </Link>
      </div>
      {error === "no_docket_match" && (
        <p className="text-sm text-muted-foreground">
          We could not reach the docket resolver. Try again in a moment.
        </p>
      )}
      {error === "server_error" && (
        <p className="text-sm text-red-600">Something went wrong. Please try again.</p>
      )}
    </div>
  );
}
