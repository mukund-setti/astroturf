/**
 * Date / number / string formatters used across the UI.
 *
 * All dates are interpreted as UTC because the underlying data ships timestamps
 * normalized to UTC (per the export schema) and we want display values to be
 * deterministic regardless of where the server or browser is.
 */

export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const s = formatDate(start);
  const e = formatDate(end);
  if (!s && !e) return " - ";
  if (s && e && s === e) return s;
  if (s && e) return `${s} - ${e}`;
  return (s ?? e) as string;
}

/**
 * Inclusive day count between two ISO dates (UTC). Returns null when either
 * endpoint is missing or unparseable. A span of one day means start === end.
 */
export function daysBetweenInclusive(
  start: string | null | undefined,
  end: string | null | undefined,
): number | null {
  if (!start || !end) return null;
  const s = new Date(start);
  const e = new Date(end);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return null;
  const diff = Math.abs(e.getTime() - s.getTime());
  return Math.floor(diff / 86_400_000) + 1;
}

export function truncate(value: string | null | undefined, n: number): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (trimmed.length <= n) return trimmed;
  return trimmed.slice(0, Math.max(0, n - 1)).trimEnd() + "...";
}

export function formatInt(value: number): string {
  return Number(value).toLocaleString("en-US");
}
