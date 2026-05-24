import { NextResponse } from "next/server";
import { removeWatchItem, markChecked } from "@/lib/watchlist-store";

interface RouteParams {
  params: Promise<{
    id: string;
  }>;
}

export async function DELETE(request: Request, { params }: RouteParams) {
  try {
    const { id } = await params;
    const success = await removeWatchItem(id);
    if (!success) {
      return NextResponse.json({ error: "Watch item not found" }, { status: 404 });
    }
    return NextResponse.json({ success: true });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export async function PATCH(request: Request, { params }: RouteParams) {
  try {
    const { id } = await params;
    const updated = await markChecked(id);
    if (!updated) {
      return NextResponse.json({ error: "Watch item not found" }, { status: 404 });
    }
    return NextResponse.json(updated);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
