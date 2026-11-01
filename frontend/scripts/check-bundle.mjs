#!/usr/bin/env node
// Scans the Next.js build output for strings that look like secrets.
// The frontend must never contain a Hugging Face token, a Google API key or a
// MongoDB connection string. Exits 1 on any hit, 2 when there is no build.

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(root, ".next");

const PATTERNS = [
  { name: "Hugging Face token", re: /hf_[A-Za-z0-9]{20,}/g },
  { name: "Google API key", re: /AIza[0-9A-Za-z_-]{30,}/g },
  { name: "MongoDB connection string", re: /mongodb\+srv:\/\//g },
];

const MAX_BYTES = 64 * 1024 * 1024;

function* walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.isFile()) yield full;
  }
}

try {
  if (!statSync(target).isDirectory()) throw new Error("not a directory");
} catch {
  console.error(`check-bundle: no build output at ${target}. Run "npm run build" first.`);
  process.exit(2);
}

let files = 0;
let bytes = 0;
const hits = [];
for (const file of walk(target)) {
  const size = statSync(file).size;
  if (size > MAX_BYTES) {
    console.warn(`check-bundle: skipped ${path.relative(root, file)} (${size} bytes, over the scan limit)`);
    continue;
  }
  files += 1;
  bytes += size;
  // latin1 keeps a 1:1 byte mapping, so binary files cannot break the scan.
  const text = readFileSync(file).toString("latin1");
  for (const { name, re } of PATTERNS) {
    re.lastIndex = 0;
    const match = re.exec(text);
    if (match) {
      const shown = match[0].slice(0, 8) + "…";
      hits.push(`${path.relative(root, file)}: ${name} (${shown})`);
    }
  }
}

if (hits.length > 0) {
  console.error(`check-bundle: FAIL, ${hits.length} possible secret(s) found in .next/`);
  for (const hit of hits) console.error(`  ${hit}`);
  process.exit(1);
}
console.log(`check-bundle: OK, scanned ${files} files (${(bytes / 1024 / 1024).toFixed(1)} MB) in .next/, no secrets found`);
