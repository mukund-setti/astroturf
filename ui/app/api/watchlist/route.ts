import { NextResponse } from "next/server";
import { listWatchItems, addWatchItem, removeWatchItem } from "@/lib/watchlist-store";

export async function GET() {
  try {
    const items = await listWatchItems();
    return NextResponse.json(items);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { kind, value, label, notes } = body;

    if (!kind || !value || !label) {
      return NextResponse.json(
        { error: "Missing required fields: kind, value, label" },
        { status: 400 }
      );
    }

    const newItem = await addWatchItem(kind, value, label, notes);
    return NextResponse.json(newItem);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
