import { query as pgQuery, isConnectionError, sanitizeDatabaseError } from "./db";

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
  // Columns added in migration 004 for the consumer-facing queue flow.
  // Older /api/analysis POSTs leave these null; the new /api/queue-analysis
  // POST populates all three.
  requested_by: string | null;
  query_text: string | null;
  topic_slug: string | null;
}

// Supabase Postgres is the only store. No more local JSON fallback - every
// store call goes through pgQuery. Connection-level failures (DB unreachable)
// degrade gracefully on reads via isConnectionError(); query-level failures
// (bad SQL, schema mismatch) and all writes throw.
const databaseUrl = (process.env.DATABASE_URL ?? "").trim();
if (!databaseUrl) {
  throw new Error(
    "CRITICAL CONFIGURATION ERROR: DATABASE_URL is required. The UI control plane talks to Supabase Postgres exclusively; there is no local JSON fallback."
  );
}

/**
 * List all analysis requests (newest first).
 */
export async function listAnalysisRequests(): Promise<AnalysisRequest[]> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM analysis_requests ORDER BY created_at DESC"
    );
    return rows.map(mapRowToRequest);
  } catch (err) {
    console.error("Failed to list analysis requests from PostgreSQL:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return [];
    throw err;
  }
}

/**
 * Retrieve a specific analysis request by ID.
 */
export async function getAnalysisRequest(id: string): Promise<AnalysisRequest | null> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM analysis_requests WHERE request_id = $1",
      [id]
    );
    if (rows.length === 0) return null;
    return mapRowToRequest(rows[0]);
  } catch (err) {
    console.error(`Failed to fetch analysis request ${id} from PostgreSQL:`, sanitizeDatabaseError(err));
    if (isConnectionError(err)) return null;
    throw err;
  }
}

/**
 * Create a new analysis request. The three "consumer-flow" columns
 * (requested_by, query_text, topic_slug) are optional - legacy callers
 * from /api/analysis don't supply them, the new /api/queue-analysis does.
 */
export async function createAnalysisRequest(
  input: Omit<
    AnalysisRequest,
    | "request_id"
    | "status"
    | "databricks_run_id"
    | "created_at"
    | "updated_at"
    | "error_message"
    | "result_url"
    | "requested_by"
    | "query_text"
    | "topic_slug"
  > & {
    requested_by?: string | null;
    query_text?: string | null;
    topic_slug?: string | null;
  },
): Promise<AnalysisRequest> {
  const id = `req_${Math.random().toString(36).substring(2, 11)}`;
  const now = new Date().toISOString();
  const requested_by = input.requested_by ?? null;
  const query_text = input.query_text ?? null;
  const topic_slug = input.topic_slug ?? null;

  await pgQuery(
    `INSERT INTO analysis_requests (
      request_id, docket_id, source, topic_id, agency_id, title,
      date_start, date_end, expected_scale, notes, status,
      databricks_run_id, error_message, result_url, created_at, updated_at,
      requested_by, query_text, topic_slug
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)`,
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
      requested_by,
      query_text,
      topic_slug,
    ],
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
    requested_by,
    query_text,
    topic_slug,
  };
}

/**
 * Update an existing analysis request (partial PATCH).
 */
export async function updateAnalysisRequest(
  id: string,
  patch: Partial<AnalysisRequest>
): Promise<AnalysisRequest | null> {
  const allowedKeys = [
    "docket_id", "source", "topic_id", "agency_id", "title",
    "date_start", "date_end", "expected_scale", "notes", "status",
    "databricks_run_id", "error_message", "result_url",
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
}

/**
 * Return the docket_id of the most-recently-succeeded analysis request,
 * or null if no such row exists in the control plane.
 *
 * Used by the landing-page stats/clusters APIs so the dashboard automatically
 * shows the docket from the latest finished run instead of a hard-coded demo
 * docket.
 */
export async function getMostRecentSucceededDocketId(): Promise<string | null> {
  try {
    const rows = await pgQuery<{ docket_id: string }>(
      "SELECT docket_id FROM analysis_requests WHERE status = $1 ORDER BY updated_at DESC LIMIT 1",
      ["succeeded"]
    );
    if (rows.length === 0) return null;
    const value = (rows[0].docket_id ?? "").toString().trim();
    return value || null;
  } catch (err) {
    console.error(
      "Failed to query most-recently-succeeded analysis request from PostgreSQL:",
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return null;
    throw err;
  }
}

/**
 * Resolve the docket_id surfaced by the landing-page stats and clusters APIs.
 *
 * Precedence, top wins:
 *   1. The docket_id of the most-recently-succeeded analysis_requests row.
 *   2. The DEMO_DOCKET_ID environment variable, for deployments that want a
 *      pinned demo docket regardless of run history.
 *   3. The hard-coded string "17-108" (the original ECFS net-neutrality demo),
 *      so the dashboard never renders an empty/undefined docket.
 *
 * Intentionally separate from databricks.ts::getDocketId(), which is consumed
 * by other surfaces (e.g. app/page.tsx) where the older "env or 17-108"
 * behaviour is still appropriate.
 */
export async function resolveLandingDocketId(): Promise<string> {
  const fromDb = await getMostRecentSucceededDocketId();
  if (fromDb) return fromDb;
  const envValue = (process.env.DEMO_DOCKET_ID ?? "").trim();
  if (envValue) return envValue;
  return "17-108";
}

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
    requested_by: (row.requested_by as string | null) ?? null,
    query_text: (row.query_text as string | null) ?? null,
    topic_slug: (row.topic_slug as string | null) ?? null,
  };
}

/**
 * List analysis requests created by a given user UID (the astroturf_uid
 * cookie), newest first. Used by the UserRequestsBadge.
 */
export async function listAnalysisRequestsForUser(
  uid: string,
  limit = 20,
): Promise<AnalysisRequest[]> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      `SELECT * FROM analysis_requests
        WHERE requested_by = $1
        ORDER BY created_at DESC
        LIMIT $2`,
      [uid, limit],
    );
    return rows.map(mapRowToRequest);
  } catch (err) {
    console.error(
      `listAnalysisRequestsForUser(${uid}) failed:`,
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return [];
    throw err;
  }
}
