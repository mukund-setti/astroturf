import { createHash } from "node:crypto";

import { query as pgQuery, isConnectionError, sanitizeDatabaseError } from "./db";
import { getCatalog, query as queryDb } from "./databricks";
import { topicForDocket, topicSlugsForQuery } from "./topics";

export const MIN_CLUSTER_SIZE_FOR_FINDING = 10;
export const MIN_CLUSTER_SIZE_FOR_FEATURED_FINDING = 100;

export interface Finding {
  id: string;
  cluster_id: string;
  docket_id: string;
  slug: string;
  headline: string;
  one_liner: string;
  topic_slug: string;
  cluster_size: number;
  posted_date_range: string | null;
  agency_id: string | null;
  is_featured: boolean;
  auto_generated: boolean;
  manually_edited: boolean;
  created_at: string;
  updated_at: string;
}

export interface FindingGenerationInput {
  cluster_id: string;
  docket_id: string;
  agency_id?: string;
  topic_slug?: string;
}

export interface GeneratedFindingPreview {
  cluster_id: string;
  docket_id: string;
  rep_text: string;
  rep_submitter_name: string | null;
  cluster_size: number;
  posted_date_range: string | null;
  headline: string;
  one_liner: string;
  topic_slug: string;
  agency_id: string | null;
  slug: string;
}

const databaseUrl = (process.env.DATABASE_URL ?? "").trim();
if (!databaseUrl) {
  throw new Error(
    "CRITICAL CONFIGURATION ERROR: DATABASE_URL is required for findings-store; control-plane storage is Postgres-only.",
  );
}

// ---------- Reads ----------

export async function listFindingsByTopic(topicSlug: string): Promise<Finding[]> {
  const slugs = topicSlugsForQuery(topicSlug);
  try {
    const placeholders = slugs.map((_, i) => `$${i + 1}`).join(", ");
    const rows = await pgQuery<Record<string, unknown>>(
      `SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY docket_id ORDER BY cluster_size DESC) as rn
        FROM findings WHERE topic_slug IN (${placeholders})
      ) sub WHERE rn = 1
      ORDER BY cluster_size DESC, created_at DESC`,
      slugs,
    );
    return rows.map(mapRowToFinding);
  } catch (err) {
    console.error(
      `listFindingsByTopic(${topicSlug}) failed:`,
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return [];
    throw err;
  }
}

export async function getFindingBySlug(slug: string): Promise<Finding | null> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM findings WHERE slug = $1",
      [slug],
    );
    if (rows.length === 0) return null;
    return mapRowToFinding(rows[0]);
  } catch (err) {
    console.error(
      `getFindingBySlug(${slug}) failed:`,
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return null;
    throw err;
  }
}

export async function getFindingByClusterId(
  cluster_id: string,
): Promise<Finding | null> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      "SELECT * FROM findings WHERE cluster_id = $1",
      [cluster_id],
    );
    if (rows.length === 0) return null;
    return mapRowToFinding(rows[0]);
  } catch (err) {
    console.error(
      `getFindingByClusterId(${cluster_id}) failed:`,
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return null;
    throw err;
  }
}

/**
 * Returns the set of top-level topic slugs that have *something* the user
 * can click through to: at least one finding, OR at least one docket in
 * docket_catalog. The topic page renders the findings list when findings
 * exist and a "we have N analyzable dockets here" picker otherwise — so
 * either case lands the user on real content, not a generic CTA.
 *
 * Wrapper around listPopulatedTopicSlugs (findings) +
 * listTopicSlugsWithDockets (catalog).
 */
export async function listAvailableTopicSlugs(): Promise<Set<string>> {
  const { listTopicSlugsWithDockets } = await import("./docket-catalog");
  const [withFindings, withDockets] = await Promise.all([
    listPopulatedTopicSlugs(),
    listTopicSlugsWithDockets(),
  ]);
  const merged = new Set(withFindings);
  for (const s of withDockets) merged.add(s);
  return merged;
}

/**
 * Returns the set of top-level topic slugs (TOPICS[].slug) that have at
 * least one finding - directly or via any of their `gathers` children.
 *
 * Used by the home page bubble grid and /api/search/suggest to hide topics
 * that would just dead-end into the "Queue this for analysis" CTA. Keeping
 * the surface honest: every visible topic is one a user can click through
 * to real content.
 */
