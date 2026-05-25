import { NextResponse } from "next/server";
import { getCatalog, query, toInt } from "@/lib/databricks";
import { resolveLandingDocketId } from "@/lib/analysis-store";
import type { StatsPayload } from "@/lib/types";

export const revalidate = 3600;

interface StatsRow {
  total_comments: unknown;
  cluster_count: unknown;
  comments_in_clusters: unknown;
  largest_cluster_size: unknown;
}

export async function GET() {
  try {
    const catalog = getCatalog();
    const docketId = await resolveLandingDocketId();

    const sql = `
      SELECT
        (SELECT COUNT(*)
           FROM ${catalog}.silver.parsed_comments
           WHERE docket_id = :docket_id)
          AS total_comments,
        (SELECT COUNT(DISTINCT cluster_id)
           FROM ${catalog}.demo.cluster_review_export
           WHERE docket_id = :docket_id AND source = 'semantic')
          AS cluster_count,
        (SELECT COUNT(DISTINCT comment_id)
           FROM ${catalog}.demo.cluster_review_export
           WHERE docket_id = :docket_id AND source = 'semantic')
          AS comments_in_clusters,
        (SELECT MAX(cluster_size)
           FROM ${catalog}.demo.cluster_review_export
           WHERE docket_id = :docket_id AND source = 'semantic')
          AS largest_cluster_size
    `;

    const rows = await query<StatsRow>(sql, { docket_id: docketId });
    const row = rows[0] ?? ({} as StatsRow);

    const payload: StatsPayload = {
      total_comments: toInt(row.total_comments),
      cluster_count: toInt(row.cluster_count),
      comments_in_clusters: toInt(row.comments_in_clusters),
      largest_cluster_size: toInt(row.largest_cluster_size),
      docket_id: docketId,
    };

    return NextResponse.json(payload);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
