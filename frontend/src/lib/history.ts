import { HISTORY_KEY } from "./config";
import type { Verdict } from "./types";

// Investigation history lives only in this browser. Each entry holds the
// access token that the API requires, so removing an entry means this browser
// can no longer open that investigation. Every storage call is wrapped:
// private windows, blocked cookies and full quotas make localStorage throw.

export type HistoryEntry = {
  id: string;
  access_token: string;
  created_at: string;
  text_preview: string;
  verdict: Verdict | null;
};

const MAX_ENTRIES = 100;
const VERDICTS: readonly string[] = ["GENUINE", "FAKE", "UNVERIFIED"];

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStorage(): StorageLike | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

function isEntry(value: unknown): value is HistoryEntry {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    v.id.length > 0 &&
    typeof v.access_token === "string" &&
    typeof v.created_at === "string" &&
    typeof v.text_preview === "string" &&
    (v.verdict === null || (typeof v.verdict === "string" && VERDICTS.includes(v.verdict)))
  );
}

function newestFirst(a: HistoryEntry, b: HistoryEntry): number {
  return (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0);
}

/** Can this browser store history at all? */
export function isStorageAvailable(storage: StorageLike | null = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    const probe = `${HISTORY_KEY}.probe`;
    storage.setItem(probe, "1");
    storage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

/** All valid entries, newest first. Returns [] when storage is unavailable or corrupt. */
export function readHistory(storage: StorageLike | null = defaultStorage()): HistoryEntry[] {
  if (!storage) return [];
  try {
    const raw = storage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isEntry).sort(newestFirst);
  } catch {
    return [];
  }
}

function writeHistory(entries: HistoryEntry[], storage: StorageLike | null): boolean {
  if (!storage) return false;
  try {
    storage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
    return true;
  } catch {
    return false;
  }
}

/** Adds or replaces an entry. Returns false if it could not be stored. */
export function saveHistoryEntry(entry: HistoryEntry, storage: StorageLike | null = defaultStorage()): boolean {
  const rest = readHistory(storage).filter((e) => e.id !== entry.id);
  return writeHistory([entry, ...rest].sort(newestFirst), storage);
}

export function updateHistoryVerdict(
  id: string,
  verdict: Verdict | null,
  storage: StorageLike | null = defaultStorage(),
): boolean {
  const entries = readHistory(storage);
  const found = entries.find((e) => e.id === id);
  if (!found) return false;
  if (found.verdict === verdict) return true;
  found.verdict = verdict;
  return writeHistory(entries, storage);
}

export function findHistoryEntry(id: string, storage: StorageLike | null = defaultStorage()): HistoryEntry | null {
  return readHistory(storage).find((e) => e.id === id) ?? null;
}

export function removeHistoryEntry(id: string, storage: StorageLike | null = defaultStorage()): boolean {
  return writeHistory(
    readHistory(storage).filter((e) => e.id !== id),
    storage,
  );
}

export function clearHistory(storage: StorageLike | null = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    storage.removeItem(HISTORY_KEY);
    return true;
  } catch {
    return false;
  }
}

export function makePreview(text: string): string {
  // Array.from splits by code point, so an emoji or other surrogate pair is never cut in half.
  return Array.from(text.replace(/\s+/g, " ").trim()).slice(0, 80).join("");
}
