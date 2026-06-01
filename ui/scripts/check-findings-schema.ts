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
  const { getDbPool } = await import("../lib/db");
  const pool = getDbPool();
  const cols = await pool.query(
    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'findings' ORDER BY ordinal_position",
  );
  console.log("findings columns:");
  for (const r of cols.rows)
    console.log(`  ${r.column_name.padEnd(22)} ${r.data_type}`);
  const idx = await pool.query(
    "SELECT indexname FROM pg_indexes WHERE tablename = 'findings' ORDER BY indexname",
  );
  console.log("findings indexes:");
  for (const r of idx.rows) console.log(`  ${r.indexname}`);
  await pool.end();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
