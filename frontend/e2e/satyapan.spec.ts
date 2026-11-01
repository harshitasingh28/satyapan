import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Runs against a REAL backend. Build the frontend with
// NEXT_PUBLIC_API_BASE_URL set to the same value as E2E_API_URL.
const API = (process.env.E2E_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

async function backendProblem(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return `GET ${API}/health answered HTTP ${res.status}`;
    const body = (await res.json().catch(() => null)) as { ok?: unknown } | null;
    if (body?.ok !== true) return `GET ${API}/health did not answer {"ok": true}`;
    return null;
  } catch (error) {
    return `GET ${API}/health is unreachable (${error instanceof Error ? error.message : String(error)})`;
  }
}

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact}): ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function hasHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
}

const STATIC_PATHS = ["/", "/verify", "/history", "/investigations/e2e-unknown-id"];

test.describe("pages without a backend run", () => {
  for (const path of STATIC_PATHS) {
    test(`axe finds no serious or critical violations on ${path}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await seriousViolations(page)).toEqual([]);
    });
  }

  test("no horizontal scroll at 360 x 740", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    for (const path of STATIC_PATHS) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await hasHorizontalScroll(page), path).toBe(false);
    }
    await context.close();
  });

  test("an id without a stored token is reported as private to its browser", async ({ page }) => {
    await page.goto("/investigations/e2e-unknown-id");
    await expect(page.getByRole("heading", { level: 1, name: "This investigation is private to the browser that created it" })).toBeVisible();
  });
});

test.describe("against the real backend", () => {
  let problem: string | null = null;

  test.beforeAll(async () => {
    problem = await backendProblem();
    if (problem) console.log(`[e2e] Skipping backend tests: ${problem}`);
    else console.log(`[e2e] Backend reachable at ${API}`);
  });

  test.beforeEach(() => {
    test.skip(problem !== null, problem ?? "");
  });

  test("submit a text claim, see live steps and a verdict, open history, download the Markdown report", async ({ page }) => {
    await page.goto("/verify");
    await expect(page.getByText(/Connected to/)).toBeVisible();

    await page
      .getByLabel("Message text", { exact: true })
      .fill("Government announces Rs 5000 for every citizen under a new scheme. Register now at the official link before Sunday.");
    await page.getByRole("button", { name: "Run verification" }).click();

    // Live trace rows come only from server step events.
    const steps = page.getByRole("list", { name: "Steps" }).getByRole("listitem");
    await expect(steps.first()).toBeVisible({ timeout: 60_000 });
    await expect(page).toHaveURL(/\/investigations\/[^/?#]+$/);

    const verdict = page.getByRole("heading", { level: 2, name: /Verdict: (GENUINE|FAKE|UNVERIFIED)/ });
    await expect(verdict).toBeVisible({ timeout: 200_000 });
    expect(await steps.count()).toBeGreaterThan(0);
    for (const name of ["Verified from sources", "AI explanation, checked against sources", "Not available"]) {
      await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    }
    expect(await seriousViolations(page)).toEqual([]);

    const investigationUrl = page.url();
    const verdictWord = ((await verdict.textContent()) ?? "").match(/GENUINE|FAKE|UNVERIFIED/)?.[0] ?? "";

    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "History" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "History" })).toBeVisible();
    const entry = page.getByRole("list", { name: "Investigations" }).getByRole("listitem").first();
    await expect(entry).toContainText(verdictWord);
    await expect(entry).toContainText("Government announces Rs 5000");

    await entry.getByRole("link").click();
    await expect(page).toHaveURL(investigationUrl);
    await expect(page.getByRole("heading", { level: 2, name: new RegExp(`Verdict: ${verdictWord}`) })).toBeVisible();

    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download report (Markdown)" }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toMatch(/^satyapan-.+\.md$/);
    const markdown = readFileSync(await download.path(), "utf8");
    expect(markdown.length).toBeGreaterThan(50);
    expect(markdown).toContain(verdictWord);

    // The saved result also fits a small phone.
    await page.setViewportSize({ width: 360, height: 740 });
    expect(await hasHorizontalScroll(page)).toBe(false);
  });
});
