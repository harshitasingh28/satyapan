import { existsSync } from "node:fs";
import { chromium, defineConfig, devices } from "@playwright/test";

// The e2e suite runs the built standalone frontend against a REAL backend.
//   E2E_API_URL      backend under test (default http://localhost:8000). The
//                    frontend must be built with the same NEXT_PUBLIC_API_BASE_URL.
//   E2E_BASE_URL     use an already running frontend instead of starting one.
//   E2E_PORT         port for the local frontend (default 3000, the backend's
//                    default allowed CORS origin is http://localhost:3000).
const port = Number(process.env.E2E_PORT ?? 3000);
const baseURL = process.env.E2E_BASE_URL ?? `http://localhost:${port}`;

// Use the preinstalled Chromium. Never download browsers from here.
function chromiumPath(): string | undefined {
  try {
    const p = chromium.executablePath();
    return existsSync(p) ? p : undefined;
  } catch {
    return undefined;
  }
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    acceptDownloads: true,
    trace: "off",
    launchOptions: { executablePath: chromiumPath() },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], launchOptions: { executablePath: chromiumPath() } } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "node scripts/serve-standalone.mjs",
        url: baseURL,
        reuseExistingServer: true,
        timeout: 60_000,
        env: { PORT: String(port) },
      },
});
