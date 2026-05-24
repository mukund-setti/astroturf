"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface HydratedWatchItem {
  watch_id: string;
  kind: "topic" | "agency" | "docket" | "keyword";
  value: string;
  label: string;
  status: "active" | "inactive";
  created_at: string;
  last_checked_at: string;
  notes: string | null;
  coverageStatus: "analyzed" | "baseline_only" | "monitoring" | "none";
  coverageLabel: string;
}

interface WatchlistClientProps {
  initialItems: HydratedWatchItem[];
}

export function WatchlistClient({ initialItems }: WatchlistClientProps) {
  const [items, setItems] = useState<HydratedWatchItem[]>(initialItems);
  const [kind, setKind] = useState<"topic" | "agency" | "docket" | "keyword">("keyword");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim() || !label.trim()) {
      setError("Please fill in both the value and display name.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, value: value.trim(), label: label.trim(), notes: notes.trim() || null }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Failed to add watch item.");
      }

      const newItem = await res.json();
      
      // Hydrate newly added item locally
      const hydratedNewItem: HydratedWatchItem = {
        ...newItem,
        coverageStatus: "monitoring",
        coverageLabel: "Monitoring Active",
      };

      setItems([hydratedNewItem, ...items]);
      setValue("");
      setLabel("");
      setNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemove = async (id: string) => {
    try {
      const res = await fetch(`/api/watchlist/${id}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Failed to remove watch item.");
      }

      setItems(items.filter((item) => item.watch_id !== id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to remove watch item.");
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] gap-10 items-start">
      <div className="space-y-6">
        <h2 className="font-display text-xl font-semibold text-foreground">Active Watches</h2>
        
        {items.length === 0 ? (
          <div className="border border-dashed border-rule rounded-sm p-12 text-center text-muted-foreground text-sm leading-relaxed">
            <p className="font-medium text-foreground mb-1">Your Watchlist is empty</p>
            <p>Add keywords, topics, or dockets on the right to start proactive monitoring.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((item) => (
              <Card key={item.watch_id} className="bg-card border border-rule rounded-sm shadow-none overflow-hidden hover:border-foreground/20 transition-colors">
                <CardContent className="p-5 flex items-start justify-between gap-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[9px] font-sans font-bold uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-0.5 rounded-sm">
                        {item.kind}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {item.value}
                      </span>
                      <span
                        className={cn(
                          "text-[9px] uppercase tracking-wider px-2 py-0.5 rounded-sm font-sans font-semibold",
                          item.coverageStatus === "analyzed"
                            ? "bg-brand/10 text-brand"
                            : item.coverageStatus === "baseline_only"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-blue-100 text-blue-800"
                        )}
                      >
                        {item.coverageLabel}
                      </span>
                    </div>

                    <h3 className="font-display text-base font-semibold text-foreground leading-tight">
                      {item.label}
                    </h3>
                    
                    {item.notes && (
                      <p className="text-xs text-muted-foreground max-w-[60ch] leading-relaxed">
                        {item.notes}
                      </p>
                    )}

                    <div className="text-[10px] text-muted-foreground flex gap-4">
                      <span>Monitored since: {new Date(item.created_at).toLocaleDateString()}</span>
                      <span>Last checked: {new Date(item.last_checked_at).toLocaleTimeString()}</span>
                    </div>
                  </div>

                  <button
                    onClick={() => handleRemove(item.watch_id)}
                    className="text-xs text-muted-foreground hover:text-red-500 font-semibold uppercase tracking-wider bg-transparent p-1 transition-colors"
                  >
                    Remove
                  </button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Card className="bg-card border border-rule rounded-sm shadow-none p-6">
        <h2 className="font-display text-lg font-semibold text-foreground mb-4">Add Monitor Rule</h2>
        
        <form onSubmit={handleAdd} className="space-y-4">
          {error && (
            <div className="p-3 bg-red-100 text-red-800 border border-red-200 text-xs rounded-sm">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-[10px] font-sans font-bold uppercase tracking-wider text-muted-foreground">
              Monitor Type
            </label>
            <div className="grid grid-cols-4 gap-2">
              {(["keyword", "topic", "agency", "docket"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setKind(t);
                    setValue("");
                  }}
                  className={cn(
                    "text-[10px] font-sans uppercase tracking-wider font-semibold py-1.5 border rounded-sm text-center transition-all",
                    kind === t
                      ? "bg-brand text-primary-foreground border-brand"
                      : "bg-background text-foreground/80 border-rule hover:bg-secondary"
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="watch-value" className="text-[10px] font-sans font-bold uppercase tracking-wider text-muted-foreground">
              {kind === "keyword"
                ? "Search Keyword (e.g. Non-compete)"
                : kind === "topic"
                ? "Topic Domain Identifier (e.g. telecom)"
                : kind === "agency"
                ? "Agency Acronym (e.g. FTC)"
                : "Docket Reference Number (e.g. 17-108)"}
            </label>
            <input
              id="watch-value"
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={
                kind === "keyword"
                  ? "e.g. Artificial Intelligence"
                  : kind === "topic"
                  ? "e.g. ai_regulation"
                  : kind === "agency"
                  ? "e.g. SEC"
                  : "e.g. CFPB-2016-0025"
              }
              className="w-full bg-background border border-rule rounded-sm px-3 py-2 text-sm text-foreground focus:outline-none focus:border-foreground/30 font-mono"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="watch-label" className="text-[10px] font-sans font-bold uppercase tracking-wider text-muted-foreground">
              Watch Name / Label
            </label>
            <input
              id="watch-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Robocalls Oversight campaign"
              className="w-full bg-background border border-rule rounded-sm px-3 py-2 text-sm text-foreground focus:outline-none focus:border-foreground/30"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="watch-notes" className="text-[10px] font-sans font-bold uppercase tracking-wider text-muted-foreground">
              Oversight Notes (Optional)
            </label>
            <textarea
              id="watch-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Provide context for this monitor rule..."
              rows={3}
              className="w-full bg-background border border-rule rounded-sm px-3 py-2 text-sm text-foreground focus:outline-none focus:border-foreground/30 resize-none"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full h-10 inline-flex items-center justify-center rounded-sm bg-brand text-xs font-semibold uppercase tracking-wider text-primary-foreground hover:bg-brand/90 disabled:opacity-50 disabled:pointer-events-none transition-colors"
          >
            {isSubmitting ? "Creating..." : "Start Monitoring"}
          </button>
        </form>
      </Card>
    </div>
  );
}
