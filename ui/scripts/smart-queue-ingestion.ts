import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function loadEnvLocal() {
  const path = resolve(process.cwd(), ".env.local");
  if (!existsSync(path)) return;
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadEnvLocal();

interface Candidate {
  docket_id: string;
  source: "regulations_gov" | "ecfs";
  agency_id: string;
  topic_id: string;
  topic_slug: string;
  title: string;
  expected_scale: number;
  query_text: string;
  notes: string;
}

const CANDIDATES: Candidate[] = [
  {
    docket_id: "FTC-2023-0007",
    source: "regulations_gov",
    agency_id: "FTC",
    topic_id: "labor",
    topic_slug: "labor",
    title: "Non-Compete Clause Ban and Workplace Freedom Rule",
    expected_scale: 10000,
    query_text: "non-compete ban",
    notes: "High-volume FTC labor/competition docket; useful non-FCC home-page diversity.",
  },
  {
    docket_id: "EPA-HQ-OAR-2021-0317",
    source: "regulations_gov",
    agency_id: "EPA",
    topic_id: "climate",
    topic_slug: "climate",
    title: "Oil and Gas Sector Methane Standards",
    expected_scale: 6000,
    query_text: "methane emissions",
    notes: "Climate/EPA methane rule with known prior sample coverage.",
  },
  {
    docket_id: "CMS-2019-0193",
    source: "regulations_gov",
    agency_id: "CMS",
    topic_id: "health-care",
    topic_slug: "health-care",
    title: "Hospital Price Transparency",
    expected_scale: 5000,
    query_text: "hospital price transparency",
    notes: "Health-care pricing topic; good consumer-facing contrast to telecom and climate.",
  },
  {
    docket_id: "EPA-HQ-OW-2021-0602",
    source: "regulations_gov",
    agency_id: "EPA",
    topic_id: "environment",
    topic_slug: "environment",
    title: "Waters of the United States",
    expected_scale: 5000,
    query_text: "clean water wetlands",
    notes: "Environment/water rule to diversify beyond air/climate.",
  },
  {
    docket_id: "DOL-2010-0050",
    source: "regulations_gov",
    agency_id: "DOL",
    topic_id: "labor",
    topic_slug: "labor",
    title: "Fiduciary Investment Advice Rule",
    expected_scale: 5000,
    query_text: "retirement fiduciary rule",
    notes: "Labor/finance rule, useful for economy topic without duplicating CFPB payday.",
  },
  {
    docket_id: "CFPB-2018-0035",
    source: "regulations_gov",
    agency_id: "CFPB",
    topic_id: "banking-and-lending",
    topic_slug: "banking-and-lending",
    title: "Overdraft Programs and Fees",
    expected_scale: 5000,
    query_text: "overdraft fees",
    notes: "Banking/lending topic distinct from payday lending.",
  },
  {
    docket_id: "14-28",
    source: "ecfs",
    agency_id: "FCC",
    topic_id: "tech-regulation",
    topic_slug: "tech-regulation",
    title: "Protecting and Promoting the Open Internet",
    expected_scale: 5000,
    query_text: "2014 open internet net neutrality",
    notes: "One older FCC control case, capped so net neutrality does not dominate.",
  },
];

async function main() {
  const dryRun = process.argv.includes("--dry-run");
  const submit = process.argv.includes("--submit");
  const limitArg = process.argv.find((arg) => arg.startsWith("--limit="));
  const limit = limitArg ? Number(limitArg.split("=")[1]) : CANDIDATES.length;
  const selected = CANDIDATES.slice(0, Number.isFinite(limit) ? limit : CANDIDATES.length);

  const { createAnalysisRequest, updateAnalysisRequest } = await import("../lib/analysis-store");
  const { submitDocketJob } = await import("../lib/databricks-jobs");
  const { query } = await import("../lib/db");

  const existing = await query<{
    docket_id: string;
    status: string;
    request_id: string;
    databricks_run_id: string | null;
  }>(
    `SELECT docket_id, status, request_id, databricks_run_id
       FROM analysis_requests
      WHERE docket_id = ANY($1)
      ORDER BY created_at DESC`,
    [selected.map((c) => c.docket_id)],
  );
  const activeOrDone = new Map<string, (typeof existing)[number]>();
  for (const row of existing) {
    if (["draft", "submitted", "running", "succeeded"].includes(row.status)) {
      activeOrDone.set(row.docket_id, row);
    }
  }

  const queued: Array<{ docket_id: string; request_id: string; status: string; run_id?: string }> = [];
  const skipped: Array<{ docket_id: string; reason: string }> = [];

  for (const candidate of selected) {
    const existingRow = activeOrDone.get(candidate.docket_id);
    if (existingRow) {
      skipped.push({
        docket_id: candidate.docket_id,
        reason: `${existingRow.status} (${existingRow.request_id})`,
      });
      continue;
    }
    if (dryRun) {
      queued.push({
        docket_id: candidate.docket_id,
        request_id: "dry-run",
        status: submit ? "would-submit" : "would-draft",
      });
      continue;
    }

    const request = await createAnalysisRequest({
      docket_id: candidate.docket_id,
      source: candidate.source,
      topic_id: candidate.topic_id,
      agency_id: candidate.agency_id,
      title: candidate.title,
      date_start: null,
      date_end: null,
      expected_scale: candidate.expected_scale,
      notes: `Smart batch ingestion. ${candidate.notes}`,
      requested_by: "system:smart-queue",
      query_text: candidate.query_text,
      topic_slug: candidate.topic_slug,
    });

    if (!submit) {
      queued.push({
        docket_id: candidate.docket_id,
        request_id: request.request_id,
        status: request.status,
      });
      continue;
    }

    try {
      const { run_id } = await submitDocketJob(request);
      const updated = await updateAnalysisRequest(request.request_id, {
        status: "submitted",
        databricks_run_id: run_id,
      });
      queued.push({
        docket_id: candidate.docket_id,
        request_id: request.request_id,
        status: updated?.status ?? "submitted",
        run_id,
      });
    } catch (err) {
      await updateAnalysisRequest(request.request_id, {
        status: "failed",
        error_message: err instanceof Error ? err.message : "Databricks submit failed",
      });
      queued.push({
        docket_id: candidate.docket_id,
        request_id: request.request_id,
        status: "failed-submit",
      });
    }
  }

  console.log("\nQueued:");
  for (const row of queued) {
    console.log(
      `  ${row.docket_id.padEnd(22)} ${row.status.padEnd(14)} ${row.request_id}${row.run_id ? ` run=${row.run_id}` : ""}`,
    );
  }
  console.log("\nSkipped:");
  for (const row of skipped) {
    console.log(`  ${row.docket_id.padEnd(22)} ${row.reason}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