export async function listPopulatedTopicSlugs(): Promise<Set<string>> {
  const populated = new Set<string>();
  try {
    const rows = await pgQuery<{ topic_slug: string }>(
      "SELECT DISTINCT topic_slug FROM findings WHERE topic_slug IS NOT NULL",
    );
    const directSlugs = new Set(rows.map((r) => r.topic_slug));
    // A gather-parent (e.g. "the-economy") counts as populated when ANY of
    // its child slugs has a finding. Doing the expansion here keeps the
    // helper signature simple - callers don't need to know about gathers.
    const { TOPICS } = await import("./topics");
    for (const topic of TOPICS) {
      if (directSlugs.has(topic.slug)) {
        populated.add(topic.slug);
        continue;
      }
      if (topic.gathers?.some((child) => directSlugs.has(child))) {
        populated.add(topic.slug);
      }
    }
  } catch (err) {
    console.error(
      "listPopulatedTopicSlugs failed:",
      sanitizeDatabaseError(err),
    );
    if (isConnectionError(err)) return populated;
    throw err;
  }
  return populated;
}

export async function getFeaturedFindings(limit = 4): Promise<Finding[]> {
  try {
    const rows = await pgQuery<Record<string, unknown>>(
      `SELECT *
         FROM (
           SELECT *,
                  ROW_NUMBER() OVER (
                    PARTITION BY docket_id
                    ORDER BY is_featured DESC, cluster_size DESC, created_at DESC
                  ) AS rn
             FROM findings
            WHERE cluster_size >= $2
         ) ranked
        WHERE rn = 1
        ORDER BY is_featured DESC, cluster_size DESC, created_at DESC
        LIMIT $1`,
      [limit, MIN_CLUSTER_SIZE_FOR_FEATURED_FINDING],
    );
    return rows.map(mapRowToFinding);
  } catch (err) {
    console.error("getFeaturedFindings failed:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return [];
    throw err;
  }
}

// ---------- Writes ----------

/**
 * Insert-or-update a finding keyed by cluster_id. Re-running generation
 * against the same cluster updates the existing row (headline/one_liner
 * may shift if the prompt or model changes) and keeps the same slug.
 */
export async function upsertFinding(
  input: Omit<Finding, "id" | "created_at" | "updated_at">,
): Promise<Finding> {
  const rows = await pgQuery<Record<string, unknown>>(
    `INSERT INTO findings (
      cluster_id, docket_id, slug, headline, one_liner, topic_slug,
      cluster_size, posted_date_range, agency_id, is_featured,
      auto_generated, manually_edited
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    ON CONFLICT (cluster_id) DO UPDATE SET
      docket_id = EXCLUDED.docket_id,
      slug = EXCLUDED.slug,
      headline = CASE WHEN findings.manually_edited THEN findings.headline ELSE EXCLUDED.headline END,
      one_liner = CASE WHEN findings.manually_edited THEN findings.one_liner ELSE EXCLUDED.one_liner END,
      topic_slug = EXCLUDED.topic_slug,
      cluster_size = EXCLUDED.cluster_size,
      posted_date_range = EXCLUDED.posted_date_range,
      agency_id = EXCLUDED.agency_id,
      is_featured = EXCLUDED.is_featured,
      auto_generated = EXCLUDED.auto_generated,
      updated_at = NOW()
    RETURNING *`,
    [
      input.cluster_id,
      input.docket_id,
      input.slug,
      input.headline,
      input.one_liner,
      input.topic_slug,
      input.cluster_size,
      input.posted_date_range,
      input.agency_id,
      input.is_featured,
      input.auto_generated,
      input.manually_edited,
    ],
  );
  return mapRowToFinding(rows[0]);
}

// ---------- Generation ----------

interface ClusterContextRow {
  cluster_id: string;
  docket_id: string;
  cluster_size: number;
  rep_text: string;
  rep_submitter_name: string | null;
  earliest_posted_date: string | null;
  latest_posted_date: string | null;
}

/**
 * Pulls the cluster's representative comment + metadata from the lakehouse
 * so the LLM has something to summarize. Returns null when the cluster
 * isn't present in cluster_review_export for the given docket.
 */
async function loadClusterContext(
  cluster_id: string,
  docket_id: string,
): Promise<ClusterContextRow | null> {
  const catalog = getCatalog();
  const sql = `
    SELECT
      cluster_id,
      docket_id,
      MAX(cluster_size) AS cluster_size,
      MAX(CASE WHEN is_representative THEN text_preview END) AS rep_text,
      MAX(CASE WHEN is_representative THEN submitter_name END) AS rep_submitter_name,
      MIN(posted_date) AS earliest_posted_date,
      MAX(posted_date) AS latest_posted_date
    FROM ${catalog}.demo.cluster_review_export
    WHERE cluster_id = :cluster_id AND docket_id = :docket_id
    GROUP BY cluster_id, docket_id
  `;
  const rows = await queryDb<Record<string, unknown>>(sql, {
    cluster_id,
    docket_id,
  });
  if (rows.length === 0) return null;
  const r = rows[0];
  const repText = (r.rep_text as string | null) ?? null;
  if (!repText) return null;
  return {
    cluster_id: r.cluster_id as string,
    docket_id: r.docket_id as string,
    cluster_size: Number(r.cluster_size ?? 0),
    rep_text: repText,
    rep_submitter_name: (r.rep_submitter_name as string | null) ?? null,
    earliest_posted_date: isoOrNull(r.earliest_posted_date),
    latest_posted_date: isoOrNull(r.latest_posted_date),
  };
}

// Findings copy is generated via the Databricks Foundation Model API, which
// serves Claude through Databricks credentials (DATABRICKS_HOST +
// DATABRICKS_TOKEN). We hit the OpenAI-style chat-completion endpoint at
// /serving-endpoints/<endpoint>/invocations so there is no separate
// Anthropic SDK or API key to manage.
// Using Llama 3.3 70B because Claude endpoints on this workspace are rate-limited to 0. Swap back to a Claude endpoint when available; same request shape.
const FOUNDATION_MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct";

function buildUserPrompt(ctx: ClusterContextRow, agency_id: string | null): string {
  const dateRange =
    formatDateRange(ctx.earliest_posted_date, ctx.latest_posted_date) ?? "unknown";
  return `You are writing a short, neutral finding card for a tool that detects coordinated public comment campaigns on US federal rulemaking.

The input is the representative comment from one cluster of textually similar comments submitted to a federal agency. Cluster size: ${ctx.cluster_size}. Agency: ${agency_id ?? "unknown"}. Docket: ${ctx.docket_id}. Date range: ${dateRange}.

Comment text:
"""
${ctx.rep_text.trim()}
"""

Write two pieces of copy:

1. headline: 4-8 words. Describe what the campaign was about in plain language. News-style. Capitalize the first word and proper nouns only - no title case. No period.

2. one_liner: exactly 2 sentences. First sentence MUST include the cluster size (${ctx.cluster_size}) as "${ctx.cluster_size} similar comments" - this is the single most important fact. Structure: "[Agency full name] received ${ctx.cluster_size} similar comments in [month year] regarding [rule topic in plain English]." If the comment uses technical terms (Title II, NPRM, CFR section numbers), translate them - say "net neutrality" not "Title II"; say "the proposed rule" not "the NPRM". Second sentence: what the campaign argued.

Hard rules:
- Do not editorialize. No words like "scandal," "fraud," "secret," "shocking."
- Do not assume motives. The comments are textually similar; that's the finding.
- Do not speculate about who organized the campaign. That's a separate analysis.
- If the comment text is too short or unclear to write a meaningful finding, return headline: "Unclear campaign focus" and a one_liner explaining the cluster size and agency.

Casing rules:
- For the headline, treat acronyms like "FCC", "EPA", "CFPB" as all-caps and never split them into "Fcc" or "Epa". Capitalize the first word; lowercase everything else except proper nouns and acronyms. Example: "FCC considers net neutrality repeal".
- For the one_liner, write the agency name in standard prose capitalization on first mention ("the Federal Communications Commission" or "the FCC"), not lowercased.

Do not put docket IDs, cluster IDs, or other internal identifiers in the headline or one_liner. Those go in technical details elsewhere in the UI.

Return as JSON: {"headline": "...", "one_liner": "..."}`;
}

interface LlmFindingDraft {
  headline: string;
  one_liner: string;
}

async function callClaudeForDraft(
  ctx: ClusterContextRow,
  agency_id: string | null,
): Promise<LlmFindingDraft> {
  const host = (process.env.DATABRICKS_HOST ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  const token = (process.env.DATABRICKS_TOKEN ?? "").trim();
  if (!host || !token) {
    throw new Error(
      "DATABRICKS_HOST and DATABRICKS_TOKEN must be set to call the Foundation Model API.",
    );
  }

  const url = `https://${host}/serving-endpoints/${FOUNDATION_MODEL_ENDPOINT}/invocations`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: buildUserPrompt(ctx, agency_id) }],
      max_tokens: 600,
      temperature: 0.3,
      response_format: { type: "json_object" },
    }),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(
      `Databricks Foundation Model API returned HTTP ${response.status}: ${body.slice(0, 300)}`,
    );
  }

  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const raw = data.choices?.[0]?.message?.content?.trim();
  if (!raw) {
    throw new Error("Foundation Model response contained no message content.");
  }
  const jsonText = extractJsonObject(raw);
  let parsed: unknown;
  try {
    parsed = JSON.parse(jsonText);
  } catch {
    throw new Error(`Model returned non-JSON output: ${raw.slice(0, 200)}`);
  }
  if (
    !parsed ||
    typeof parsed !== "object" ||
    typeof (parsed as Record<string, unknown>).headline !== "string" ||
    typeof (parsed as Record<string, unknown>).one_liner !== "string"
  ) {
    throw new Error(`Model returned malformed JSON: ${jsonText.slice(0, 200)}`);
  }
  return {
    headline: ((parsed as Record<string, unknown>).headline as string).trim(),
    one_liner: ((parsed as Record<string, unknown>).one_liner as string).trim(),
  };
}

