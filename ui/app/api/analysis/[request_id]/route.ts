import { NextResponse } from "next/server";
import { getAnalysisRequest, updateAnalysisRequest } from "@/lib/analysis-store";

interface Context {
  params: Promise<{
    request_id: string;
  }>;
}

export async function GET(request: Request, { params }: Context) {
  try {
    const { request_id } = await params;
    const req = await getAnalysisRequest(request_id);
    if (!req) {
      return NextResponse.json({ error: `Analysis request with ID ${request_id} not found.` }, { status: 404 });
    }
    return NextResponse.json(req);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PATCH(request: Request, { params }: Context) {
  try {
    const { request_id } = await params;
    const body = await request.json();
    const req = await getAnalysisRequest(request_id);
    if (!req) {
      return NextResponse.json({ error: `Analysis request with ID ${request_id} not found.` }, { status: 404 });
    }

    const updated = await updateAnalysisRequest(request_id, body);
    return NextResponse.json(updated);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
