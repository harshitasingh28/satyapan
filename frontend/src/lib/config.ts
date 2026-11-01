const DEFAULT_API_BASE = "http://localhost:8000";

/** Normalise the configured base URL: http(s) only, no trailing slash. */
export function normaliseApiBase(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  if (!/^https?:\/\//i.test(value)) return DEFAULT_API_BASE;
  return value.replace(/\/+$/, "");
}

// NEXT_PUBLIC_ variables are inlined at build time, so this must stay a
// literal property access.
export const API_BASE = normaliseApiBase(process.env.NEXT_PUBLIC_API_BASE_URL);

export const HISTORY_KEY = "satyapan.history.v1";
