// Lists Databricks Foundation Model / Serving endpoints visible to the
// configured DATABRICKS_TOKEN, so we can pick a Claude variant that's
// actually deployed on this workspace.

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
  const host = (process.env.DATABRICKS_HOST ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  const token = (process.env.DATABRICKS_TOKEN ?? "").trim();
  const url = `https://${host}/api/2.0/serving-endpoints`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    console.error(`HTTP ${res.status}: ${await res.text()}`);
    process.exit(1);
  }
  const data = (await res.json()) as {
    endpoints?: Array<{ name: string; state?: { ready?: string } }>;
  };
  const endpoints = data.endpoints ?? [];
  console.log(`Found ${endpoints.length} serving endpoints:`);
  for (const ep of endpoints) {
    const ready = ep.state?.ready ?? "unknown";
    console.log(`  ${ep.name.padEnd(60)} ${ready}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
