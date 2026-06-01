import { NextResponse } from "next/server";
import { TOPICS, type Topic } from "@/lib/topics";

// Free-text -> topic match. Step 10 will swap in Databricks BGE embeddings
// for the primary scoring path; this stub uses keyword overlap so the route
// is usable end-to-end now. The redirect threshold is exposed so the home
// page form can avoid a slow round-trip when the match is obviously strong.

const EXPLORE_REDIRECT_THRESHOLD = 0.7;
export const revalidate = 300;

interface ScoredTopic {
  slug: string;
  label: string;
  score: number;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const q = (url.searchParams.get("q") ?? "").trim();
  if (!q) {
    return NextResponse.json(
      { error: "Missing required query parameter: q" },
      { status: 400 },
    );
  }

  const scored = scoreTopicsKeyword(q);
  const top = scored[0];
  const shouldRedirect = top.score >= EXPLORE_REDIRECT_THRESHOLD;

  return NextResponse.json({
    query: q,
    match: top,
    candidates: scored,
    threshold: EXPLORE_REDIRECT_THRESHOLD,
    should_redirect: shouldRedirect,
    redirect_url: shouldRedirect ? `/topic/${top.slug}` : null,
    algorithm: "keyword_overlap",
  });
}

function scoreTopicsKeyword(q: string): ScoredTopic[] {
  const tokens = tokenize(q);
  if (tokens.length === 0) {
    return TOPICS.map((t) => ({ slug: t.slug, label: t.label, score: 0 }));
  }
  const scored: ScoredTopic[] = TOPICS.map((topic) => ({
    slug: topic.slug,
    label: topic.label,
    score: scoreOne(topic, tokens),
  }));
  scored.sort((a, b) => b.score - a.score);
  return scored;
}

function scoreOne(topic: Topic, tokens: string[]): number {
  const haystack = new Set<string>();
  for (const word of tokenize(topic.label)) haystack.add(word);
  for (const kw of topic.keywords) for (const word of tokenize(kw)) haystack.add(word);
  let hits = 0;
  for (const t of tokens) if (haystack.has(t)) hits += 1;
  // Normalize by query length so 1-word queries can still cross the
  // redirect threshold when they're an exact keyword match.
  return tokens.length === 0 ? 0 : hits / tokens.length;
}

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 1);
}
