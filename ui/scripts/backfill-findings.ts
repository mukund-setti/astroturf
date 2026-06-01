// Backfill findings for every (cluster_id, docket_id) currently in
// astroturf.demo.cluster_review_export. Largest clusters first so we get
// the most narratively-load-bearing findings ready before the long tail.
// Skips clusters that already have a finding row (idempotent re-run);
// pass --force to overwrite existing rows.
//
// Usage:
//   tsx scripts/backfill-findings.ts                    # all dockets
//   tsx scripts/backfill-findings.ts --docket 17-108    # one docket
//   tsx scripts/backfill-findings.ts --limit 5          # stop after N writes
//   tsx scripts/backfill-findings.ts --force            # regenerate existing

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
process.env.ASTROTURF_DATA_MODE = process.env.ASTROTURF_DATA_MODE || "live";

interface Args {
  docket_id?: string;
  limit: number;
  force: boolean;
  dry_run: boolean;
}

function parseArgs(): Args {
  const argv = process.argv.slice(2);
  let docket_id: string | undefined;
  let limit = Number.POSITIVE_INFINITY;
  let force = false;
  let dry_run = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--docket") docket_id = argv[++i];
    else if (a === "--limit") limit = parseInt(argv[++i], 10) || limit;
    else if (a === "--force") force = true;
    else if (a === "--dry-run") dry_run = true;
  }
  return { docket_id, limit, force, dry_run };
}

function agencyHintFromDocket(docket_id: string): string | undefined {
  const m = docket_id.match(/^([A-Z]+)-/);
  if (m) return m[1];
  if (/^\d/.test(docket_id)) return "FCC";
  return undefined;
}

async function main() {
  const args = parseArgs();
  const { getCatalog, query: queryDb } = await import("../lib/databricks");
  const {
    generateFindingFromCluster,
    getFindingByClusterId,
  } = await import("../lib/findings-store");

  const catalog = getCatalog();
  const sql = args.docket_id
    ? `SELECT cluster_id, docket_id, MAX(cluster_size) AS cluster_size
       FROM ${catalog}.demo.cluster_review_export
       WHERE docket_id = :docket_id
       GROUP BY cluster_id, docket_id
       ORDER BY cluster_size DESC`
    : `SELECT cluster_id, docket_id, MAX(cluster_size) AS cluster_size
       FROM ${catalog}.demo.cluster_review_export
       GROUP BY cluster_id, docket_id
       ORDER BY cluster_size DESC`;

  const rows = await queryDb<{
    cluster_id: string;
    docket_id: string;
    cluster_size: number;
  }>(sql, args.docket_id ? { docket_id: args.docket_id } : {});

  console.log(
    `Snapshot: ${rows.length} (cluster, docket) pairs. Limit=${args.limit === Number.POSITIVE_INFINITY ? "none" : args.limit}, force=${args.force}, dry_run=${args.dry_run}`,
  );
  if (rows.length === 0) {
    console.log("Nothing to backfill.");
    return;
  }

  let generated = 0;
  let skipped = 0;
  let errored = 0;
  const startMs = Date.now();

  for (let i = 0; i < rows.length; i++) {
    if (generated >= args.limit) {
      console.log(`Hit --limit=${args.limit}; stopping.`);
      break;
    }
    const row = rows[i];
    const prefix = `[${i + 1}/${rows.length}] cluster=${row.cluster_id.slice(0, 12)}… docket=${row.docket_id} size=${row.cluster_size}`;

    if (!args.force) {
      const existing = await getFindingByClusterId(row.cluster_id);
      if (existing) {
        skipped += 1;
        console.log(`${prefix}  skip (existing slug=${existing.slug})`);
        continue;
      }
    }

    if (args.dry_run) {
      generated += 1;
      console.log(`${prefix}  would generate`);
      continue;
    }

    try {
      const agency_id = agencyHintFromDocket(row.docket_id);
      const finding = await generateFindingFromCluster({
        cluster_id: row.cluster_id,
        docket_id: row.docket_id,
        agency_id,
      });
      if (!finding) {
        skipped += 1;
        console.log(`${prefix}  skip (cluster too small)`);
        continue;
      }
      generated += 1;
      console.log(`${prefix}  -> ${finding.slug}`);
    } catch (err) {
      errored += 1;
      const message = err instanceof Error ? err.message : String(err);
      console.error(`${prefix}  ERROR ${message.slice(0, 200)}`);
    }

    // 200 ms gap so we stay under the Foundation Model API per-second budget.
    await new Promise((resolve) => setTimeout(resolve, 200));
  }

  const elapsedSec = ((Date.now() - startMs) / 1000).toFixed(1);
  console.log("");
  console.log(
    `Done. generated=${generated} skipped=${skipped} errored=${errored} (${elapsedSec}s)`,
  );
  process.exit(0);
}

main().catch((err) => {
  console.error("backfill-findings failed:");
  console.error(err);
  process.exit(1);
});
