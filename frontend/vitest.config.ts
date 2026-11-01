import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Next.js keeps "jsx": "preserve" in tsconfig, so tests compile JSX here.
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
