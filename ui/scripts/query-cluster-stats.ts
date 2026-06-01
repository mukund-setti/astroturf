// Quick one-off: query cluster_review_export for docket-level summary.
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
process.env.ASTROTURF_DATA_MODE = "live";

async function main() {
  const { getCatalog, query } = await import("../lib/databricks");
  const catalog = getCatalog();
  const sql = `
    SELECT docket_id,
           COUNT(*) AS rows,
           COUNT(DISTINCT cluster_id) AS clusters,
           MAX(cluster_size) AS largest
    FROM ${catalog}.demo.cluster_review_export
    GROUP BY docket_id
    ORDER BY rows DESC
  `;
  const rows = await query<Record<string, unknown>>(sql, {});
  console.log("\ndocket_id                    | rows    | clusters | largest");
  console.log("-----------------------------+---------+----------+--------");
  for (const r of rows) {
    const did = String(r.docket_id ?? "").padEnd(28);
    const cnt = String(r.rows ?? 0).padStart(7);
    const cl = String(r.clusters ?? 0).padStart(8);
    const lg = String(r.largest ?? 0).padStart(7);
    console.log(`${did} | ${cnt} | ${cl} | ${lg}`);
  }
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
