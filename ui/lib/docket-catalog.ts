import fs from "fs";
import path from "path";
import { query as pgQuery } from "./db";
import { query as queryDb, isOfflineMode, getCatalog } from "./databricks";

export interface DiscoveredDocket {
  docket_id: string;
  source: "regulations_gov" | "ecfs";
  agency_id: string;
  topic_id: string;
  title: string;
  summary: string;
  status: "discovered" | "monitoring" | "queued" | "analyzing" | "analyzed" | "stale" | "failed";
  comment_count_estimate: number;
  last_comment_date: string | null;
  last_ingested_at: string | null;
  last_analyzed_at: string | null;
  freshness_label: string;
  priority_score: number;
  user_requested_count: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

const isProduction = process.env.ASTROTURF_DEPLOYMENT_MODE === "production";
const hasDatabaseUrl = Boolean(process.env.DATABASE_URL && process.env.DATABASE_URL.trim());

// Fail loudly in production if DATABASE_URL is missing
if (isProduction && !hasDatabaseUrl) {
  throw new Error("CRITICAL CONFIGURATION ERROR: Missing required environment variable 'DATABASE_URL' in production deployment mode. Production requires PostgreSQL state storage.");
}

const useDb = isProduction || hasDatabaseUrl;

const LOCAL_CATALOG_PATH = path.resolve(process.cwd(), "..", "data", "discovery", "docket_catalog.json");

function ensureCatalogDirectory(): void {
  if (isProduction) return;

  try {
    const dir = path.dirname(LOCAL_CATALOG_PATH);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    if (!fs.existsSync(LOCAL_CATALOG_PATH)) {
      fs.writeFileSync(LOCAL_CATALOG_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize discovery catalog directory:", err);
  }
}

/**
 * List all discovered and monitored rulemaking dockets
 */
export async function listDiscoveredDockets(): Promise<DiscoveredDocket[]> {
  if (useDb) {
    try {
      const rows = await pgQuery<Record<string, unknown>>(
        "SELECT * FROM docket_catalog ORDER BY priority_score DESC"
      );
      if (rows.length > 0) {
        return rows.map(mapRowToDocket);
      }

      // If Postgres cache is empty, we check if Databricks credentials exist to sync
      const offline = isOfflineMode();
      if (!offline) {
        try {
          const catalog = getCatalog();
          const sql = `SELECT * FROM ${catalog}.discovery.docket_catalog ORDER BY priority_score DESC`;
          const dbRows = await queryDb<Record<string, unknown>>(sql);
          const mapped = dbRows.map(mapDbRowToDocket);

          // Seed/cache the discovered dockets into the PostgreSQL database
          for (const docket of mapped) {
            await registerDiscoveredDocket(docket);
          }
          return mapped;
        } catch (dbErr) {
          console.warn("Failed to read docket_catalog from Databricks SQL:", dbErr);
        }
      }

      // Production mode does not load local JSON quickseeds
      return [];
    } catch (err) {
      console.error("Failed to query docket catalog from PostgreSQL:", err);
      if (isProduction) throw err;
    }
  }

  // Local Dev Fallback: Read local JSON file
  ensureCatalogDirectory();
  try {
    if (!fs.existsSync(LOCAL_CATALOG_PATH)) {
      return [];
    }
    const raw = fs.readFileSync(LOCAL_CATALOG_PATH, "utf8");
    if (!raw.trim()) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map((item: Record<string, unknown>) => ({
      ...item,
      tags: typeof item.tags === "string" ? (item.tags as string).split(",").map((s: string) => s.trim()) : (item.tags as string[]) || [],
    })) as DiscoveredDocket[];
  } catch (err) {
    console.error("Failed to read discovered docket catalog JSON store:", err);
    return [];
  }
}

/**
 * Get a specific discovered docket by ID
 */
export async function getDiscoveredDocket(docketId: string): Promise<DiscoveredDocket | null> {
  if (useDb) {
    try {
      const rows = await pgQuery<Record<string, unknown>>(
        "SELECT * FROM docket_catalog WHERE LOWER(docket_id) = LOWER($1)",
        [docketId]
      );
      if (rows.length === 0) return null;
      return mapRowToDocket(rows[0]);
    } catch (err) {
      console.error(`Failed to get docket ${docketId} from PostgreSQL:`, err);
      if (isProduction) throw err;
    }
  }

  const list = await listDiscoveredDockets();
  return list.find((d) => d.docket_id.toLowerCase() === docketId.toLowerCase()) || null;
}

/**
 * Register or update a docket in the discovered dockets catalog (idempotent ON CONFLICT)
 */
export async function registerDiscoveredDocket(docket: Partial<DiscoveredDocket>): Promise<DiscoveredDocket> {
  const now = new Date().toISOString();

  if (useDb) {
    try {
      const rows = await pgQuery(
        `INSERT INTO docket_catalog (
          docket_id, source, agency_id, topic_id, title, summary, status,
          comment_count_estimate, last_comment_date, last_ingested_at, last_analyzed_at,
          freshness_label, priority_score, user_requested_count, tags_json, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
        ON CONFLICT (docket_id) DO UPDATE SET
          source = EXCLUDED.source,
          agency_id = EXCLUDED.agency_id,
          topic_id = EXCLUDED.topic_id,
          title = EXCLUDED.title,
          summary = EXCLUDED.summary,
          status = EXCLUDED.status,
          comment_count_estimate = EXCLUDED.comment_count_estimate,
          last_comment_date = EXCLUDED.last_comment_date,
          last_ingested_at = EXCLUDED.last_ingested_at,
          last_analyzed_at = EXCLUDED.last_analyzed_at,
          freshness_label = EXCLUDED.freshness_label,
          priority_score = EXCLUDED.priority_score,
          user_requested_count = EXCLUDED.user_requested_count,
          tags_json = EXCLUDED.tags_json,
          updated_at = EXCLUDED.updated_at
        RETURNING *`,
        [
          docket.docket_id!,
          docket.source || "regulations_gov",
          docket.agency_id || "FTC",
          docket.topic_id || "unclassified",
          docket.title || "Short Title",
          docket.summary || "",
          docket.status || "discovered",
          docket.comment_count_estimate || 0,
          docket.last_comment_date || null,
          docket.last_ingested_at || null,
          docket.last_analyzed_at || null,
          docket.freshness_label || "Active",
          docket.priority_score || 0.0,
          docket.user_requested_count || 0,
          JSON.stringify(docket.tags || []),
          now,
          now,
        ]
      );
      return mapRowToDocket(rows[0]);
    } catch (err) {
      console.error("Failed to insert/upsert discovered docket in PostgreSQL:", err);
      throw err;
    }
  }

  // Local Dev Fallback: Write local JSON file
  ensureCatalogDirectory();
  const list = await listDiscoveredDockets();
  const index = list.findIndex((d) => d.docket_id === docket.docket_id);
  
  const newDocket: DiscoveredDocket = {
    docket_id: docket.docket_id!,
    source: docket.source || "regulations_gov",
    agency_id: docket.agency_id || "FTC",
    topic_id: docket.topic_id || "unclassified",
    title: docket.title || "Short Title",
    summary: docket.summary || "",
    status: docket.status || "discovered",
    comment_count_estimate: docket.comment_count_estimate || 1000,
    last_comment_date: docket.last_comment_date || null,
    last_ingested_at: docket.last_ingested_at || null,
    last_analyzed_at: docket.last_analyzed_at || null,
    freshness_label: docket.freshness_label || "Active",
    priority_score: docket.priority_score || 0.0,
    user_requested_count: docket.user_requested_count || 0,
    tags: docket.tags || [],
    created_at: index !== -1 ? list[index].created_at : now,
    updated_at: now,
  };

  if (index !== -1) {
    list[index] = newDocket;
  } else {
    list.push(newDocket);
  }

  fs.writeFileSync(
    LOCAL_CATALOG_PATH,
    JSON.stringify(
      list.map((d) => ({ ...d, tags: d.tags.join(", ") })),
      null,
      2
    ),
    "utf8"
  );

  return newDocket;
}

/**
 * Increment requests count for a discovered rulemaking (idempotent priority updates)
 */
export async function incrementUserRequestCount(docketId: string): Promise<DiscoveredDocket | null> {
  const docket = await getDiscoveredDocket(docketId);
  if (!docket) return null;

  docket.user_requested_count += 1;
  
  // Recalculate priority score locally
  const scaleScore = 25 * Math.min(1.0, docket.comment_count_estimate / 50000);
  const interestScore = 30 * Math.min(1.0, docket.user_requested_count / 10) + 15; // Watched bonus
  const recencyScore = 15; // default recency
  const agencyScore = ["FCC", "EPA", "CFPB", "FTC"].includes(docket.agency_id) ? 5 : 0;
  docket.priority_score = Math.min(100.0, Math.round(scaleScore + interestScore + recencyScore + agencyScore));

  return await registerDiscoveredDocket(docket);
}

/**
 * Maps a PostgreSQL database row to DiscoveredDocket TypeScript interface
 */
function mapRowToDocket(row: Record<string, unknown>): DiscoveredDocket {
  let tags: string[] = [];
  try {
    tags = Array.isArray(row.tags_json) ? (row.tags_json as string[]) : JSON.parse((row.tags_json as string) || "[]");
  } catch {
    tags = row.tags_json ? String(row.tags_json).split(",").map((s) => s.trim()) : [];
  }

  return {
    docket_id: row.docket_id as string,
    source: row.source as "regulations_gov" | "ecfs",
    agency_id: row.agency_id as string,
    topic_id: row.topic_id as string,
    title: row.title as string,
    summary: (row.summary as string) || "",
    status: row.status as DiscoveredDocket["status"],
    comment_count_estimate: Number(row.comment_count_estimate ?? 0),
    last_comment_date: row.last_comment_date ? new Date(row.last_comment_date as string).toISOString() : null,
    last_ingested_at: row.last_ingested_at ? new Date(row.last_ingested_at as string).toISOString() : null,
    last_analyzed_at: row.last_analyzed_at ? new Date(row.last_analyzed_at as string).toISOString() : null,
    freshness_label: (row.freshness_label as string) ?? "Active",
    priority_score: Number(row.priority_score ?? 0.0),
    user_requested_count: Number(row.user_requested_count ?? 0),
    tags,
    created_at: new Date(row.created_at as string).toISOString(),
    updated_at: new Date(row.updated_at as string).toISOString(),
  };
}

/**
 * Maps Databricks SQL Warehouse row format to local DiscoveredDocket interface
 */
function mapDbRowToDocket(r: Record<string, unknown>): DiscoveredDocket {
  const tagsStr = r.tags ? String(r.tags) : "";
  return {
    docket_id: r.docket_id as string,
    source: r.source as "regulations_gov" | "ecfs",
    agency_id: r.agency_id as string,
    topic_id: r.topic_id as string,
    title: r.title as string,
    summary: r.summary as string,
    status: r.status as DiscoveredDocket["status"],
    comment_count_estimate: Number(r.comment_count_estimate ?? 0),
    last_comment_date: r.last_comment_date ? new Date(r.last_comment_date as string).toISOString() : null,
    last_ingested_at: r.last_ingested_at ? new Date(r.last_ingested_at as string).toISOString() : null,
    last_analyzed_at: r.last_analyzed_at ? new Date(r.last_analyzed_at as string).toISOString() : null,
    freshness_label: (r.freshness_label as string) ?? "Active",
    priority_score: Number(r.priority_score ?? 0.0),
    user_requested_count: Number(r.user_requested_count ?? 0),
    tags: tagsStr ? tagsStr.split(",").map((s) => s.trim()) : [],
    created_at: r.created_at ? new Date(r.created_at as string).toISOString() : new Date().toISOString(),
    updated_at: r.updated_at ? new Date(r.updated_at as string).toISOString() : new Date().toISOString(),
  };
}
