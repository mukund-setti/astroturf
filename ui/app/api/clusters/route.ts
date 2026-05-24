import { NextResponse } from "next/server";
import { getCatalog, getDocketId, query, toInt, toIso } from "@/lib/databricks";
import type { ClusterSummary } from "@/lib/types";

export const revalidate = 3600;

interface ClusterSummaryRow {
  cluster_id: string;
  cluster_size: unknown;
  similarity_threshold: unknown;
  embedding_model: string;
  representative_comment_id: string;
  rep_text_preview: string | null;
  rep_submitter_name: string | null;
  rep_posted_date: unknown;
  earliest_posted_date: unknown;
  latest_posted_date: unknown;
}

export async function GET() {
  try {
    const catalog = getCatalog();
    const docketId = getDocketId();

    const sql = `
      SELECT
        cluster_id,
        cluster_size,
        similarity_threshold,
        embedding_model,
        representative_comment_id,
        MAX(CASE WHEN is_representative THEN text_preview END)
          AS rep_text_preview,
        MAX(CASE WHEN is_representative THEN submitter_name END)
          AS rep_submitter_name,
        MAX(CASE WHEN is_representative THEN posted_date END)
          AS rep_posted_date,
        MIN(posted_date) AS earliest_posted_date,
        MAX(posted_date) AS latest_posted_date
      FROM ${catalog}.demo.cluster_review_export
      WHERE docket_id = :docket_id AND source = 'semantic'
      GROUP BY
        cluster_id,
        cluster_size,
        similarity_threshold,
        embedding_model,
        representative_comment_id
      ORDER BY cluster_size DESC, cluster_id ASC
    `;

    const rows = await query<ClusterSummaryRow>(sql, { docket_id: docketId });

    const payload: ClusterSummary[] = rows.map((r) => ({
      cluster_id: r.cluster_id,
      cluster_size: toInt(r.cluster_size),
      similarity_threshold: Number(r.similarity_threshold ?? 0),
      embedding_model: r.embedding_model,
      representative_comment_id: r.representative_comment_id,
      rep_text_preview: r.rep_text_preview,
      rep_submitter_name: r.rep_submitter_name,
      rep_posted_date: toIso(r.rep_posted_date),
      earliest_posted_date: toIso(r.earliest_posted_date),
      latest_posted_date: toIso(r.latest_posted_date),
    }));

    return NextResponse.json(payload);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
