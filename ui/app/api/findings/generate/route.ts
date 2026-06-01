import { NextResponse } from "next/server";
import { getCatalog, query as queryDb } from "@/lib/databricks";
import {
  generateFindingFromCluster,
  getFindingByClusterId,
} from "@/lib/findings-store";
import { topicForDocket } from "@/lib/topics";

// Admin-gated batch generation. POST { docket_id, agency_id?, force?: boolean }.
// Iterates clusters in cluster_review_export for that docket (largest first),
// skips clusters that already have a finding unless force=true, and inserts
// one finding per cluster via Claude. Returns a summary.

interface GenerateRequestBody {
  docket_id?: string;
  agency_id?: string;
  force?: boolean;
  limit?: number;
}

interface ClusterListRow {
  cluster_id: string;
  cluster_size: number;
}

function checkAuth(request: Request): NextResponse | null {
  const adminToken = (process.env.ADMIN_TOKEN ?? "").trim();
  if (!adminToken) {
    return NextResponse.json(
      { error: "ADMIN_TOKEN is not configured on the server." },
      { status: 503 },
    );
  }
  const provided = request.headers.get("x-admin-token") ?? "";
  if (provided !== adminToken) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  return null;
}

export async function POST(request: Request) {
  const authFail = checkAuth(request);
  if (authFail) return authFail;

  let body: GenerateRequestBody;
  try {
    body = (await request.json()) as GenerateRequestBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const docket_id = body.docket_id?.trim();
  if (!docket_id) {
    return NextResponse.json(
      { error: "Missing required field: docket_id" },
      { status: 400 },
    );
  }
  const force = body.force === true;
  const limit = typeof body.limit === "number" ? body.limit : Number.POSITIVE_INFINITY;
  const agency_id = body.agency_id?.trim();
  const topic_slug = topicForDocket(docket_id, agency_id);

  const catalog = getCatalog();
  const sql = `
    SELECT cluster_id, MAX(cluster_size) AS cluster_size
    FROM ${catalog}.demo.cluster_review_export
    WHERE docket_id = :docket_id
    GROUP BY cluster_id
    ORDER BY cluster_size DESC
  `;
  const rows = await queryDb<ClusterListRow>(sql, { docket_id });

  const results: Array<{
    cluster_id: string;
    status: "generated" | "skipped" | "error";
    slug?: string;
    error?: string;
  }> = [];

  let count = 0;
  for (const row of rows) {
    if (count >= limit) break;
    const existing = await getFindingByClusterId(row.cluster_id);
    if (existing && !force) {
      results.push({
        cluster_id: row.cluster_id,
        status: "skipped",
        slug: existing.slug,
      });
      continue;
    }
    try {
      const finding = await generateFindingFromCluster({
        cluster_id: row.cluster_id,
        docket_id,
        agency_id,
        topic_slug,
      });
      if (!finding) {
        results.push({
          cluster_id: row.cluster_id,
          status: "skipped",
        });
        continue;
      }
      results.push({
        cluster_id: row.cluster_id,
        status: "generated",
        slug: finding.slug,
      });
      count += 1;
      // Small gap to keep within Anthropic rate limits for the backfill.
      await sleep(200);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      results.push({
        cluster_id: row.cluster_id,
        status: "error",
        error: message,
      });
    }
  }

  const generated = results.filter((r) => r.status === "generated").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  const errored = results.filter((r) => r.status === "error").length;

  return NextResponse.json({
    docket_id,
    topic_slug,
    total_clusters: rows.length,
    generated,
    skipped,
    errored,
    results,
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