/**
 * End-to-end: pulls cluster context from Databricks, asks Claude for a
 * headline + one_liner, upserts a finding row, and returns it.
 */
export async function generateFindingFromCluster(
  input: FindingGenerationInput,
): Promise<Finding | null> {
  const ctx = await loadClusterContext(input.cluster_id, input.docket_id);
  if (!ctx) {
    throw new Error(
      `No cluster context found for cluster_id=${input.cluster_id} docket_id=${input.docket_id}`,
    );
  }
  if (ctx.cluster_size < MIN_CLUSTER_SIZE_FOR_FINDING) {
    return null;
  }
  const draft = await callClaudeForDraft(ctx, input.agency_id ?? null);
  const topic_slug = input.topic_slug ?? topicForDocket(input.docket_id, input.agency_id);
  const slug = makeSlug(draft.headline, input.cluster_id);
  return upsertFinding({
    cluster_id: input.cluster_id,
    docket_id: input.docket_id,
    slug,
    headline: draft.headline,
    one_liner: draft.one_liner,
    topic_slug,
    cluster_size: ctx.cluster_size,
    posted_date_range: formatDateRange(
      ctx.earliest_posted_date,
      ctx.latest_posted_date,
    ),
    agency_id: input.agency_id ?? null,
    is_featured: false,
    auto_generated: true,
    manually_edited: false,
  });
}

