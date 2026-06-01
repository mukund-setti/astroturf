import { NextResponse } from "next/server";
import { getFindingBySlug } from "@/lib/findings-store";

export const revalidate = 300;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  try {
    const finding = await getFindingBySlug(slug);
    if (!finding) {
      return NextResponse.json({ error: "Finding not found" }, { status: 404 });
    }
    return NextResponse.json(finding);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
