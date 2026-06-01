import { NextResponse } from "next/server";
import { getDiscoveredDocket } from "@/lib/docket-catalog";

/**
 * POST /api/docket-lookup
 *
 * Looks up a docket ID in the catalog (Supabase Postgres) and returns
 * its metadata for form auto-fill. Returns { found: false } when the
 * docket is not in the catalog - callers should degrade gracefully.
 */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { docketId } = body;

    if (!docketId || !docketId.trim()) {
      return NextResponse.json({ found: false });
    }

    const docket = await getDiscoveredDocket(docketId.trim());
    if (!docket) {
      return NextResponse.json({ found: false });
    }

    return NextResponse.json({
      found: true,
      docketId: docket.docket_id,
      source: docket.source,
      topicId: docket.topic_id,
      agencyId: docket.agency_id,
      title: docket.title,
      expectedScale: String(docket.comment_count_estimate || ""),
      summary: docket.summary,
    });
  } catch (err) {
    console.error("Docket lookup failed:", err);
    return NextResponse.json({ found: false });
  }
}
