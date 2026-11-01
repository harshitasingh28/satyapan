// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "../../src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

describe("app source rules", () => {
  const files = sourceFiles(SRC).map((file) => ({ file: path.relative(SRC, file), text: readFileSync(file, "utf8") }));

  it("finds the source files", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it("never injects HTML", () => {
    for (const { file, text } of files) {
      expect(text, file).not.toMatch(/dangerouslySetInnerHTML|\.innerHTML\s*=|outerHTML\s*=|insertAdjacentHTML/);
    }
  });

  it("never imports test data", () => {
    for (const { file, text } of files) {
      expect(text, file).not.toMatch(/from\s+["'][^"']*(tests\/|fixture-)[^"']*["']/);
    }
  });

  it("reads only the public API base URL from the environment", () => {
    for (const { file, text } of files) {
      const vars = [...text.matchAll(/process\.env\.([A-Z0-9_]+)/g)].map((m) => m[1]);
      for (const name of vars) expect(name, file).toBe("NEXT_PUBLIC_API_BASE_URL");
    }
  });
});
