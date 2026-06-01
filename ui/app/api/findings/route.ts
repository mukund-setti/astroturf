import { NextResponse } from "next/server";
import { listFindingsByTopic } from "@/lib/findings-store";

export const revalidate = 300;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const topic = url.searchParams.get("topic");
  if (!topic) {
    return NextResponse.json(
      { error: "Missing required query parameter: topic" },
      { status: 400 },
    );
  }
  try {
    const findings = await listFindingsByTopic(topic);
    return NextResponse.json(findings);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
