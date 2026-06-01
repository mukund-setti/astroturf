import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import {
  createAnalysisRequest,
  updateAnalysisRequest,
} from "@/lib/analysis-store";
import { query as pgQuery, isConnectionError, sanitizeDatabaseError } from "@/lib/db";
import { submitDocketJob, isJobSubmitEnabled } from "@/lib/databricks-jobs";
import {
  applyUserCookie,
  getOrCreateUserSession,
} from "@/lib/user-session";
import { topicForDocket } from "@/lib/topics";

// POST /api/queue-analysis
//
// Body: { query: string, docket_id?: string, topic_slug?: string }
//
// Flow:
//   1. Read or mint the astroturf_uid cookie.
//   2. Resolve a real docket:
//        a) If docket_id was passed, look it up in docket_catalog.
//        b) Otherwise, ILIKE-search docket_catalog by title/docket_id.
//      If nothing matches, return 404 with { error: "no_docket_match" }.
//   3. INSERT a row into analysis_requests with status='draft', tagged
//      with requested_by=uid, query_text=query, topic_slug.
//   4. If isJobSubmitEnabled() is true, call submitDocketJob() and update
//      status -> 'submitted' on success or 'failed' on error. The HTTP
//      response is the same shape either way; failures only show up in
//      the badge via status.
//   5. Always sets the cookie on the response when minted for the first
//      time, so the very same POST that queues an item also identifies
//      the user for subsequent /api/user-requests reads.

interface QueueRequestBody {
  query?: string;
  docket_id?: string;
  topic_slug?: string;
}

interface CatalogRow {
  docket_id: string;
  title: string | null;
  source: string | null;
  agency_id: string | null;
  topic_id: string | null;
  summary?: string | null;
  comment_count_estimate: number | null;
  tags_json: unknown;
}

const ESTIMATED_MINUTES = 10;
const FOUNDATION_MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct";
const STOPWORDS = new Set([
  "and",
  "are",
  "for",
  "how",
  "into",
  "non",
  "our",
  "regulation",
  "regulations",
  "rule",
  "rules",
  "that",
  "the",
  "this",
  "want",
  "what",
  "with",
]);

