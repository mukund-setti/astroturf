import { NextResponse } from "next/server";
import { getFeaturedFindings } from "@/lib/findings-store";

export const revalidate = 300;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const limitRaw = url.searchParams.get("limit");
  const limit = limitRaw ? Math.min(Math.max(parseInt(limitRaw, 10) || 4, 1), 24) : 4;
  try {
    const findings = await getFeaturedFindings(limit);
    return NextResponse.json(findings);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
