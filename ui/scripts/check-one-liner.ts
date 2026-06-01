// Check stored finding one_liner for the net neutrality repeal finding
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
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))
      value = value.slice(1, -1);
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
loadEnvLocal();

async function main() {
  const { query } = await import("../lib/db");
  const rows = await query(
    `SELECT slug, headline, one_liner, cluster_size, docket_id FROM findings WHERE slug LIKE '%32d7df' OR cluster_id LIKE '2f2ec5bb%'`,
    []
  );
  for (const r of rows) {
    console.log("slug:", r.slug);
    console.log("headline:", r.headline);
    console.log("cluster_size:", r.cluster_size);
    console.log("one_liner:", r.one_liner);
    console.log("---");
  }
  // Also check a few others to see if cluster_size appears in one_liners
  const sample = await query(
    `SELECT slug, cluster_size, one_liner FROM findings ORDER BY cluster_size DESC LIMIT 5`,
    []
  );
  console.log("\nTop 5 by cluster_size:");
  for (const r of sample) {
    console.log(`  [${r.cluster_size}] ${r.slug}`);
    console.log(`    ${r.one_liner}`);
    const hasSize = String(r.one_liner).includes(String(r.cluster_size));
    console.log(`    contains cluster_size? ${hasSize}`);
  }
  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
