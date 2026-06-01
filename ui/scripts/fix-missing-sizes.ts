// Re-generate findings where one_liner doesn't contain the cluster_size number.
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
  // Find findings where one_liner doesn't contain the cluster_size as a substring
  const broken = await query<Record<string, unknown>>(
    `SELECT id, cluster_id, docket_id, slug, cluster_size, one_liner
     FROM findings
     WHERE one_liner NOT LIKE '%' || cluster_size::text || ' similar comments%'
     ORDER BY cluster_size DESC`,
    []
  );
  console.log(`Found ${broken.length} findings missing cluster_size in one_liner:`);
  for (const r of broken) {
    console.log(`  [${r.cluster_size}] ${r.slug} — ${r.docket_id}`);
  }

  if (broken.length === 0) {
    console.log("All findings already contain cluster_size. Done.");
    process.exit(0);
  }

  const { generateFindingFromCluster } = await import("../lib/findings-store");

  for (const r of broken) {
    const agency = String(r.docket_id).match(/^([A-Z]+)-/)?.[1] ?? (/^\d/.test(String(r.docket_id)) ? "FCC" : undefined);
    console.log(`\nRe-generating: ${r.slug} (cluster_size=${r.cluster_size})...`);
    try {
      const finding = await generateFindingFromCluster({
        cluster_id: String(r.cluster_id),
        docket_id: String(r.docket_id),
        agency_id: agency,
      });
      if (!finding) {
        console.log(`  → skipped (cluster too small)`);
        continue;
      }
      const hasSize = finding.one_liner.includes(`${r.cluster_size} similar comments`);
      console.log(`  → ${hasSize ? "✓" : "✗"} one_liner: ${finding.one_liner.slice(0, 120)}...`);
    } catch (err) {
      console.error(`  ERROR: ${err instanceof Error ? err.message : err}`);
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }

  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
