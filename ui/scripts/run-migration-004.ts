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
  const sql = readFileSync(
    resolve(process.cwd(), "db/migrations/004_analysis_requests_user_tracking.sql"),
    "utf8",
  );
  await query(sql, []);
  console.log("Migration 004 applied successfully.");
  process.exit(0);
}
main().catch((e) => {
  console.error("Migration 004 failed:", e.message);
  process.exit(1);
});
