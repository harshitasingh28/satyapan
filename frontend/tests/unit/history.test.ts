import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HISTORY_KEY } from "@/lib/config";
import {
  clearHistory,
  findHistoryEntry,
  type HistoryEntry,
  isStorageAvailable,
  makePreview,
  readHistory,
  removeHistoryEntry,
  saveHistoryEntry,
  updateHistoryVerdict,
} from "@/lib/history";

const older: HistoryEntry = {
  id: "inv-old",
  access_token: "tok-old",
  created_at: "2026-10-30T10:00:00Z",
  text_preview: "older",
  verdict: "UNVERIFIED",
};
const newer: HistoryEntry = {
  id: "inv-new",
  access_token: "tok-new",
  created_at: "2026-10-31T10:00:00Z",
  text_preview: "newer",
  verdict: null,
};

const throwing = {
  getItem: () => {
    throw new DOMException("blocked", "SecurityError");
  },
  setItem: () => {
    throw new DOMException("full", "QuotaExceededError");
  },
  removeItem: () => {
    throw new DOMException("blocked", "SecurityError");
  },
};

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

describe("history storage", () => {
  it("saves, reads newest first, updates, removes and clears", () => {
    expect(saveHistoryEntry(older)).toBe(true);
    expect(saveHistoryEntry(newer)).toBe(true);
    expect(readHistory().map((e) => e.id)).toEqual(["inv-new", "inv-old"]);

    expect(updateHistoryVerdict("inv-new", "GENUINE")).toBe(true);
    expect(findHistoryEntry("inv-new")?.verdict).toBe("GENUINE");
    expect(findHistoryEntry("inv-new")?.access_token).toBe("tok-new");

    expect(removeHistoryEntry("inv-old")).toBe(true);
    expect(readHistory().map((e) => e.id)).toEqual(["inv-new"]);

    expect(clearHistory()).toBe(true);
    expect(readHistory()).toEqual([]);
  });

  it("replaces an entry with the same id instead of duplicating it", () => {
    saveHistoryEntry(older);
    saveHistoryEntry({ ...older, text_preview: "changed" });
    expect(readHistory()).toHaveLength(1);
    expect(readHistory()[0]?.text_preview).toBe("changed");
  });

  it("returns an empty list for corrupt or unexpected data", () => {
    window.localStorage.setItem(HISTORY_KEY, "{not json");
    expect(readHistory()).toEqual([]);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify({ id: "x" }));
    expect(readHistory()).toEqual([]);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify([older, { id: 5 }, { ...newer, verdict: "MAYBE" }]));
    expect(readHistory().map((e) => e.id)).toEqual(["inv-old"]);
  });

  it("never throws when every storage call throws", () => {
    expect(isStorageAvailable(throwing)).toBe(false);
    expect(readHistory(throwing)).toEqual([]);
    expect(saveHistoryEntry(older, throwing)).toBe(false);
    expect(updateHistoryVerdict("inv-old", "FAKE", throwing)).toBe(false);
    expect(findHistoryEntry("inv-old", throwing)).toBeNull();
    expect(removeHistoryEntry("inv-old", throwing)).toBe(false);
    expect(clearHistory(throwing)).toBe(false);
  });

  it("never throws when reading window.localStorage itself throws", () => {
    const spy = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    try {
      expect(isStorageAvailable()).toBe(false);
      expect(readHistory()).toEqual([]);
      expect(saveHistoryEntry(older)).toBe(false);
      expect(clearHistory()).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it("treats a missing storage as unavailable", () => {
    expect(isStorageAvailable(null)).toBe(false);
    expect(readHistory(null)).toEqual([]);
    expect(saveHistoryEntry(older, null)).toBe(false);
  });
});

describe("makePreview", () => {
  it("keeps the first 80 characters with whitespace collapsed", () => {
    expect(makePreview("  a\n\n b  ")).toBe("a b");
    expect(Array.from(makePreview("क".repeat(200)))).toHaveLength(80);
  });

  it("does not cut a surrogate pair in half", () => {
    const preview = makePreview(`${"a".repeat(79)}😀tail`);
    expect(preview.endsWith("😀")).toBe(true);
  });
});
