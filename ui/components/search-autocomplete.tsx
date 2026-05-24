"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatInt } from "@/lib/format";
import type { ClusterSummary } from "@/lib/types";
import { AGENCIES, DOCKETS, TOPICS } from "@/lib/fallback-data";
import type { DiscoveredDocket } from "@/lib/docket-catalog";
import type { WatchItem } from "@/lib/watchlist-store";

interface SearchAutocompleteProps {
  clusters: ClusterSummary[];
  query: string;
  onQueryChange: (value: string) => void;
}

interface SearchMatch {
  type: "topic" | "agency" | "docket" | "campaign" | "analyze";
  id: string;
  title: string;
  subtitle: string;
  badge: string;
  url: string;
  preview?: string;
  snippetRanges?: { start: number; length: number }[];
}

export function SearchAutocomplete({
  clusters,
  query,
  onQueryChange,
}: SearchAutocompleteProps) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const [catalog, setCatalog] = useState<DiscoveredDocket[]>([]);
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);

  useEffect(() => {
    Promise.all([
      fetch("/api/discoveries").then((res) => res.json()).catch(() => []),
      fetch("/api/watchlist").then((res) => res.json()).catch(() => []),
    ]).then(([docketsData, watchData]) => {
      setCatalog(Array.isArray(docketsData) ? docketsData : []);
      setWatchlist(Array.isArray(watchData) ? watchData : []);
    });
  }, []);

  const qTrim = query.trim().toLowerCase();

  // Multi-entity search matcher
  const matches = useMemo(() => {
    if (!qTrim) return [];

    const list: SearchMatch[] = [];

    // 1. Match Topics (fallback-data)
    for (const t of TOPICS) {
      const topicTerms = [
        t.id.toLowerCase().replaceAll("_", " "),
        t.name.toLowerCase(),
        t.description.toLowerCase(),
      ].join(" ");
      if (topicTerms.includes(qTrim)) {
        if (t.visibility !== "primary" || t.id === "analyze") {
          list.push({
            type: "analyze",
            id: t.id,
            title: `Analyze a docket: ${t.name}`,
            subtitle: `${t.statusLabel}. Generate an ingestion config instead of opening an empty topic page.`,
            badge: "Analyze",
            url: `/analyze?topic=${t.id}&query=${encodeURIComponent(query.trim())}`,
          });
          continue;
        }

        list.push({
          type: "topic",
          id: t.id,
          title: t.name,
          subtitle: t.description,
          badge: "Sector",
          url: `/topics/${t.id}`,
        });
      }
    }

    // 2. Match Agencies (fallback-data)
    for (const a of AGENCIES) {
      if (
        a.id.toLowerCase().includes(qTrim) ||
        a.fullName.toLowerCase().includes(qTrim) ||
        a.policyDomains.some((d) => d.toLowerCase().includes(qTrim))
      ) {
        if (a.visibility !== "primary") {
          list.push({
            type: "analyze",
            id: a.id,
            title: `Analyze a ${a.id} docket`,
            subtitle: `${a.statusLabel}. Generate a docket registration before promoting an agency dashboard.`,
            badge: "Analyze",
            url: `/analyze?agency=${a.id}&query=${encodeURIComponent(query.trim())}`,
          });
          continue;
        }

        list.push({
          type: "agency",
          id: a.id,
          title: `${a.fullName} (${a.id})`,
          subtitle: `Monitors policy domains: ${a.policyDomains.join(", ")}`,
          badge: "Agency",
          url: `/agencies/${a.id}`,
        });
      }
    }

    // 3. Match Dockets (fallback-data)
    for (const d of DOCKETS) {
      if (
        d.id.toLowerCase().includes(qTrim) ||
        d.title.toLowerCase().includes(qTrim) ||
        d.ruleTitle.toLowerCase().includes(qTrim) ||
        d.ruleShortName.toLowerCase().includes(qTrim)
      ) {
        if (d.status === "ingestion_ready") {
          list.push({
            type: "analyze",
            id: d.id,
            title: `Configure docket ${d.id}`,
            subtitle: `${d.statusLabel}. ${d.validationSummary}`,
            badge: "Analyze",
            url: `/analyze?docket=${encodeURIComponent(d.id)}&agency=${d.agencyId}&topic=${d.topicId}`,
          });
          continue;
        }

        list.push({
          type: "docket",
          id: d.id,
          title: `Docket ${d.id} · ${d.title}`,
          subtitle: d.ruleShortName,
          badge: "Docket",
          url: `/dockets/${d.id}`,
        });
      }
    }

    // 4. Match Active Watchlist Monitored Items
    for (const w of watchlist) {
      if (w.status === "active" && (w.label.toLowerCase().includes(qTrim) || w.value.toLowerCase().includes(qTrim))) {
        list.push({
          type: "topic",
          id: w.watch_id,
          title: `Watchlist: ${w.label}`,
          subtitle: `Active monitoring for ${w.kind} "${w.value}".`,
          badge: "Watching",
          url: "/watchlist",
        });
      }
    }

    // 5. Match Discovered Dockets in Catalog
    for (const d of catalog) {
      const alreadyMatched = list.some((item) => item.id.toLowerCase() === d.docket_id.toLowerCase());
      if (!alreadyMatched && (d.docket_id.toLowerCase().includes(qTrim) || d.title.toLowerCase().includes(qTrim) || d.summary.toLowerCase().includes(qTrim))) {
        list.push({
          type: "docket",
          id: d.docket_id,
          title: `Discovered: ${d.docket_id} · ${d.title}`,
          subtitle: ` crawler priority: ${d.priority_score} | comments estimate: ${d.comment_count_estimate}`,
          badge: "Discovered",
          url: "/discoveries",
        });
      }
    }

    // 6. Match Campaigns / Template Phrases in clusters
    for (const c of clusters) {
      const text = c.rep_text_preview ?? "";
      const id = c.cluster_id ?? "";
      const submitter = c.rep_submitter_name ?? "";

      const matchInText = text.toLowerCase().indexOf(qTrim);
      const matchInId = id.toLowerCase().indexOf(qTrim);
      const matchInSubmitter = submitter.toLowerCase().indexOf(qTrim);

      if (matchInText >= 0 || matchInId >= 0 || matchInSubmitter >= 0) {
        let snippet = text;
        let ranges: { start: number; length: number }[] = [];

        if (matchInText >= 0) {
          const start = Math.max(0, matchInText - 20);
          const end = Math.min(text.length, matchInText + qTrim.length + 80);
          snippet = (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "");
          
          const relativeStart = start > 0 ? matchInText - start + 1 : matchInText;
          ranges = [{ start: relativeStart, length: qTrim.length }];
        } else {
          snippet = text.slice(0, 100) + "...";
        }

        list.push({
          type: "campaign",
          id: c.cluster_id,
          title: `${formatInt(c.cluster_size)} Comments Campaign`,
          subtitle: `Template phrase match (ID: ${c.cluster_id.substring(0, 8)})`,
          badge: "Campaign",
          url: `/campaign/${c.cluster_id}`,
          preview: snippet,
          snippetRanges: ranges,
        });
      }
    }

    if (list.length === 0) {
      list.push({
        type: "analyze",
        id: "new-docket",
        title: `Add "${query.trim()}" to Watchlist`,
        subtitle: "Generate a custom monitor or trigger a discovery run.",
        badge: "Watchlist",
        url: `/watchlist`,
      });
    }

    // Cap total matches to avoid overflow
    return list.slice(0, 7);
  }, [qTrim, query, clusters, catalog, watchlist]);

  // Handle outside clicks
  useEffect(() => {
    if (!isOpen) return;
    function onDocMouseDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [isOpen]);

  const selectItem = useCallback(
    (item: SearchMatch) => {
      router.push(item.url);
      setIsOpen(false);
      onQueryChange("");
    },
    [router, onQueryChange]
  );

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setIsOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (!isOpen) {
      if (e.key === "ArrowDown" && matches.length > 0) {
        setIsOpen(true);
        setActiveIndex(0);
        e.preventDefault();
      }
      return;
    }
    if (e.key === "ArrowDown") {
      if (matches.length === 0) return;
      setActiveIndex((i) => (i + 1) % matches.length);
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      if (matches.length === 0) return;
      setActiveIndex((i) => (i - 1 + matches.length) % matches.length);
      e.preventDefault();
    } else if (e.key === "Enter") {
      if (matches.length === 0) return;
      const target = activeIndex >= 0 ? matches[activeIndex] : matches[0];
      selectItem(target);
      e.preventDefault();
    }
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full max-w-xs sm:max-w-sm md:max-w-md"
    >
      <Search
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground z-10"
      />
      <input
        ref={inputRef}
        type="search"
        placeholder="Search topics, agencies, dockets, or campaigns..."
        value={query}
        onChange={(e) => {
          const nextValue = e.target.value;
          onQueryChange(nextValue);
          setIsOpen(nextValue.trim().length > 0);
          setActiveIndex(-1);
        }}
        onFocus={() => {
          if (qTrim) setIsOpen(true);
        }}
        onKeyDown={handleKeyDown}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={isOpen}
        aria-controls="global-search-listbox"
        aria-activedescendant={
          activeIndex >= 0 ? `global-search-option-${activeIndex}` : undefined
        }
        aria-label="Global search topics, agencies, dockets, or campaigns"
        className={cn(
          "w-full h-9 pl-9 pr-3 rounded-sm bg-card border border-rule text-sm text-foreground",
          "placeholder:text-muted-foreground outline-none transition-colors",
          "focus:border-brand focus:ring-2 focus:ring-brand/15"
        )}
      />

      {isOpen ? (
        <div
          id="global-search-listbox"
          role="listbox"
          className="absolute left-0 right-0 mt-1 z-50 bg-card border border-rule rounded-sm overflow-hidden shadow-[0_6px_24px_-8px_rgba(26,23,20,0.25)]"
        >
          {matches.length === 0 ? (
            <div className="p-4 space-y-2">
              <p className="text-sm text-muted-foreground">
                No matching results found for &ldquo;{query}&rdquo;.
              </p>
              <p className="text-[11px] leading-relaxed text-muted-foreground/80 border-t border-rule pt-2">
                <strong>Ingestion queue:</strong> Astroturf is a multi-docket semantic platform. If you would like to run 
                influence tracking on this docket, submit it in our Databricks server workflow panel.
              </p>
            </div>
          ) : (
            <ul>
              {matches.map((m, i) => (
                <li
                  key={`${m.type}-${m.id}-${i}`}
                  id={`global-search-option-${i}`}
                  role="option"
                  aria-selected={activeIndex === i}
                  onMouseDown={(e) => {
                    e.preventDefault(); // prevent blur
                    selectItem(m);
                  }}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={cn(
                    "px-4 py-3 cursor-pointer border-b border-rule last:border-b-0 transition-colors",
                    activeIndex === i ? "bg-brand-soft" : "hover:bg-muted"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "text-[9px] uppercase tracking-wider px-2 py-0.5 rounded-[2px] font-sans font-semibold shrink-0 select-none mt-0.5",
                        m.type === "topic" && "bg-emerald-100 text-emerald-800",
                        m.type === "agency" && "bg-blue-100 text-blue-800",
                        m.type === "docket" && "bg-purple-100 text-purple-800",
                        m.type === "campaign" && "bg-brand/10 text-brand",
                        m.type === "analyze" && "bg-blue-100 text-blue-800"
                      )}
                    >
                      {m.badge}
                    </span>

                    <div className="min-w-0 flex-1">
                      <h4 className="text-sm font-semibold text-foreground leading-snug truncate">
                        {m.title}
                      </h4>
                      
                      {m.preview ? (
                        <p className="mt-1 text-xs text-muted-foreground italic leading-relaxed line-clamp-2">
                          &ldquo;{m.preview}&rdquo;
                        </p>
                      ) : (
                        <p className="mt-0.5 text-xs text-muted-foreground truncate">
                          {m.subtitle}
                        </p>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
