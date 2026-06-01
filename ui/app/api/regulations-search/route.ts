import { NextResponse } from "next/server";

// GET /api/regulations-search?q=...
//
// Server-side proxy to regulations.gov v4 dockets search. Returns the top 5
// dockets matching the query, ordered by lastModifiedDate DESC.
//
// Requires DATA_GOV_API_KEY in the environment. If missing, returns an empty
// result set (non-fatal: the queue-analysis flow falls back to docket_catalog).

export const revalidate = 0;

interface RegDocket {
  docket_id: string;
  title: string;
  agency_id: string;
  docket_type: string;
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

  const apiKey = (process.env.DATA_GOV_API_KEY ?? "").trim();
  if (!apiKey) {
    return NextResponse.json({ dockets: [], note: "DATA_GOV_API_KEY not configured" });
  }

  try {
    const params = new URLSearchParams({
      "filter[searchTerm]": q,
      "sort": "-lastModifiedDate",
      "page[size]": "5",
      "api_key": apiKey,
    });
    const res = await fetch(
      `https://api.regulations.gov/v4/dockets?${params.toString()}`,
      {
        headers: { Accept: "application/vnd.api+json" },
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!res.ok) {
      console.warn(`regulations.gov search failed: ${res.status}`);
      return NextResponse.json({ dockets: [] });
    }
    const body = await res.json();
    const data = body?.data ?? [];
    const dockets: RegDocket[] = data.map(
      (d: { id: string; attributes: Record<string, string> }) => ({
        docket_id: d.id ?? "",
        title: d.attributes?.title ?? "",
        agency_id: d.attributes?.agencyId ?? "",
        docket_type: d.attributes?.docketType ?? "",
      }),
    );
    return NextResponse.json({ dockets });
  } catch (err) {
    console.warn(
      "regulations.gov search error:",
      err instanceof Error ? err.message : err,
    );
    return NextResponse.json({ dockets: [] });
  }
}