export async function POST(request: Request) {
  let body: QueueRequestBody;
  try {
    body = (await request.json()) as QueueRequestBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const query = (body.query ?? "").trim();
  if (!query && !body.docket_id) {
    return NextResponse.json(
      { error: "Either `query` or `docket_id` is required." },
      { status: 400 },
    );
  }

  const session = await getOrCreateUserSession();

  // Resolve the docket.
  let match: CatalogRow | null = null;
  if (body.docket_id) {
    match = await lookupDocketById(body.docket_id);
  }
  if (!match && query) {
    match = await searchCatalog(query);
  }
  if (!match && query) {
    match = await searchRegulationsGov(query);
  }
  if (!match) {
    const unresolved = await createUnresolvedRequest(query, body.topic_slug, session.uid);
    const response = NextResponse.json({
      request_id: unresolved.request_id,
      docket_id: unresolved.docket_id,
      docket_title: unresolved.title,
      status: unresolved.status,
      estimated_minutes: ESTIMATED_MINUTES,
      needs_docket_match: true,
    });
    return applyUserCookie(response, session);
  }

  // Resolve topic + agency for the row.
  const agency_id = (match.agency_id ?? "").trim() || "FTC";
  const source = (match.source ?? "").trim() || "regulations_gov";
  const topic_slug =
    body.topic_slug ??
    topicForDocket(match.docket_id, agency_id, parseTags(match.tags_json));
  const title = match.title?.trim() || `Analysis of ${match.docket_id}`;
  const expectedScale = Math.max(
    100,
    Number(match.comment_count_estimate ?? 1000),
  );

  // Insert the row.
  let created;
  try {
    created = await createAnalysisRequest({
      docket_id: match.docket_id,
      source,
      topic_id: (match.topic_id ?? topic_slug).trim() || topic_slug,
      agency_id,
      title,
      date_start: null,
      date_end: null,
      expected_scale: expectedScale,
      notes: `Queued from consumer search. Query: "${query}".`,
      requested_by: session.uid,
      query_text: query || null,
      topic_slug,
    });
  } catch (err) {
    console.error("queue-analysis insert failed:", err);
    const response = NextResponse.json(
      { error: "Failed to create analysis request." },
      { status: 500 },
    );
    return applyUserCookie(response, session);
  }

  // Best-effort: try to submit a real Databricks job. If unsupported in this
  // environment (no DATABRICKS_JOB_ID, ASTROTURF_ENABLE_JOB_SUBMIT off, etc.)
  // the row stays in 'draft' and the badge shows it as pending.
  let finalRequest = created;
  if (isJobSubmitEnabled()) {
    try {
      const { run_id } = await submitDocketJob(created);
      const updated = await updateAnalysisRequest(created.request_id, {
        status: "submitted",
        databricks_run_id: run_id,
      });
      if (updated) finalRequest = updated;
    } catch (err) {
      console.warn(
        "queue-analysis: Databricks job submit failed; row left in draft:",
        err instanceof Error ? err.message : err,
      );
      const updated = await updateAnalysisRequest(created.request_id, {
        status: "failed",
        error_message:
          err instanceof Error ? err.message : "Databricks submit failed.",
      });
      if (updated) finalRequest = updated;
    }
  }

  const response = NextResponse.json({
    request_id: finalRequest.request_id,
    docket_id: finalRequest.docket_id,
    docket_title: finalRequest.title,
    status: finalRequest.status,
    estimated_minutes: ESTIMATED_MINUTES,
  });
  return applyUserCookie(response, session);
}

async function createUnresolvedRequest(
  query: string,
  topicSlug: string | undefined,
  uid: string,
) {
  const agency = inferAgencyHint(query) ?? "FTC";
  const topic_slug = topicSlug ?? topicForDocket("UNRESOLVED", agency);
  const stableId = createHash("sha256")
    .update(`${uid}:${query.toLowerCase()}`)
    .digest("hex")
    .slice(0, 8);
  return createAnalysisRequest({
    docket_id: `UNRESOLVED-${stableId}`,
    source: "regulations_gov",
    topic_id: topic_slug,
    agency_id: agency,
    title: `Find a docket for: ${query}`,
    date_start: null,
    date_end: null,
    expected_scale: 1000,
    notes: `Queued from consumer search, but no docket was confidently resolved. Query: "${query}". Operator should map this request to a real docket_id before submission.`,
    requested_by: uid,
    query_text: query || null,
    topic_slug,
  });
}

async function lookupDocketById(docket_id: string): Promise<CatalogRow | null> {
  try {
    const rows = await pgQuery<CatalogRow>(
      `SELECT docket_id, title, source, agency_id, topic_id, summary, comment_count_estimate, tags_json
         FROM docket_catalog
        WHERE LOWER(docket_id) = LOWER($1)
        LIMIT 1`,
      [docket_id],
    );
    return rows[0] ?? null;
  } catch (err) {
    console.error("queue-analysis: lookupDocketById failed:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return null;
    throw err;
  }
}

async function searchCatalog(query: string): Promise<CatalogRow | null> {
  try {
    const searchQueries = await buildSearchQueries(query);
    const terms = unique(searchQueries.flatMap(tokenize)).slice(0, 12);
    if (terms.length === 0) return null;
    const exactPhrases = unique(searchQueries.map(normalizeText).filter(Boolean));
    const params = terms.map((term) => `%${term}%`);
    const matchClauses = terms.map(
      (_, i) =>
        `(title ILIKE $${i + 1} OR docket_id ILIKE $${i + 1} OR summary ILIKE $${i + 1} OR tags_json::text ILIKE $${i + 1})`,
    );
    const rows = await pgQuery<CatalogRow>(
      `SELECT docket_id, title, source, agency_id, topic_id, summary, comment_count_estimate, tags_json
         FROM docket_catalog
        WHERE (${matchClauses.join(" OR ")})
        ORDER BY priority_score DESC, comment_count_estimate DESC
        LIMIT 30`,
      params,
    );
    return chooseBestCatalogRow(query, rows, terms, exactPhrases);
  } catch (err) {
    console.error("queue-analysis: searchCatalog failed:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return null;
    throw err;
  }
}

async function searchRegulationsGov(query: string): Promise<CatalogRow | null> {
  const apiKey = (process.env.DATA_GOV_API_KEY ?? "").trim();
  if (!apiKey) return null;

  try {
    const searchQueries = await buildSearchQueries(query);
    const candidates: CatalogRow[] = [];
    for (const searchTerm of searchQueries.slice(0, 6)) {
      const params = new URLSearchParams({
        "filter[searchTerm]": searchTerm,
        sort: "-lastModifiedDate",
        "page[size]": "5",
        api_key: apiKey,
      });
      const res = await fetch(
        `https://api.regulations.gov/v4/dockets?${params.toString()}`,
        {
          headers: { Accept: "application/vnd.api+json" },
          signal: AbortSignal.timeout(10_000),
        },
      );
      if (!res.ok) continue;
      const body = (await res.json()) as {
        data?: Array<{
          id?: string;
          attributes?: {
            title?: string;
            agencyId?: string;
            commentCount?: number;
            docketType?: string;
          };
        }>;
      };
      for (const item of body.data ?? []) {
        if (!item.id) continue;
        const agency = item.attributes?.agencyId || inferAgencyFromDocket(item.id);
        candidates.push({
          docket_id: item.id,
          title: item.attributes?.title ?? item.id,
          source: "regulations_gov",
          agency_id: agency,
          topic_id: topicForDocket(item.id, agency),
          summary: null,
          comment_count_estimate: Number(item.attributes?.commentCount ?? 1000),
          tags_json: [],
        });
      }
    }
    const terms = unique(searchQueries.flatMap(tokenize)).slice(0, 12);
    const exactPhrases = unique(searchQueries.map(normalizeText).filter(Boolean));
    const best = chooseBestCatalogRow(query, dedupeRows(candidates), terms, exactPhrases);
    if (!best) return null;
    return best;
  } catch (err) {
    console.warn(
      "queue-analysis: regulations.gov fallback failed:",
      err instanceof Error ? err.message : err,
    );
    return null;
  }
}

function inferAgencyFromDocket(docketId: string): string {
  const first = docketId.split("-")[0]?.toUpperCase();
  return first || "FTC";
}

function chooseBestCatalogRow(
  rawQuery: string,
  rows: CatalogRow[],
  terms: string[],
  exactPhrases: string[],
): CatalogRow | null {
  let best: { row: CatalogRow; score: number } | null = null;
  for (const row of rows) {
    const score = scoreCatalogRow(rawQuery, row, terms, exactPhrases);
    if (!best || score > best.score) {
      best = { row, score };
    }
  }
  return best && best.score >= 10 ? best.row : null;
}

function scoreCatalogRow(
  rawQuery: string,
  row: CatalogRow,
  terms: string[],
  exactPhrases: string[],
): number {
  const title = normalizeText(row.title ?? "");
  const summary = normalizeText(row.summary ?? "");
  const tags = normalizeText(parseTags(row.tags_json).join(" "));
  const docket = normalizeText(row.docket_id);
  let score = 0;

  for (const phrase of exactPhrases) {
    if (!phrase) continue;
    if (title.includes(phrase)) score += 80;
    if (tags.includes(phrase)) score += 55;
    if (summary.includes(phrase)) score += 30;
  }

  const titleHits = terms.filter((term) => title.includes(term)).length;
  const tagHits = terms.filter((term) => tags.includes(term)).length;
  const summaryHits = terms.filter((term) => summary.includes(term)).length;
  const docketHits = terms.filter((term) => docket.includes(term)).length;
  score += titleHits * 18 + tagHits * 12 + summaryHits * 5 + docketHits * 4;
  if (terms.length > 0 && titleHits >= Math.min(2, terms.length)) score += 35;
  if (terms.length > 0 && titleHits + tagHits >= Math.min(2, terms.length)) score += 20;
  score += Math.min(8, Math.log10(Math.max(1, Number(row.comment_count_estimate ?? 0))) * 2);

  const agencyHint = inferAgencyHint(rawQuery);
  if (agencyHint && row.agency_id?.toUpperCase() === agencyHint) score += 25;
  return score;
}

async function buildSearchQueries(query: string): Promise<string[]> {
  const fallback = fallbackSearchQueries(query);
  const llmQueries = await llmSearchQueries(query);
  return unique([...fallback, ...llmQueries]).slice(0, 10);
}

function fallbackSearchQueries(query: string): string[] {
  const normalized = normalizeText(query);
  const terms = tokenize(query);
  const queries = [query, terms.join(" ")].filter(Boolean);
  const expansions: Array<[RegExp, string[]]> = [
    [/drug|prescription|medicine|pharma|pricing|price/, ["drug pricing", "prescription drug prices", "cms price transparency"]],
    [/student|loan|college|borrower/, ["student loans", "borrower defense", "education student loans"]],
    [/methane|carbon|emission|climate/, ["methane emissions", "greenhouse gas emissions", "epa methane"]],
    [/overtime|wage|worker|labor|salary/, ["overtime wages", "fair labor standards", "dol overtime"]],
    [/non\s*compete|compete|competition|workplace freedom/, ["non compete ban", "non-compete clause", "workplace freedom"]],
    [/net\s*neutral|broadband|internet/, ["net neutrality", "open internet", "broadband internet"]],
    [/payday|overdraft|credit|lending|bank/, ["payday lending", "consumer finance", "banking lending"]],
  ];
  for (const [pattern, values] of expansions) {
    if (pattern.test(normalized)) queries.push(...values);
  }
  return unique(queries);
}

async function llmSearchQueries(query: string): Promise<string[]> {
  const host = (process.env.DATABRICKS_HOST ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  const token = (process.env.DATABRICKS_TOKEN ?? "").trim();
  if (!host || !token) return [];

  try {
    const response = await fetch(
      `https://${host}/serving-endpoints/${FOUNDATION_MODEL_ENDPOINT}/invocations`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: [
            {
              role: "user",
              content: `Convert this user's public-policy search into 3 to 6 short regulations.gov docket search phrases. Include agency or rulemaking terms when useful. Return JSON only: {"queries":["..."]}\n\nUser search: ${JSON.stringify(query)}`,
            },
          ],
          max_tokens: 180,
          temperature: 0.2,
          response_format: { type: "json_object" },
        }),
        signal: AbortSignal.timeout(5_000),
      },
    );
    if (!response.ok) return [];
    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const raw = data.choices?.[0]?.message?.content?.trim();
    if (!raw) return [];
    const parsed = JSON.parse(extractJsonObject(raw)) as { queries?: unknown };
    return Array.isArray(parsed.queries)
      ? parsed.queries.filter((q): q is string => typeof q === "string")
      : [];
  } catch {
    return [];
  }
}

function tokenize(text: string): string[] {
  return normalizeText(text)
    .split(" ")
    .filter((term) => term.length > 2 && !STOPWORDS.has(term));
}

function normalizeText(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function inferAgencyHint(query: string): string | null {
  const text = normalizeText(query);
  if (/\bfcc\b|internet|broadband|neutrality/.test(text)) return "FCC";
  if (/\bepa\b|climate|methane|emission|water|pollution/.test(text)) return "EPA";
  if (/\bcms\b|health|medicare|medicaid|drug|hospital/.test(text)) return "CMS";
  if (/\bcfpb\b|payday|overdraft|credit|lending|bank/.test(text)) return "CFPB";
  if (/\bdol\b|overtime|wage|worker|labor/.test(text)) return "DOL";
  if (/\bed\b|education|student|school|college|loan/.test(text)) return "ED";
  if (/\bftc\b|non compete|competition|consumer protection/.test(text)) return "FTC";
  return null;
}

function dedupeRows(rows: CatalogRow[]): CatalogRow[] {
  const seen = new Set<string>();
  const out: CatalogRow[] = [];
  for (const row of rows) {
    const key = row.docket_id.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

function unique(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function extractJsonObject(text: string): string {
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) return fence[1].trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  return start >= 0 && end > start ? text.slice(start, end + 1) : text;
}

function parseTags(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[];
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? (parsed as string[]) : [];
    } catch {
      return [];
    }
  }
  return [];
}
