// Tiny ad-hoc migration runner. We don't have a real migration framework —
// the team applies SQL files by hand against Supabase. This script just lets
// you do that from the repo: `npx tsx scripts/apply-migration.ts 002_findings.sql`.
//
// Idempotent SQL (CREATE TABLE IF NOT EXISTS, etc.) only — there is no
// applied-versions table to prevent re-runs.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

function loadEnvLocal() {
  const path = resolve(process.cwd(), ".env.local");
  if (!existsSync(path)) return;
  const text = readFileSync(path, "utf8");
  for (const raw of text.split(/\r?\n/)) {
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

async function main() {
  const filename = process.argv[2];
  if (!filename) {
    console.error("Usage: tsx scripts/apply-migration.ts <filename>");
    process.exit(1);
  }
  const path = resolve(process.cwd(), "db", "migrations", filename);
  const sql = readFileSync(path, "utf8");
  console.log(`Applying migration: ${filename}`);

  const { getDbPool } = await import("../lib/db");
  const pool = getDbPool();
  await pool.query(sql);
  console.log(`Applied: ${filename}`);
  await pool.end();
}

main().catch((err) => {
  console.error("Migration failed:", err);
  process.exit(1);
});
