import fs from "fs";
import path from "path";
import { query as pgQuery } from "./db";

export interface AnalysisRequest {
  request_id: string;
  docket_id: string;
  source: string;
  topic_id: string;
  agency_id: string;
  title: string;
  date_start: string | null;
  date_end: string | null;
  expected_scale: number;
  notes: string;
  status: "draft" | "submitted" | "running" | "succeeded" | "failed" | "canceled";
  databricks_run_id: string | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  result_url: string | null;
}

const isProduction = process.env.ASTROTURF_DEPLOYMENT_MODE === "production";
const hasDatabaseUrl = Boolean(process.env.DATABASE_URL && process.env.DATABASE_URL.trim());

// Fail loudly in production if DATABASE_URL is missing
if (isProduction && !hasDatabaseUrl) {
  throw new Error("CRITICAL CONFIGURATION ERROR: Missing required environment variable 'DATABASE_URL' in production deployment mode. Production requires PostgreSQL state storage.");
}

const useDb = isProduction || hasDatabaseUrl;

const DATA_DIR = path.resolve(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "analysis-requests.json");

function ensureStoreExists(): void {
  // Never write local files in production
  if (isProduction) return;

  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(STORE_PATH)) {
      fs.writeFileSync(STORE_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize local analysis store directory or file:", err);
  }
}

/**
 * List all analysis requests (newest first)
 */
export async function listAnalysisRequests(): Promise<AnalysisRequest[]> {
  if (useDb) {
    try {
      const rows = await pgQuery<Record<string, unknown>>(
        "SELECT * FROM analysis_requests ORDER BY created_at DESC"
      );
      return rows.map(mapRowToRequest);
    } catch (err) {
      console.error("Failed to list analysis requests from PostgreSQL:", err);
      // In production we refuse fallback
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
      console.warn("Analysis request store is not an array, resetting to empty.");
      return [];
    }
    return parsed;
  } catch (err) {
    console.error("Failed to read analysis requests JSON store. Returning empty list.", err);
    return [];
  }
}

/**
 * Retrieve a specific analysis request by ID
 */
export async function getAnalysisRequest(id: string): Promise<AnalysisRequest | null> {
  if (useDb) {
    try {
      const rows = await pgQuery<Record<string, unknown>>(
        "SELECT * FROM analysis_requests WHERE request_id = $1",
        [id]
      );
      if (rows.length === 0) return null;
      return mapRowToRequest(rows[0]);
    } catch (err) {
      console.error(`Failed to fetch analysis request ${id} from PostgreSQL:`, err);
      if (isProduction) throw err;
    }
  }

  const list = await listAnalysisRequests();
  return list.find((req) => req.request_id === id) || null;
}

/**
 * Create a new analysis request
 */
export async function createAnalysisRequest(
  input: Omit<
    AnalysisRequest,
    "request_id" | "status" | "databricks_run_id" | "created_at" | "updated_at" | "error_message" | "result_url"
  >
): Promise<AnalysisRequest> {
  const id = `req_${Math.random().toString(36).substring(2, 11)}`;
  const now = new Date().toISOString();

  if (useDb) {
    try {
      await pgQuery(
        `INSERT INTO analysis_requests (
          request_id, docket_id, source, topic_id, agency_id, title,
          date_start, date_end, expected_scale, notes, status,
          databricks_run_id, error_message, result_url, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`,
        [
          id,
          input.docket_id,
          input.source,
          input.topic_id,
          input.agency_id,
          input.title,
          input.date_start,
          input.date_end,
          input.expected_scale,
          input.notes,
          "draft",
          null,
          null,
          null,
          now,
          now,
        ]
      );

      return {
        ...input,
        request_id: id,
        status: "draft",
        databricks_run_id: null,
        created_at: now,
        updated_at: now,
        error_message: null,
        result_url: null,
      };
    } catch (err) {
      console.error("Failed to insert analysis request into PostgreSQL:", err);
      throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  const list = await listAnalysisRequests();
  const newRequest: AnalysisRequest = {
    ...input,
    request_id: id,
    status: "draft",
    databricks_run_id: null,
    created_at: now,
    updated_at: now,
    error_message: null,
    result_url: null,
  };

  list.push(newRequest);
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return newRequest;
}

/**
 * Update an existing analysis request (supports partial PATCH)
 */
export async function updateAnalysisRequest(
  id: string,
  patch: Partial<AnalysisRequest>
): Promise<AnalysisRequest | null> {
  if (useDb) {
    try {
      // Dynamic UPDATE query builder for strict columns matching
      const allowedKeys = [
        "docket_id", "source", "topic_id", "agency_id", "title",
        "date_start", "date_end", "expected_scale", "notes", "status",
        "databricks_run_id", "error_message", "result_url"
      ];
      
      const fields = Object.keys(patch).filter((k) => allowedKeys.includes(k));
      if (fields.length === 0) {
        return getAnalysisRequest(id);
      }

      const now = new Date().toISOString();
      const sets = fields.map((f, i) => `${f} = $${i + 2}`);
      sets.push(`updated_at = $${fields.length + 2}`);

      const params = fields.map((f) => (patch as Record<string, unknown>)[f]);
      params.push(now);

      const queryText = `
        UPDATE analysis_requests 
        SET ${sets.join(", ")} 
        WHERE request_id = $1 
        RETURNING *
      `;

      const rows = await pgQuery<Record<string, unknown>>(queryText, [id, ...params]);
      if (rows.length === 0) return null;
      return mapRowToRequest(rows[0]);
    } catch (err) {
      console.error(`Failed to update analysis request ${id} in PostgreSQL:`, err);
      throw err;
    }
  }

  // Local fallback for dev mode
  ensureStoreExists();
  const list = await listAnalysisRequests();
  const index = list.findIndex((req) => req.request_id === id);
  if (index === -1) {
    return null;
  }

  const updated = {
    ...list[index],
    ...patch,
    updated_at: new Date().toISOString(),
  };

  list[index] = updated;
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return updated;
}

/**
 * Helper to convert PostgreSQL column formats to local TS interfaces
 */
function mapRowToRequest(row: Record<string, unknown>): AnalysisRequest {
  return {
    request_id: row.request_id as string,
    docket_id: row.docket_id as string,
    source: row.source as string,
    topic_id: row.topic_id as string,
    agency_id: row.agency_id as string,
    title: row.title as string,
    date_start: row.date_start ? new Date(row.date_start as string).toISOString().split("T")[0] : null,
    date_end: row.date_end ? new Date(row.date_end as string).toISOString().split("T")[0] : null,
    expected_scale: Number(row.expected_scale ?? 0),
    notes: (row.notes as string) || "",
    status: row.status as AnalysisRequest["status"],
    databricks_run_id: (row.databricks_run_id as string) || null,
    created_at: new Date(row.created_at as string).toISOString(),
    updated_at: new Date(row.updated_at as string).toISOString(),
    error_message: (row.error_message as string) || null,
    result_url: (row.result_url as string) || null,
  };
}
