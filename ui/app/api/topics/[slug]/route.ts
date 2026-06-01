import { NextResponse } from "next/server";
import { getTopicBySlug, topicSlugsForQuery } from "@/lib/topics";
import { listFindingsByTopic } from "@/lib/findings-store";

export const revalidate = 300;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const topic = getTopicBySlug(slug);
  if (!topic) {
    return NextResponse.json({ error: "Topic not found" }, { status: 404 });
  }
  try {
    const findings = await listFindingsByTopic(slug);
    return NextResponse.json({
      slug: topic.slug,
      label: topic.label,
      gathers: topicSlugsForQuery(slug),
      finding_count: findings.length,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
