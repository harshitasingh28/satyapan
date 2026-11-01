const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

const dateTimeFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

const dateOnlyFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "1 Nov 2026, 4:05 pm IST" in the viewer's time zone. Unparseable input is returned as is. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "Not known";
  if (DATE_ONLY.test(iso)) {
    const d = new Date(`${iso}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? iso : dateOnlyFormat.format(d);
  }
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTimeFormat.format(d);
}

const numberFormat = new Intl.NumberFormat("en-IN");

export function formatNumber(n: number): string {
  return Number.isFinite(n) ? numberFormat.format(n) : String(n);
}

export function formatMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null || !Number.isFinite(ms)) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatRetention(hours: number): string {
  if (!Number.isFinite(hours) || hours <= 0) return "the retention period";
  if (hours >= 48 && hours % 24 === 0) return `${hours / 24} days`;
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

/** "SERVICE_ERROR" -> "Service error", "safe_browsing" -> "Safe browsing". */
export function humanise(code: string): string {
  const spaced = code.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : code;
}
