import { query as pgQuery, isConnectionError, sanitizeDatabaseError } from "./db";

export interface WatchItem {
  watch_id: string;
  kind: "topic" | "agency" | "docket" | "keyword";
  value: string;
  label: string;
  status: "active" | "inactive";
  created_at: string;
  last_checked_at: string;
  notes: string | null;
}

// Supabase Postgres is the only store. No more local JSON fallback.
const databaseUrl = (process.env.DATABASE_URL ?? "").trim();
if (!databaseUrl) {
  throw new Error(
    "CRITICAL CONFIGURATION ERROR: DATABASE_URL is required. The UI control plane talks to Supabase Postgres exclusively; there is no local JSON fallback."
  );
}

/**
 * List all watched topics, agencies, keywords, and dockets.
 */
export async function listWatchItems(): Promise<WatchItem[]> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM watchlist_items ORDER BY created_at DESC"
    );
    return rows.map(mapRowToWatchItem);
  } catch (err) {
    console.error("Failed to query watchlist_items from PostgreSQL:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return [];
    throw err;
  }
}

/**
 * Add a new item to the active watchlist (idempotent ON CONFLICT clause).
 */
export async function addWatchItem(
  kind: "topic" | "agency" | "docket" | "keyword",
  value: string,
  label: string,
  notes: string | null = null
): Promise<WatchItem> {
  const id = `watch_${Math.random().toString(36).substring(2, 11)}`;
  const now = new Date().toISOString();

  const rows = await pgQuery(
    `INSERT INTO watchlist_items (watch_id, kind, value, label, status, notes, created_at, updated_at, last_checked_at)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
     ON CONFLICT (kind, value) DO UPDATE
     SET status = 'active', last_checked_at = EXCLUDED.last_checked_at, updated_at = EXCLUDED.updated_at
     RETURNING *`,
    [id, kind, value, label, "active", notes, now, now, now]
  );
  return mapRowToWatchItem(rows[0]);
}

/**
 * Completely remove a watched item from the control plane.
 */
export async function removeWatchItem(watchId: string): Promise<boolean> {
  const rows = await pgQuery(
    "DELETE FROM watchlist_items WHERE watch_id = $1 RETURNING *",
    [watchId]
  );
  return rows.length > 0;
}

/**
 * Mark a watched item checked.
 */
export async function markChecked(watchId: string): Promise<WatchItem | null> {
  const now = new Date().toISOString();
  const rows = await pgQuery(
    "UPDATE watchlist_items SET last_checked_at = $2, updated_at = $2 WHERE watch_id = $1 RETURNING *",
    [watchId, now]
  );
  if (rows.length === 0) return null;
  return mapRowToWatchItem(rows[0]);
}

function mapRowToWatchItem(row: Record<string, unknown>): WatchItem {
  return {
    watch_id: row.watch_id as string,
    kind: row.kind as WatchItem["kind"],
    value: row.value as string,
    label: row.label as string,
    status: row.status as WatchItem["status"],
    created_at: new Date(row.created_at as string).toISOString(),
    last_checked_at: new Date(row.last_checked_at as string).toISOString(),
    notes: (row.notes as string) || null,
  };
}
