import { NextResponse } from "next/server";
import { TOPICS } from "@/lib/topics";
import { query as pgQuery, isConnectionError, sanitizeDatabaseError } from "@/lib/db";
import { listAvailableTopicSlugs } from "@/lib/findings-store";

export const revalidate = 0;

const MAX_RESULTS = 12;
const LOCAL_CANDIDATE_LIMIT = 8;
const FOUNDATION_MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct";

type SuggestionType = "topic" | "finding" | "docket" | "analysis";

interface Suggestion {
  type: SuggestionType;
  label: string;
  sublabel?: string;
  href: string;
  cluster_size?: number;
}

interface FindingRow {
  slug: string;
  headline: string;
  cluster_size: number;
}

interface DocketRow {
  docket_id: string;
  title: string;
  priority_score: number;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const q = (url.searchParams.get("q") ?? "").trim();

  // Topics show only when they have *something* to show: either a finding
  // or a docket in docket_catalog. /topic/[slug] renders dockets when there
  // are no findings, so either case lands the user on real content rather
  // than a generic CTA.
  const populated = await listAvailableTopicSlugs();

  if (!q) {
    return NextResponse.json({
      results: TOPICS.filter((t) => populated.has(t.slug)).map<Suggestion>(
        (t) => ({
          type: "topic",
          label: t.label,
          href: `/topic/${t.slug}`,
        }),
      ),
    });
  }

  const qLower = q.toLowerCase();
  const localResults = [
    ...matchTopics(qLower, populated).slice(0, LOCAL_CANDIDATE_LIMIT),
    ...(await matchFindings(q)),
    ...(await matchDockets(q)),
  ];

  const ranked = await rankWithLlm(q, localResults);
  const results = ensureAnalysisOption(ranked.length > 0 ? ranked : localResults, q);
  return NextResponse.json({ results: results.slice(0, MAX_RESULTS) });
}

function matchTopics(qLower: string, populated: Set<string>): Suggestion[] {
  const normalized = normalizeForSearch(qLower);
  return TOPICS.filter((t) => {
    if (!populated.has(t.slug)) return false;
    const haystack = normalizeForSearch(
      [t.label, t.slug, ...t.keywords].join(" "),
    );
    return haystack.includes(normalized);
  }).map<Suggestion>((t) => ({
    type: "topic",
    label: t.label,
    href: `/topic/${t.slug}`,
  }));
}

async function matchFindings(q: string): Promise<Suggestion[]> {
  try {
    const tokens = tokenize(q).slice(0, 4);
    if (tokens.length === 0) return [];
    const clauses = tokens.map((_, i) => `headline ILIKE $${i + 1}`);
    const params = tokens.map((t) => `%${t}%`);
    const rows = await pgQuery<FindingRow>(
      `SELECT slug, headline, cluster_size
         FROM findings
        WHERE ${clauses.join(" OR ")}
        ORDER BY cluster_size DESC
        LIMIT $${params.length + 1}`,
      [...params, LOCAL_CANDIDATE_LIMIT],
    );
    return rows.map<Suggestion>((r) => ({
      type: "finding",
      label: r.headline,
      href: `/finding/${r.slug}`,
      cluster_size: Number(r.cluster_size),
    }));
  } catch (err) {
    console.error("suggest: matchFindings failed:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return [];
    return [];
  }
}

async function matchDockets(q: string): Promise<Suggestion[]> {
  try {
    const tokens = tokenize(q).slice(0, 4);
    if (tokens.length === 0) return [];
    const clauses = tokens.map(
      (_, i) =>
        `(title ILIKE $${i + 1} OR docket_id ILIKE $${i + 1} OR summary ILIKE $${i + 1} OR tags_json::text ILIKE $${i + 1})`,
    );
    const params = tokens.map((t) => `%${t}%`);
    const rows = await pgQuery<DocketRow>(
      `SELECT docket_id, title, priority_score
         FROM docket_catalog
        WHERE ${clauses.join(" OR ")}
        ORDER BY priority_score DESC
        LIMIT $${params.length + 1}`,
      [...params, LOCAL_CANDIDATE_LIMIT],
    );
    return rows.map<Suggestion>((r) => ({
      type: "docket",
      label: r.title || r.docket_id,
      sublabel: r.docket_id,
      href: `/legacy/dockets/${encodeURIComponent(r.docket_id)}`,
    }));
  } catch (err) {
    console.error("suggest: matchDockets failed:", sanitizeDatabaseError(err));
    if (isConnectionError(err)) return [];
    return [];
  }
}

async function rankWithLlm(query: string, candidates: Suggestion[]): Promise<Suggestion[]> {
  const host = (process.env.DATABRICKS_HOST ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  const token = (process.env.DATABRICKS_TOKEN ?? "").trim();
  if (!host || !token) return candidates;

  const candidatePayload = candidates.map((candidate, index) => ({
    index,
    type: candidate.type,
    label: candidate.label,
    sublabel: candidate.sublabel ?? null,
  }));
  const prompt = `You rank search suggestions for Astroturf, a public-rulemaking analysis tool.

User typed: ${JSON.stringify(query)}

Available suggestions:
${JSON.stringify(candidatePayload, null, 2)}

Choose the most relevant suggestions for the user's intent. Prefer policy meaning over literal substring matches. If the user appears to be asking for a policy area that is not clearly covered by the suggestions, include an analysis option by returning the string "analysis".

Return JSON only: {"order":[0,2,"analysis",1]}. Use at most 11 candidate indexes plus "analysis".`;

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
          messages: [{ role: "user", content: prompt }],
          max_tokens: 200,
          temperature: 0.1,
          response_format: { type: "json_object" },
        }),
      },
    );
    if (!response.ok) return candidates;
    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const raw = data.choices?.[0]?.message?.content?.trim();
    if (!raw) return candidates;
    const parsed = JSON.parse(extractJsonObject(raw)) as {
      order?: Array<number | string>;
    };
    if (!Array.isArray(parsed.order)) return candidates;
    const ordered: Suggestion[] = [];
    for (const item of parsed.order) {
      if (item === "analysis") {
        ordered.push(analysisSuggestion(query));
      } else if (typeof item === "number" && candidates[item]) {
        ordered.push(candidates[item]);
      }
    }
    return ordered.length > 0 ? dedupeSuggestions(ordered) : candidates;
  } catch {
    return candidates;
  }
}

function ensureAnalysisOption(results: Suggestion[], query: string): Suggestion[] {
  const deduped = dedupeSuggestions(results);
  if (!deduped.some((r) => r.type === "analysis")) {
    deduped.push(analysisSuggestion(query));
  }
  return deduped;
}

function analysisSuggestion(query: string): Suggestion {
  return {
    type: "analysis",
    label: `Analyze "${query}"`,
    sublabel: "Queue a new docket search",
    href: `/explore?q=${encodeURIComponent(query)}&queue=1`,
  };
}

function dedupeSuggestions(results: Suggestion[]): Suggestion[] {
  const seen = new Set<string>();
  const out: Suggestion[] = [];
  for (const result of results) {
    const key = `${result.type}:${result.href}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(result);
  }
  return out;
}

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 1);
}

function normalizeForSearch(text: string): string {
  return tokenize(text).join(" ");
}

function extractJsonObject(text: string): string {
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) return fence[1].trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  return start >= 0 && end > start ? text.slice(start, end + 1) : text;
}
