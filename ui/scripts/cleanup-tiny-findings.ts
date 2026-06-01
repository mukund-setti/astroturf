// Delete findings rows where cluster_size < MIN_CLUSTER_SIZE_FOR_FINDING.
// Idempotent: re-running after cleanup is a no-op.
//
// Usage:
//   cd ui && npx tsx scripts/cleanup-tiny-findings.ts

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

async function main() {
  const { MIN_CLUSTER_SIZE_FOR_FINDING } = await import("../lib/findings-store");
  const { query } = await import("../lib/db");

  console.log(`Deleting findings with cluster_size < ${MIN_CLUSTER_SIZE_FOR_FINDING}...`);

  const deleted = await query<Record<string, unknown>>(
    `DELETE FROM findings WHERE cluster_size < $1 RETURNING id, slug, cluster_size`,
    [MIN_CLUSTER_SIZE_FOR_FINDING],
  );

  console.log(`Deleted ${deleted.length} tiny findings:`);
  for (const r of deleted) {
    console.log(`  [size=${r.cluster_size}] ${r.slug}`);
  }

  const remaining = await query<Record<string, unknown>>(
    `SELECT COUNT(*) AS cnt FROM findings`,
    [],
  );
  const count = Number(remaining[0]?.cnt ?? 0);
  console.log(`\nRemaining findings: ${count}`);

  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
