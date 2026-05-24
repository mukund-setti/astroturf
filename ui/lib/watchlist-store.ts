import fs from "fs";
import path from "path";
import { query, isOfflineMode, getCatalog } from "./databricks";

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

const DATA_DIR = path.resolve(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "watchlist.json");

function ensureStoreExists(): void {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(STORE_PATH)) {
      fs.writeFileSync(STORE_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize watchlist JSON directory:", err);
  }
}

export async function listWatchItems(): Promise<WatchItem[]> {
  const offline = isOfflineMode();

  if (!offline) {
    // Production Mode: Query Databricks SQL Warehouse
    try {
      const catalog = getCatalog();
      const sql = `SELECT * FROM ${catalog}.discovery.watchlist ORDER BY created_at DESC`;
      const rows = await query<Record<string, unknown>>(sql);
      return rows.map((r) => ({
        watch_id: r.watch_id as string,
        kind: r.kind as WatchItem["kind"],
        value: r.value as string,
        label: r.label as string,
        status: (r.status as string || "active") as WatchItem["status"],
        created_at: r.created_at ? new Date(r.created_at as string).toISOString() : new Date().toISOString(),
        last_checked_at: r.last_checked_at ? new Date(r.last_checked_at as string).toISOString() : new Date().toISOString(),
        notes: (r.notes as string) || null,
      }));
    } catch (err) {
      console.warn("Failed to query watchlist from Databricks SQL. Falling back to local watchlist JSON.", err);
    }
  }

  // Local Dev Fallback: Read local JSON file
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

export async function addWatchItem(
  kind: "topic" | "agency" | "docket" | "keyword",
  value: string,
  label: string,
  notes: string | null = null
): Promise<WatchItem> {
  ensureStoreExists();
  const list = await listWatchItems();

  // Check if identical item already active
  const existing = list.find((item) => item.kind === kind && item.value.toLowerCase() === value.toLowerCase());
  if (existing) {
    if (existing.status === "inactive") {
      existing.status = "active";
      existing.last_checked_at = new Date().toISOString();
      fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
    }
    return existing;
  }

  const now = new Date().toISOString();
  const newItem: WatchItem = {
    watch_id: `watch_${Math.random().toString(36).substring(2, 11)}`,
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

export async function removeWatchItem(watchId: string): Promise<boolean> {
  ensureStoreExists();
  const list = await listWatchItems();
  const index = list.findIndex((item) => item.watch_id === watchId);
  if (index === -1) {
    return false;
  }

  // Soft delete or completely remove for MVP
  list.splice(index, 1);
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return true;
}

export async function markChecked(watchId: string): Promise<WatchItem | null> {
  ensureStoreExists();
  const list = await listWatchItems();
  const index = list.findIndex((item) => item.watch_id === watchId);
  if (index === -1) {
    return null;
  }

  list[index].last_checked_at = new Date().toISOString();
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return list[index];
}
