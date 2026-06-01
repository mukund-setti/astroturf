// Preview / generate a finding from a single Databricks cluster.
//
// Usage:
//   tsx scripts/generate-finding.ts                       # preview largest cluster of DEMO_DOCKET_ID
//   tsx scripts/generate-finding.ts --docket 17-108       # preview largest cluster of that docket
//   tsx scripts/generate-finding.ts --cluster <id> --docket 17-108
//   tsx scripts/generate-finding.ts ... --commit          # also upsert into findings table
//
// Prints the representative comment (input) and the generated headline +
// one_liner (output) side by side so you can eyeball the prompt's behavior
// before backfilling.

import { readFileSync, existsSync } from "node:fs";
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
    )
      value = value.slice(1, -1);
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
loadEnvLocal();

interface Args {
  cluster_id?: string;
  docket_id: string;
  agency_id?: string;
  commit: boolean;
}

function parseArgs(): Args {
  const argv = process.argv.slice(2);
  let cluster_id: string | undefined;
  let docket_id = process.env.DEMO_DOCKET_ID || "17-108";
  let agency_id: string | undefined;
  let commit = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--cluster") cluster_id = argv[++i];
    else if (a === "--docket") docket_id = argv[++i];
    else if (a === "--agency") agency_id = argv[++i];
    else if (a === "--commit") commit = true;
  }
  return { cluster_id, docket_id, agency_id, commit };
}

async function main() {
  const args = parseArgs();

  const { getCatalog, query: queryDb } = await import("../lib/databricks");
  const {
    previewFindingFromCluster,
    upsertFinding,
    makeSlug,
  } = await import("../lib/findings-store");

  let cluster_id = args.cluster_id;
  if (!cluster_id) {
    const catalog = getCatalog();
    const rows = await queryDb<{ cluster_id: string; cluster_size: number }>(
      `SELECT cluster_id, MAX(cluster_size) AS cluster_size
       FROM ${catalog}.demo.cluster_review_export
       WHERE docket_id = :docket_id
       GROUP BY cluster_id
       ORDER BY cluster_size DESC
       LIMIT 1`,
      { docket_id: args.docket_id },
    );
    if (rows.length === 0) {
      console.error(
        `No clusters found for docket_id=${args.docket_id} in cluster_review_export.`,
      );
      process.exit(1);
    }
    cluster_id = rows[0].cluster_id;
    console.log(
      `[auto-pick] largest cluster: ${cluster_id} (size=${rows[0].cluster_size})\n`,
    );
  }

  const agency_id = args.agency_id ?? topicAgencyHint(args.docket_id) ?? undefined;
  console.log(`Generating preview for cluster=${cluster_id} docket=${args.docket_id}...`);
  const preview = await previewFindingFromCluster({
    cluster_id,
    docket_id: args.docket_id,
    agency_id,
  });

  const bar = "─".repeat(72);
  console.log(`\n${bar}`);
  console.log("INPUT (representative comment from the cluster)");
  console.log(bar);
  console.log(`cluster_id        : ${preview.cluster_id}`);
  console.log(`docket_id         : ${preview.docket_id}`);
  console.log(`cluster_size      : ${preview.cluster_size}`);
  console.log(`posted_date_range : ${preview.posted_date_range ?? "(none)"}`);
  console.log(`rep_submitter     : ${preview.rep_submitter_name ?? "(none)"}`);
  console.log("");
  console.log(preview.rep_text);

  console.log(`\n${bar}`);
  console.log("OUTPUT (LLM-generated finding)");
  console.log(bar);
  console.log(`headline   : ${preview.headline}`);
  console.log(`one_liner  : ${preview.one_liner}`);
  console.log(`topic_slug : ${preview.topic_slug}`);
  console.log(`slug       : ${preview.slug}`);
  console.log(bar);

  if (args.commit) {
    console.log("\nCommitting to findings table...");
    const finding = await upsertFinding({
      cluster_id: preview.cluster_id,
      docket_id: preview.docket_id,
      slug: makeSlug(preview.headline, preview.cluster_id),
      headline: preview.headline,
      one_liner: preview.one_liner,
      topic_slug: preview.topic_slug,
      cluster_size: preview.cluster_size,
      posted_date_range: preview.posted_date_range,
      agency_id: args.agency_id ?? topicAgencyHint(args.docket_id),
      is_featured: false,
      auto_generated: true,
      manually_edited: false,
    });
    console.log(`Wrote finding id=${finding.id} slug=${finding.slug}`);
  } else {
    console.log("\n(preview only; re-run with --commit to upsert into findings)");
  }

  process.exit(0);
}

function topicAgencyHint(docket_id: string): string | null {
  const m = docket_id.match(/^([A-Z]+)-/);
  if (m) return m[1];
  if (/^\d/.test(docket_id)) return "FCC";
  return null;
}

main().catch((err) => {
  console.error("\ngenerate-finding failed:");
  console.error(err);
  process.exit(1);
});
