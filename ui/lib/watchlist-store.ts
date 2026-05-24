import fs from "fs";
import path from "path";
import { query as pgQuery } from "./db";

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

const isProduction = process.env.ASTROTURF_DEPLOYMENT_MODE === "production";
const hasDatabaseUrl = Boolean(process.env.DATABASE_URL && process.env.DATABASE_URL.trim());

// Fail loudly in production if DATABASE_URL is missing
if (isProduction && !hasDatabaseUrl) {
  throw new Error("CRITICAL CONFIGURATION ERROR: Missing required environment variable 'DATABASE_URL' in production deployment mode. Production requires PostgreSQL state storage.");
}

const useDb = isProduction || hasDatabaseUrl;

const DATA_DIR = path.resolve(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "watchlist.json");

function ensureStoreExists(): void {
  if (isProduction) return;

  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(STORE_PATH)) {
      fs.writeFileSync(STORE_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize local watchlist JSON directory:", err);
  }
}

/**
 * List all watched topics, agencies, keywords, and dockets
 */
export async function listWatchItems(): Promise<WatchItem[]> {
  if (useDb) {
    try {
      const rows = await pgQuery<Record<string, unknown>>(
        "SELECT * FROM watchlist_items ORDER BY created_at DESC"
      );
      return rows.map(mapRowToWatchItem);
    } catch (err) {
      console.error("Failed to query watchlist_items from PostgreSQL:", err);
      if (isProduction) throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  try {
    if (!fs.existsSync(STORE_PATH)) {
      return [];
    }
    const raw = fs.readFileSync(STORE_PATH, "utf8");
    if (!raw.trim()) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed;
  } catch (err) {
    console.error("Failed to read watchlist JSON store:", err);
    return [];
  }
}

/**
 * Add a new item to the active watchlist (idempotent ON CONFLICT clause)
 */
export async function addWatchItem(
  kind: "topic" | "agency" | "docket" | "keyword",
  value: string,
  label: string,
  notes: string | null = null
): Promise<WatchItem> {
  const id = `watch_${Math.random().toString(36).substring(2, 11)}`;
  const now = new Date().toISOString();

  if (useDb) {
    try {
      const rows = await pgQuery(
        `INSERT INTO watchlist_items (watch_id, kind, value, label, status, notes, created_at, updated_at, last_checked_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
         ON CONFLICT (kind, value) DO UPDATE 
         SET status = 'active', last_checked_at = EXCLUDED.last_checked_at, updated_at = EXCLUDED.updated_at
         RETURNING *`,
        [id, kind, value, label, "active", notes, now, now, now]
      );
      return mapRowToWatchItem(rows[0]);
    } catch (err) {
      console.error("Failed to insert/upsert watch item in PostgreSQL:", err);
      throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  const list = await listWatchItems();

  const existing = list.find((item) => item.kind === kind && item.value.toLowerCase() === value.toLowerCase());
  if (existing) {
    if (existing.status === "inactive") {
      existing.status = "active";
      existing.last_checked_at = now;
      fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
    }
    return existing;
  }

  const newItem: WatchItem = {
    watch_id: id,
    kind,
    value,
    label,
    status: "active",
    created_at: now,
    last_checked_at: now,
    notes,
  };

  list.push(newItem);
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return newItem;
}

/**
 * Completely remove a watched item from the control plane
 */
export async function removeWatchItem(watchId: string): Promise<boolean> {
  if (useDb) {
    try {
      const rows = await pgQuery(
        "DELETE FROM watchlist_items WHERE watch_id = $1 RETURNING *",
        [watchId]
      );
      return rows.length > 0;
    } catch (err) {
      console.error(`Failed to remove watch item ${watchId} from PostgreSQL:`, err);
      throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  const list = await listWatchItems();
  const index = list.findIndex((item) => item.watch_id === watchId);
  if (index === -1) {
    return false;
  }

  list.splice(index, 1);
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return true;
}

/**
 * Mark a watched item checked
 */
export async function markChecked(watchId: string): Promise<WatchItem | null> {
  const now = new Date().toISOString();

  if (useDb) {
    try {
      const rows = await pgQuery(
        "UPDATE watchlist_items SET last_checked_at = $2, updated_at = $2 WHERE watch_id = $1 RETURNING *",
        [watchId, now]
      );
      if (rows.length === 0) return null;
      return mapRowToWatchItem(rows[0]);
    } catch (err) {
      console.error(`Failed to mark watch item ${watchId} checked in PostgreSQL:`, err);
      throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  const list = await listWatchItems();
  const index = list.findIndex((item) => item.watch_id === watchId);
  if (index === -1) {
    return null;
  }

  list[index].last_checked_at = now;
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return list[index];
}

/**
 * Helper to map PostgreSQL row to WatchItem TypeScript shape
 */
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