/**
 * Generates and returns the proposed finding without writing anything.
 * Used by the diagnostic CLI / step-5 stopping rule so we can eyeball
 * input -> output before backfilling.
 */
export async function previewFindingFromCluster(
  input: FindingGenerationInput,
): Promise<GeneratedFindingPreview> {
  const ctx = await loadClusterContext(input.cluster_id, input.docket_id);
  if (!ctx) {
    throw new Error(
      `No cluster context found for cluster_id=${input.cluster_id} docket_id=${input.docket_id}`,
    );
  }
  const draft = await callClaudeForDraft(ctx, input.agency_id ?? null);
  const topic_slug = input.topic_slug ?? topicForDocket(input.docket_id, input.agency_id);
  const slug = makeSlug(draft.headline, input.cluster_id);
  return {
    cluster_id: ctx.cluster_id,
    docket_id: ctx.docket_id,
    rep_text: ctx.rep_text,
    rep_submitter_name: ctx.rep_submitter_name,
    cluster_size: ctx.cluster_size,
    posted_date_range: formatDateRange(
      ctx.earliest_posted_date,
      ctx.latest_posted_date,
    ),
    headline: draft.headline,
    one_liner: draft.one_liner,
    topic_slug,
    agency_id: input.agency_id ?? null,
    slug,
  };
}

// ---------- Helpers (exported for tests) ----------

export function makeSlug(headline: string, cluster_id: string): string {
  const base = headline
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/g, "");
  const suffix = createHash("sha256").update(cluster_id).digest("hex").slice(0, 6);
  return base ? `${base}-${suffix}` : `finding-${suffix}`;
}

export function formatDateRange(
  start: string | null,
  end: string | null,
): string | null {
  const s = toDateOnly(start);
  const e = toDateOnly(end);
  if (!s && !e) return null;
  if (s && e && s === e) return s;
  if (s && e) return `${s} to ${e}`;
  return s ?? e;
}

function toDateOnly(value: string | null): string | null {
  if (!value) return null;
  // Accept ISO timestamps, plain dates, or date-only strings.
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) {
    // Fall back to a YYYY-MM-DD prefix if value already looks like one.
    return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null;
  }
  return d.toISOString().slice(0, 10);
}

function isoOrNull(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "string") return value;
  return null;
}

function extractJsonObject(text: string): string {
  // Strip code fences if Claude wrapped the JSON.
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) return fence[1].trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start !== -1 && end !== -1 && end > start) {
    return text.slice(start, end + 1);
  }
  return text;
}

function mapRowToFinding(row: Record<string, unknown>): Finding {
  return {
    id: row.id as string,
    cluster_id: row.cluster_id as string,
    docket_id: row.docket_id as string,
    slug: row.slug as string,
    headline: row.headline as string,
    one_liner: row.one_liner as string,
    topic_slug: row.topic_slug as string,
    cluster_size: Number(row.cluster_size ?? 0),
    posted_date_range: (row.posted_date_range as string | null) ?? null,
    agency_id: (row.agency_id as string | null) ?? null,
    is_featured: Boolean(row.is_featured),
    auto_generated: Boolean(row.auto_generated),
    manually_edited: Boolean(row.manually_edited),
    created_at: new Date(row.created_at as string).toISOString(),
    updated_at: new Date(row.updated_at as string).toISOString(),
  };
}
