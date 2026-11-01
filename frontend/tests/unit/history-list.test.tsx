import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HistoryList } from "@/components/HistoryList";
import { HISTORY_KEY } from "@/lib/config";
import { resetStatusCache } from "@/lib/useStatus";
import { fixtureStatus } from "../fixtures/fixture-report";

beforeEach(() => {
  resetStatusCache();
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(fixtureStatus), { headers: { "content-type": "application/json" } })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("HistoryList", () => {
  it("lists entries newest first with verdict words, and removes one", async () => {
    window.localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([
        { id: "a", access_token: "t", created_at: "2026-10-30T10:00:00Z", text_preview: "Older fixture", verdict: "GENUINE" },
        { id: "b", access_token: "t", created_at: "2026-10-31T10:00:00Z", text_preview: "Newer fixture", verdict: null },
      ]),
    );
    const user = userEvent.setup();
    render(<HistoryList />);
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Newer fixture");
    expect(items[0]).toHaveTextContent("No verdict yet");
    expect(items[1]).toHaveTextContent("GENUINE");
    expect(screen.getByRole("link", { name: "Older fixture" })).toHaveAttribute("href", "/investigations/a");
    // Retention from /v1/status: 168 hours
    expect(await screen.findByText(/deleted automatically after 7 days/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Remove “Older fixture”/ }));
    expect(screen.queryByText("Older fixture")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(HISTORY_KEY) ?? "[]")).toHaveLength(1);
  });

  it("asks for confirmation before clearing all", async () => {
    window.localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([{ id: "a", access_token: "t", created_at: "2026-10-30T10:00:00Z", text_preview: "x", verdict: "FAKE" }]),
    );
    const user = userEvent.setup();
    render(<HistoryList />);
    await user.click(await screen.findByRole("button", { name: "Clear all" }));
    expect(screen.getByText(/Remove all 1 entries/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(window.localStorage.getItem(HISTORY_KEY)).toBeNull();
  });

  it("renders a plain explanation when storage is unavailable", async () => {
    const spy = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    try {
      render(<HistoryList />);
      expect(await screen.findByRole("alert")).toHaveTextContent("not letting Satyapan store data");
    } finally {
      spy.mockRestore();
    }
  });
});
