import { NextResponse } from "next/server";
import { getUserId } from "@/lib/user-session";
import { listAnalysisRequestsForUser } from "@/lib/analysis-store";
import { query as pgQuery } from "@/lib/db";

// GET /api/user-requests
//
// Reads the astroturf_uid cookie and returns the user's recent analysis
// requests. For completed requests, we JOIN to findings to get the slug
// of the largest finding for that docket so the badge can link directly.

export const revalidate = 0;

interface UserRequestItem {
  request_id: string;
  query_text: string | null;
  docket_id: string;
  title: string;
  status: string;
  created_at: string;
  finding_slug: string | null;
}

export async function GET() {
  const uid = await getUserId();
  if (!uid) {
    return NextResponse.json({ requests: [] });
  }

  const requests = await listAnalysisRequestsForUser(uid, 20);

  // For succeeded requests, look up the largest finding per docket.
  const succeeded = requests.filter((r) => r.status === "succeeded");
  const findingSlugs = new Map<string, string>();
  if (succeeded.length > 0) {
    try {
      const docketIds = [...new Set(succeeded.map((r) => r.docket_id))];
      const placeholders = docketIds.map((_, i) => `$${i + 1}`).join(", ");
      const rows = await pgQuery<{ docket_id: string; slug: string }>(
        `SELECT DISTINCT ON (docket_id) docket_id, slug
           FROM findings
          WHERE docket_id IN (${placeholders})
          ORDER BY docket_id, cluster_size DESC`,
        docketIds,
      );
      for (const r of rows) {
        findingSlugs.set(r.docket_id, r.slug);
      }
    } catch {
      // Non-fatal: badge works without finding links.
    }
  }

  const items: UserRequestItem[] = requests.map((r) => ({
    request_id: r.request_id,
    query_text: r.query_text,
    docket_id: r.docket_id,
    title: r.title,
    status: r.status,
    created_at: r.created_at,
    finding_slug: findingSlugs.get(r.docket_id) ?? null,
  }));

  return NextResponse.json({ requests: items });
}
