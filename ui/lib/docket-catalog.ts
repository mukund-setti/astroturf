import { query as pgQuery, isConnectionError } from "./db";
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
  // Source-API validation tracking. See ui/db/migrations/003_add_docket_validation.sql
  // and scripts/validate_discoveries.py. Anything other than 'validated_real'
  // means the docket may not exist on its source API and a one-click
  // "Request analysis" could silently return zero rows.
  validation_status: "unvalidated" | "validated_real" | "validated_empty" | "not_found" | "error";
  validated_comment_count: number | null;
  validated_at: string | null;
  validation_source: string | null;
}

// Supabase Postgres is the only store. No more local JSON fallback.
const databaseUrl = (process.env.DATABASE_URL ?? "").trim();
if (!databaseUrl) {
  throw new Error(
    "CRITICAL CONFIGURATION ERROR: DATABASE_URL is required. The UI control plane talks to Supabase Postgres exclusively; there is no local JSON fallback."
  );
}

/**
 * List all discovered and monitored rulemaking dockets.
 *
 * If the Postgres cache is empty and Databricks SQL credentials are available,
 * seed the cache from `<catalog>.discovery.docket_catalog` (written by the
 * autopilot workflow). Otherwise return whatever Postgres has, including [].
 */
export async function listDiscoveredDockets(): Promise<DiscoveredDocket[]> {
  let rows: DiscoveredDocket[];
  try {
    const pgRows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM docket_catalog ORDER BY priority_score DESC"
    );
    rows = pgRows.map(mapRowToDocket);
  } catch (err) {
    console.error("Failed to query docket catalog from PostgreSQL:", err);
    if (isConnectionError(err)) return [];
    throw err;
  }

  if (rows.length > 0) return rows;

  // Postgres empty — try to seed from the Databricks autopilot output.
  if (isOfflineMode()) return [];
  try {
    const catalog = getCatalog();
    const sql = `SELECT * FROM ${catalog}.discovery.docket_catalog ORDER BY priority_score DESC`;
    const dbRows = await queryDb<Record<string, unknown>>(sql);
    const mapped = dbRows.map(mapDbRowToDocket);
    for (const docket of mapped) {
      try {
        await registerDiscoveredDocket(docket);
      } catch (seedErr) {
        console.error(`Failed to seed docket ${docket.docket_id} into Postgres:`, seedErr);
      }
    }
    return mapped;
  } catch (dbErr) {
    console.warn("Failed to read docket_catalog from Databricks SQL:", dbErr);
    return [];
  }
}

/**
 * List dockets that are valid candidates for a brand-new analysis request.
 *
 * Excludes any docket that already has an analysis_request row in
 * ('submitted', 'running', 'succeeded') status — the user has either just
 * requested it or has already received results, so re-surfacing it on the
 * "candidates to analyze" page would be noise.
 *
 * Dockets with only 'failed', 'canceled', or 'draft' analysis_requests are
 * still shown so the user can retry. Dockets the catalog itself has marked
 * as 'analyzed' are also filtered (they have a permanent results page).
 */
export async function listAvailableDiscoveries(): Promise<DiscoveredDocket[]> {
  try {
    const pgRows = await pgQuery<Record<string, unknown>>(
      `
      SELECT dc.*
      FROM docket_catalog dc
      WHERE dc.status NOT IN ('analyzed', 'analyzing')
        AND NOT EXISTS (
          SELECT 1
          FROM analysis_requests ar
          WHERE ar.docket_id = dc.docket_id
            AND ar.status IN ('submitted', 'running', 'succeeded')
        )
      ORDER BY dc.priority_score DESC
      `,
    );
    return pgRows.map(mapRowToDocket);
  } catch (err) {
    console.error("Failed to query available discoveries from PostgreSQL:", err);
    if (isConnectionError(err)) return [];
    throw err;
  }
}

/**
 * Dockets that have at least one *succeeded* analysis request.
 *
 * The discoveries page renders these in a "Recently analyzed" section below
 * the "Awaiting analysis" list so the page is never empty just because the
 * autopilot's queue has temporarily caught up to the catalog. Each card links
 * to the analysis-detail page for the most recent succeeded run instead of
 * the "Request analysis" submit flow.
 */
export interface AnalyzedDocket extends DiscoveredDocket {
  latest_request_id: string;
  latest_run_completed_at: string;
  latest_databricks_run_id: string | null;
}

export async function listAnalyzedDockets(): Promise<AnalyzedDocket[]> {
  try {
    const pgRows = await pgQuery<Record<string, unknown>>(
      `
      SELECT dc.*,
             ar.request_id AS latest_request_id,
             ar.updated_at AS latest_run_completed_at,
             ar.databricks_run_id AS latest_databricks_run_id
      FROM docket_catalog dc
      INNER JOIN LATERAL (
        SELECT request_id, updated_at, databricks_run_id
        FROM analysis_requests
        WHERE docket_id = dc.docket_id
          AND status = 'succeeded'
        ORDER BY updated_at DESC
        LIMIT 1
      ) ar ON true
      ORDER BY ar.updated_at DESC
      `,
    );
    return pgRows.map((row) => {
      const base = mapRowToDocket(row);
      return {
        ...base,
        latest_request_id: row.latest_request_id as string,
        latest_run_completed_at: new Date(row.latest_run_completed_at as string).toISOString(),
        latest_databricks_run_id: (row.latest_databricks_run_id as string | null) ?? null,
      };
    });
  } catch (err) {
    console.error("Failed to query analyzed dockets from PostgreSQL:", err);
    if (isConnectionError(err)) return [];
    throw err;
  }
}

/**
 * Get a specific discovered docket by ID.
 */
export async function getDiscoveredDocket(docketId: string): Promise<DiscoveredDocket | null> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM docket_catalog WHERE LOWER(docket_id) = LOWER($1)",
      [docketId]
    );
    if (rows.length === 0) return null;
    return mapRowToDocket(rows[0]);
  } catch (err) {
    console.error(`Failed to get docket ${docketId} from PostgreSQL:`, err);
    if (isConnectionError(err)) return null;
    throw err;
  }
}

/**
 * Register or update a docket in the discovered dockets catalog
 * (idempotent ON CONFLICT).
 */
export async function registerDiscoveredDocket(docket: Partial<DiscoveredDocket>): Promise<DiscoveredDocket> {
  const now = new Date().toISOString();

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
}

/**
 * Increment requests count for a discovered rulemaking (idempotent priority updates).
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
    validation_status: (row.validation_status as DiscoveredDocket["validation_status"]) ?? "unvalidated",
    validated_comment_count:
      row.validated_comment_count !== null && row.validated_comment_count !== undefined
        ? Number(row.validated_comment_count)
        : null,
    validated_at: row.validated_at ? new Date(row.validated_at as string).toISOString() : null,
    validation_source: (row.validation_source as string | null) ?? null,
  };
}

/**
 * Maps Databricks SQL Warehouse row format to local DiscoveredDocket interface.
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
    // Databricks-side discovery doesn't populate validation_* fields; that
    // lives in the Postgres control plane via scripts/validate_discoveries.py.
    validation_status: (r.validation_status as DiscoveredDocket["validation_status"]) ?? "unvalidated",
    validated_comment_count:
      r.validated_comment_count !== null && r.validated_comment_count !== undefined
        ? Number(r.validated_comment_count)
        : null,
    validated_at: r.validated_at ? new Date(r.validated_at as string).toISOString() : null,
    validation_source: (r.validation_source as string | null) ?? null,
  };
}
