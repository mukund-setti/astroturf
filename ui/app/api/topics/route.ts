import { NextResponse } from "next/server";
import { TOPICS } from "@/lib/topics";

export const revalidate = 3600;

export async function GET() {
  return NextResponse.json(
    TOPICS.map((t) => ({ slug: t.slug, label: t.label })),
  );
}
