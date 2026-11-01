#!/usr/bin/env node
// Runs the standalone production server locally, the same way the Docker
// image does. Next.js leaves static assets out of .next/standalone, so they
// are copied in first.

import { spawn } from "node:child_process";
import { cpSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const standalone = path.join(root, ".next", "standalone");
const server = path.join(standalone, "server.js");

if (!existsSync(server)) {
  console.error('serve-standalone: .next/standalone/server.js is missing. Run "npm run build" first.');
  process.exit(2);
}

cpSync(path.join(root, ".next", "static"), path.join(standalone, ".next", "static"), { recursive: true });
if (existsSync(path.join(root, "public"))) {
  cpSync(path.join(root, "public"), path.join(standalone, "public"), { recursive: true });
}

const child = spawn(process.execPath, [server], {
  cwd: standalone,
  stdio: "inherit",
  // Shells often set HOSTNAME to the machine name, which Next.js would bind to,
  // so it is not inherited here. Use BIND_HOST to choose another address.
  env: { ...process.env, PORT: process.env.PORT ?? "3000", HOSTNAME: process.env.BIND_HOST ?? "0.0.0.0" },
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code) => process.exit(code ?? 0));
