import fs from "fs";
import path from "path";

export interface AnalysisRequest {
  request_id: string;
  docket_id: string;
  source: string;
  topic_id: string;
  agency_id: string;
  title: string;
  date_start: string | null;
  date_end: string | null;
  expected_scale: number;
  notes: string;
  status: "draft" | "submitted" | "running" | "succeeded" | "failed" | "canceled";
  databricks_run_id: string | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  result_url: string | null;
}

const DATA_DIR = path.resolve(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "analysis-requests.json");

function ensureStoreExists(): void {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(STORE_PATH)) {
      fs.writeFileSync(STORE_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize local analysis store directory or file:", err);
  }
}

export async function listAnalysisRequests(): Promise<AnalysisRequest[]> {
  ensureStoreExists();
  try {
    if (!fs.existsSync(STORE_PATH)) {
      return [];
    }
    const raw = fs.readFileSync(STORE_PATH, "utf8");
    if (!raw.trim()) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      console.warn("Analysis request store is not an array, resetting to empty.");
      return [];
    }
    return parsed;
  } catch (err) {
    console.error("Failed to read analysis requests JSON store. Returning empty list.", err);
    return [];
  }
}

export async function getAnalysisRequest(id: string): Promise<AnalysisRequest | null> {
  const list = await listAnalysisRequests();
  return list.find((req) => req.request_id === id) || null;
}

export async function createAnalysisRequest(
  input: Omit<
    AnalysisRequest,
    "request_id" | "status" | "databricks_run_id" | "created_at" | "updated_at" | "error_message" | "result_url"
  >
): Promise<AnalysisRequest> {
  ensureStoreExists();
  const list = await listAnalysisRequests();
  
  const now = new Date().toISOString();
  const newRequest: AnalysisRequest = {
    ...input,
    request_id: `req_${Math.random().toString(36).substring(2, 11)}`,
    status: "draft",
    databricks_run_id: null,
    created_at: now,
    updated_at: now,
    error_message: null,
    result_url: null,
  };

  list.push(newRequest);
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return newRequest;
}

export async function updateAnalysisRequest(
  id: string,
  patch: Partial<AnalysisRequest>
): Promise<AnalysisRequest | null> {
  ensureStoreExists();
  const list = await listAnalysisRequests();
  const index = list.findIndex((req) => req.request_id === id);
  if (index === -1) {
    return null;
  }

  const updated = {
    ...list[index],
    ...patch,
    updated_at: new Date().toISOString(),
  };

  list[index] = updated;
  fs.writeFileSync(STORE_PATH, JSON.stringify(list, null, 2), "utf8");
  return updated;
}
