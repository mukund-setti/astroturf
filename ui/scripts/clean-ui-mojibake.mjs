import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const roots = ["app", "components", "lib"];
const exts = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs"]);
const c = (...codes) => String.fromCharCode(...codes);

const replacements = [
  [c(0x00e2, 0x2020, 0x2019), "->"],
  [c(0x00e2, 0x2020, 0x0090), "<-"],
  [c(0x2192), "->"],
  [c(0x2190), "<-"],
  [c(0x00e2, 0x20ac, 0x00a6), "..."],
  [c(0x2026), "..."],
  [c(0x00c2, 0x00b7), "/"],
  [c(0x00b7), "/"],
  [c(0x00e2, 0x20ac, 0x00a2), "*"],
  [c(0x2022), "*"],
  [c(0x00e2, 0x0153, 0x201c), "OK"],
  [c(0x2713), "OK"],
  [c(0x2717), "x"],
  [c(0x00e2, 0x2013, 0x00b8), ">"],
  [c(0x00c2, 0x00b2), "^2"],
  [c(0x00b2), "^2"],
  [c(0x00c3, 0x2014), "x"],
  [c(0x00c3), ""],
  [c(0x00d7), "x"],
  [c(0x00e2, 0x20ac, 0x2122), "'"],
  [c(0x2019), "'"],
  [c(0x00e2, 0x20ac, 0x0153), '"'],
  [c(0x00e2, 0x20ac, 0x009d), '"'],
  [c(0x201c), '"'],
  [c(0x201d), '"'],
  [c(0x00e2, 0x20ac, 0x02dc), "'"],
  [c(0x2018), "'"],
  [c(0x00c2), ""],
  [c(0xfffd), ""],
];

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const st = statSync(path);
    if (st.isDirectory()) files.push(...walk(path));
    else if (exts.has(path.slice(path.lastIndexOf(".")))) files.push(path);
  }
  return files;
}

let changed = 0;
for (const root of roots) {
  for (const file of walk(root)) {
    const before = readFileSync(file, "utf8");
    let after = before;
    for (const [from, to] of replacements) {
      after = after.split(from).join(to);
    }
    after = after.replace(/(\d+(?:\.\d+)?)\s+-\s+/g, "$1x ");
    if (after !== before) {
      writeFileSync(file, after, "utf8");
      changed += 1;
      console.log(file);
    }
  }
}

console.log(`cleaned ${changed} files`);
