import fs from "fs";
import path from "path";
import { query, isOfflineMode, getCatalog } from "./databricks";

export interface DiscoveredDocket {
  docket_id: string;
  source: "regulations_gov" | "ecfs";
  agency_id: string;
  topic_id: string;
  title: string;
  summary: string;
  status: "discovered" | "monitoring" | "queued" | "analyzing" | "analyzed" | "stale" | "failed";
  comment_count_estimate: number;
  last_comment_date: string | null;
  last_ingested_at: string | null;
  last_analyzed_at: string | null;
  freshness_label: string;
  priority_score: number;
  user_requested_count: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

const LOCAL_CATALOG_PATH = path.resolve(process.cwd(), "..", "data", "discovery", "docket_catalog.json");

function ensureCatalogDirectory(): void {
  try {
    const dir = path.dirname(LOCAL_CATALOG_PATH);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    if (!fs.existsSync(LOCAL_CATALOG_PATH)) {
      fs.writeFileSync(LOCAL_CATALOG_PATH, JSON.stringify([]), "utf8");
    }
  } catch (err) {
    console.error("Failed to initialize discovery catalog directory:", err);
  }
}

export async function listDiscoveredDockets(): Promise<DiscoveredDocket[]> {
  const offline = isOfflineMode();
  
  if (!offline) {
    // Production Mode: Query Databricks SQL Warehouse
    try {
      const catalog = getCatalog();
      const sql = `SELECT * FROM ${catalog}.discovery.docket_catalog ORDER BY priority_score DESC`;
      const rows = await query<Record<string, unknown>>(sql);
      return rows.map((r) => ({
        docket_id: r.docket_id as string,
        source: r.source as "regulations_gov" | "ecfs",
        agency_id: r.agency_id as string,
        topic_id: r.topic_id as string,
        title: r.title as string,
        summary: r.summary as string,
        status: r.status as DiscoveredDocket["status"],
        comment_count_estimate: Number(r.comment_count_estimate ?? 0),
        last_comment_date: r.last_comment_date ? new Date(r.last_comment_date as string).toISOString() : null,
        last_ingested_at: r.last_ingested_at ? new Date(r.last_ingested_at as string).toISOString() : null,
        last_analyzed_at: r.last_analyzed_at ? new Date(r.last_analyzed_at as string).toISOString() : null,
        freshness_label: (r.freshness_label as string) ?? "Active",
        priority_score: Number(r.priority_score ?? 0.0),
        user_requested_count: Number(r.user_requested_count ?? 0),
        tags: r.tags ? (r.tags as string).split(",").map((s: string) => s.trim()) : [],
        created_at: r.created_at ? new Date(r.created_at as string).toISOString() : new Date().toISOString(),
        updated_at: r.updated_at ? new Date(r.updated_at as string).toISOString() : new Date().toISOString(),
      }));
    } catch (err) {
      console.warn("Failed to query docket catalog from Databricks SQL. Falling back to local catalog JSON.", err);
    }
  }

  // Local Dev Fallback: Read local JSON file
  ensureCatalogDirectory();
  try {
    if (!fs.existsSync(LOCAL_CATALOG_PATH)) {
      return [];
    }
    const raw = fs.readFileSync(LOCAL_CATALOG_PATH, "utf8");
    if (!raw.trim()) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map((item: Record<string, unknown>) => ({
      ...item,
      tags: typeof item.tags === "string" ? (item.tags as string).split(",").map((s: string) => s.trim()) : (item.tags as string[]) || [],
    })) as DiscoveredDocket[];
  } catch (err) {
    console.error("Failed to read discovered docket catalog JSON store:", err);
    return [];
  }
}

export async function getDiscoveredDocket(docketId: string): Promise<DiscoveredDocket | null> {
  const list = await listDiscoveredDockets();
  return list.find((d) => d.docket_id.toLowerCase() === docketId.toLowerCase()) || null;
}

export async function registerDiscoveredDocket(docket: Partial<DiscoveredDocket>): Promise<DiscoveredDocket> {
  ensureCatalogDirectory();
  const list = await listDiscoveredDockets();
  const index = list.findIndex((d) => d.docket_id === docket.docket_id);
  
  const now = new Date().toISOString();
  
  const newDocket: DiscoveredDocket = {
    docket_id: docket.docket_id!,
    source: docket.source || "regulations_gov",
    agency_id: docket.agency_id || "FTC",
    topic_id: docket.topic_id || "unclassified",
    title: docket.title || "Short Title",
    summary: docket.summary || "",
    status: docket.status || "discovered",
    comment_count_estimate: docket.comment_count_estimate || 1000,
    last_comment_date: docket.last_comment_date || null,
    last_ingested_at: docket.last_ingested_at || null,
    last_analyzed_at: docket.last_analyzed_at || null,
    freshness_label: docket.freshness_label || "Active",
    priority_score: docket.priority_score || 0.0,
    user_requested_count: docket.user_requested_count || 0,
    tags: docket.tags || [],
    created_at: index !== -1 ? list[index].created_at : now,
    updated_at: now,
  };

  if (index !== -1) {
    list[index] = newDocket;
  } else {
    list.push(newDocket);
  }

  // Save to local JSON
  fs.writeFileSync(
    LOCAL_CATALOG_PATH,
    JSON.stringify(
      list.map((d) => ({ ...d, tags: d.tags.join(", ") })),
      null,
      2
    ),
    "utf8"
  );

  return newDocket;
}

export async function incrementUserRequestCount(docketId: string): Promise<DiscoveredDocket | null> {
  const docket = await getDiscoveredDocket(docketId);
  if (!docket) return null;

  docket.user_requested_count += 1;
  
  // Recalculate priority score locally
  const scaleScore = 25 * Math.min(1.0, docket.comment_count_estimate / 50000);
  const interestScore = 30 * Math.min(1.0, docket.user_requested_count / 10) + 15; // Watched bonus
  const recencyScore = 15; // default recency
  const agencyScore = ["FCC", "EPA", "CFPB", "FTC"].includes(docket.agency_id) ? 5 : 0;
  docket.priority_score = Math.min(100.0, Math.round(scaleScore + interestScore + recencyScore + agencyScore));

  return await registerDiscoveredDocket(docket);
}
