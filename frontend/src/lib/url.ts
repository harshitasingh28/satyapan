/** True only for absolute http:// or https:// URLs. Everything else renders as plain text. */
export function isHttpUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const trimmed = value.trim();
  if (!/^https?:\/\//i.test(trimmed)) return false;
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/** A DOM id for an evidence card. Evidence ids look like "E1". */
export function evidenceAnchorId(evidenceId: string): string {
  return `evidence-${evidenceId.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}
