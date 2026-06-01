"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";

type SuggestionType = "topic" | "finding" | "docket" | "analysis";

interface Suggestion {
  type: SuggestionType;
  label: string;
  sublabel?: string;
  href: string;
  cluster_size?: number;
}

interface TopicBubblesProps {
  /**
   * Initial bubbles rendered server-side. The component re-fetches as the
   * user types, but seeding avoids a blank flash on first paint.
   */
  initial: Suggestion[];
}

const DEBOUNCE_MS = 150;

export function TopicBubbles({ initial }: TopicBubblesProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Suggestion[]>(initial);
  const inflight = useRef<AbortController | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (inflight.current) inflight.current.abort();
    const ctl = new AbortController();
    inflight.current = ctl;
    try {
      const res = await fetch(
        `/api/search/suggest?q=${encodeURIComponent(q)}`,
        { signal: ctl.signal },
      );
      if (!res.ok) return;
      const data = (await res.json()) as { results: Suggestion[] };
      setResults(Array.isArray(data.results) ? data.results : []);
    } catch (err) {
      if ((err as { name?: string }).name === "AbortError") return;
      // Silent: bubbles just stop updating if the network is down.
    }
  }, []);

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      void fetchSuggestions(query);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [query, fetchSuggestions]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    router.push(`/explore?q=${encodeURIComponent(trimmed)}`);
  }

  // Bubbles use a stable key so React can animate enter/exit instead of
  // remounting the whole row on every keystroke. The key is type+href so
  // re-using the same destination (e.g. the "the economy" topic) keeps
  // the same DOM node across renders and CSS transitions just apply.
  const visible = useMemo(() => results.slice(0, 12), [results]);

  return (
    <div className="space-y-5">
      <form onSubmit={handleSubmit} className="max-w-lg">
        <div className="flex gap-3">
          <input
            id="home-search-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What policy area are you curious about?"
            className="flex-1 bg-card border border-rule rounded-sm px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent transition-shadow"
            autoComplete="off"
            autoFocus
          />
          <button
            type="submit"
            className="bg-brand text-white font-medium text-sm px-6 py-3 rounded-sm hover:bg-brand/90 transition-colors shrink-0 disabled:opacity-50"
            disabled={!query.trim()}
          >
            Explore
          </button>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground/80">
          Click a bubble below to jump straight there, or press Enter to run a
          full search.
        </p>
      </form>

      <div className="flex flex-wrap gap-2 min-h-[5.5rem]">
        {visible.map((s) => (
          <Bubble
            key={`${s.type}:${s.href}`}
            suggestion={s}
            onClick={() => router.push(s.href)}
          />
        ))}
        {visible.length === 0 && (
          <p className="text-xs text-muted-foreground/70 italic py-2">
            No matches yet - press Enter to search.
          </p>
        )}
      </div>
    </div>
  );
}

interface BubbleProps {
  suggestion: Suggestion;
  onClick: () => void;
}

function Bubble({ suggestion, onClick }: BubbleProps) {
  const { type, label, sublabel, cluster_size } = suggestion;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // Shared layout
        "inline-flex items-center gap-2 rounded-sm px-3.5 py-2 text-sm font-medium",
        "transition-all duration-150 ease-out",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
        "max-w-[28rem]",
        // Per-type styling
        type === "topic" && [
          "border border-brand/70 text-brand bg-transparent",
          "hover:bg-brand/10",
        ],
        type === "finding" && [
          "bg-brand text-white border border-brand",
          "hover:bg-brand/90",
        ],
        type === "docket" && [
          "border border-muted-foreground/30 text-foreground/80 bg-transparent",
          "hover:border-foreground/50 hover:text-foreground",
        ],
        type === "analysis" && [
          "border border-brand/40 text-foreground bg-card",
          "hover:border-brand hover:text-brand",
        ],
      )}
      title={sublabel ?? label}
    >
      <span className="truncate">{label}</span>
      {type === "finding" && cluster_size !== undefined && (
        <span
          className="text-[10px] uppercase tracking-wider tabular-nums bg-white/20 px-1.5 py-0.5 rounded-sm shrink-0"
          aria-label={`${cluster_size} similar comments`}
        >
          {formatInt(cluster_size)}
        </span>
      )}
      {type === "docket" && sublabel && (
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground shrink-0 font-mono">
          {sublabel}
        </span>
      )}
      {type === "analysis" && sublabel && (
        <span className="text-[10px] uppercase tracking-wider text-brand/80 shrink-0">
          {sublabel}
        </span>
      )}
    </button>
  );
}
