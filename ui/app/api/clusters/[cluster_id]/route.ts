import { NextResponse } from "next/server";
import { getCatalog, query, toInt, toIso } from "@/lib/databricks";
import type { ClusterDetailPayload, ClusterRow, Source } from "@/lib/types";

export const revalidate = 3600;

interface RawClusterRow {
  cluster_id: string;
  cluster_size: unknown;
  similarity_threshold: unknown;
  embedding_model: string;
  representative_comment_id: string;
  comment_id: string;
  is_representative: boolean;
  text_source: string | null;
  text_preview: string | null;
  submitter_name: string | null;
  posted_date: unknown;
  source: string;
  exported_at: unknown;
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ cluster_id: string }> },
) {
  try {
    const { cluster_id } = await params;
    const catalog = getCatalog();

    const sql = `
      SELECT
        cluster_id,
        cluster_size,
        similarity_threshold,
        embedding_model,
        representative_comment_id,
        comment_id,
        is_representative,
        text_source,
        text_preview,
        submitter_name,
        posted_date,
        source,
        exported_at
      FROM ${catalog}.demo.cluster_review_export
      WHERE cluster_id = :cluster_id
      ORDER BY is_representative DESC, posted_date ASC
    `;

    const rows = await query<RawClusterRow>(sql, { cluster_id });

    const mapped: ClusterRow[] = rows.map((r) => ({
      cluster_id: r.cluster_id,
      cluster_size: toInt(r.cluster_size),
      similarity_threshold: Number(r.similarity_threshold ?? 0),
      embedding_model: r.embedding_model,
      representative_comment_id: r.representative_comment_id,
      comment_id: r.comment_id,
      is_representative: Boolean(r.is_representative),
      text_source: r.text_source,
      text_preview: r.text_preview,
      submitter_name: r.submitter_name,
      posted_date: toIso(r.posted_date),
      source: (r.source as Source) ?? "semantic",
      exported_at: toIso(r.exported_at),
    }));

    if (mapped.length === 0) {
      return NextResponse.json({ error: "Cluster not found" }, { status: 404 });
    }

    const payload: ClusterDetailPayload = {
      cluster_id,
      rows: mapped,
    };

    return NextResponse.json(payload);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
