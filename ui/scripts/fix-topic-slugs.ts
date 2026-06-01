// Fix topic_slug for findings that were backfilled before the manual mapping was added.
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
  const { query } = await import("../lib/db");

  // Fix ED-2018-OCR-0064 findings: should be "education"
  const edResult = await query(
    `UPDATE findings SET topic_slug = 'education', updated_at = NOW()
     WHERE docket_id = 'ED-2018-OCR-0064' AND topic_slug != 'education'
     RETURNING id, slug, topic_slug`,
    []
  );
  console.log(`ED-2018-OCR-0064: updated ${edResult.length} findings to topic_slug='education'`);

  // Fix FTC-2023-0007 findings: should be "tech-regulation"
  const ftcResult = await query(
    `UPDATE findings SET topic_slug = 'tech-regulation', updated_at = NOW()
     WHERE docket_id = 'FTC-2023-0007' AND topic_slug != 'tech-regulation'
     RETURNING id, slug, topic_slug`,
    []
  );
  console.log(`FTC-2023-0007: updated ${ftcResult.length} findings to topic_slug='tech-regulation'`);

  // Fix CMS-2019-0006: should be "health-care" (verify)
  const cmsResult = await query(
    `UPDATE findings SET topic_slug = 'health-care', updated_at = NOW()
     WHERE docket_id = 'CMS-2019-0006' AND topic_slug != 'health-care'
     RETURNING id, slug, topic_slug`,
    []
  );
  console.log(`CMS-2019-0006: updated ${cmsResult.length} findings to topic_slug='health-care'`);

  // Show final distribution
  const dist = await query(
    `SELECT topic_slug, COUNT(*) AS cnt FROM findings GROUP BY topic_slug ORDER BY cnt DESC`,
    []
  );
  console.log("\nFinal topic distribution:");
  for (const r of dist) {
    console.log(`  ${r.topic_slug}: ${r.cnt}`);
  }

  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
