"use client";

import { useMemo, useState } from "react";
import { formatDate, formatInt, truncate } from "@/lib/format";
import type { ClusterRow } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MemberListProps {
  members: ClusterRow[];
}

type Order = "asc" | "desc";

const MEMBER_PREVIEW_CHARS = 220;

export function MemberList({ members }: MemberListProps) {
  const [order, setOrder] = useState<Order>("asc");

  const sorted = useMemo(() => {
    const arr = [...members];
    arr.sort((a, b) => {
      const aT = a.posted_date ? new Date(a.posted_date).getTime() : 0;
      const bT = b.posted_date ? new Date(b.posted_date).getTime() : 0;
      if (aT === bT) return a.comment_id.localeCompare(b.comment_id);
      return order === "asc" ? aT - bT : bT - aT;
    });
    return arr;
  }, [members, order]);

  if (members.length === 0) {
    return (
      <div>
        <h2 className="font-display text-2xl md:text-3xl tracking-tight text-foreground mb-4">
          No other comments in this cluster
        </h2>
        <p className="text-sm text-muted-foreground">
          The representative is the only member of this cluster.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-end justify-between gap-4 flex-wrap mb-4 md:mb-6">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-2">
            {formatInt(members.length)} other{" "}
            {members.length === 1 ? "comment" : "comments"} in this cluster
          </p>
          <h2 className="font-display text-2xl md:text-3xl tracking-tight text-foreground">
            Members
          </h2>
        </div>

        <div
          role="group"
          aria-label="Sort order"
          className="flex items-center gap-2 text-[11px] uppercase tracking-[0.14em]"
        >
          <span className="text-muted-foreground">Sort</span>
          <SortButton
            active={order === "asc"}
            onClick={() => setOrder("asc")}
            label="Oldest first"
          />
          <SortButton
            active={order === "desc"}
            onClick={() => setOrder("desc")}
            label="Newest first"
          />
        </div>
      </div>

      <ul className="border-t border-rule">
        {sorted.map((m) => (
          <li
            key={m.comment_id}
            className="border-b border-rule py-6 grid grid-cols-1 md:grid-cols-12 gap-x-6 gap-y-3"
          >
            <div className="md:col-span-2 flex flex-col gap-1 text-xs">
              <span className="text-foreground tabular-nums">
                {formatDate(m.posted_date) ?? "—"}
              </span>
              <span className="text-muted-foreground">
                {m.submitter_name ? (
                  <span className="truncate">{m.submitter_name}</span>
                ) : (
                  <span className="italic">(unsigned)</span>
                )}
              </span>
            </div>
            <div className="md:col-span-10 flex flex-col gap-2">
              <p className="text-sm md:text-base text-foreground leading-relaxed">
                {m.text_preview ? (
                  <>&ldquo;{truncate(m.text_preview, MEMBER_PREVIEW_CHARS)}&rdquo;</>
                ) : (
                  <span className="text-muted-foreground italic">
                    (no preview text)
                  </span>
                )}
              </p>
              <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-mono">
                {m.comment_id}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SortButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "px-3 py-1.5 border rounded-sm transition-colors",
        active
          ? "bg-foreground text-background border-foreground"
          : "bg-card text-foreground border-rule hover:border-foreground/40",
      )}
    >
      {label}
    </button>
  );
}
