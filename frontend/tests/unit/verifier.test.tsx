import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Verifier } from "@/components/verify/Verifier";
import { HISTORY_KEY } from "@/lib/config";
import { resetStatusCache } from "@/lib/useStatus";
import { fixtureReport, fixtureStatus, fixtureSteps } from "../fixtures/fixture-report";

// Mirrors Next.js, which reports window.history.replaceState through usePathname.
vi.mock("next/navigation", () => ({ usePathname: () => window.location.pathname }));

function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamResponse(text: string, chunkSize = 7): Response {
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) controller.enqueue(bytes.slice(i, i + chunkSize));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream; charset=utf-8" } });
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

let streamBody: () => Response | Promise<Response>;
let sentForm: FormData | null = null;

beforeEach(() => {
  resetStatusCache();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/verify");
  sentForm = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/status")) return json(fixtureStatus);
      if (url.endsWith("/v1/investigations/stream")) {
        sentForm = init?.body as FormData;
        return streamBody();
      }
      return json({ detail: "not found" }, 404);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Verifier", () => {
  it("streams steps, saves history, moves the URL and shows the verdict", async () => {
    streamBody = () =>
      streamResponse(
        ": keep-alive\n\n" +
          sse("created", { id: "inv-test-1", access_token: "tok-1", status: "queued", expires_at: "2026-11-07T00:00:00Z" }) +
          sse("queued", { id: "inv-test-1", message: "Fixture queue message" }) +
          sse("step", fixtureSteps[0]) +
          sse("step", fixtureSteps[1]) +
          sse("done", { id: "inv-test-1", status: "done", report: fixtureReport }),
      );
    const user = userEvent.setup();
    render(<Verifier />);

    await user.type(screen.getByLabelText("Message text"), "Fixture message to verify");
    await user.click(screen.getByLabelText(/Send the message text to the AI model/));
    await user.click(screen.getByRole("button", { name: "Run verification" }));

    expect(await screen.findByRole("heading", { name: /Verdict: FAKE/ })).toBeInTheDocument();
    expect(screen.getByText("Fixture extracting")).toBeInTheDocument();
    expect(screen.getByText("321 ms")).toBeInTheDocument();
    expect(screen.getByText(/2 new pieces of evidence/)).toBeInTheDocument();

    expect(window.location.pathname).toBe("/investigations/inv-test-1");

    const saved = JSON.parse(window.localStorage.getItem(HISTORY_KEY) ?? "[]");
    expect(saved).toEqual([
      expect.objectContaining({ id: "inv-test-1", access_token: "tok-1", text_preview: "Fixture message to verify", verdict: "FAKE" }),
    ]);

    expect(sentForm?.get("text")).toBe("Fixture message to verify");
    expect(sentForm?.get("consent_third_party_text")).toBe("true");
    expect(sentForm?.get("consent_third_party_links")).toBe("false");
    expect(sentForm?.get("consent_third_party_media")).toBe("false");
  });

  it("asks for input before sending an empty form", async () => {
    streamBody = () => streamResponse("");
    const user = userEvent.setup();
    render(<Verifier />);
    await user.click(screen.getByRole("button", { name: "Run verification" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Add message text, a link or a file to verify.");
    expect(sentForm).toBeNull();
  });

  it("shows a clear error with a retry button when the API cannot be reached", async () => {
    streamBody = () => Promise.reject(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    render(<Verifier />);
    await user.type(screen.getByLabelText("Message text"), "Fixture text");
    await user.click(screen.getByRole("button", { name: "Run verification" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not reach the Satyapan API");
    // The form keeps what was typed so the retry sends the same thing.
    expect(screen.getByLabelText("Message text")).toHaveValue("Fixture text");

    streamBody = () =>
      streamResponse(
        sse("created", { id: "inv-test-2", access_token: "tok-2", status: "queued", expires_at: "" }) +
          sse("done", { id: "inv-test-2", status: "done", report: { ...fixtureReport, verdict: "UNVERIFIED" } }),
      );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: /Verdict: UNVERIFIED/ })).toBeInTheDocument();
  });

  it("shows the server's error event", async () => {
    streamBody = () =>
      streamResponse(
        sse("created", { id: "inv-test-3", access_token: "tok-3", status: "queued", expires_at: "" }) +
          sse("error", { id: "inv-test-3", status: "error", message: "Fixture pipeline failure" }),
      );
    const user = userEvent.setup();
    render(<Verifier />);
    await user.type(screen.getByLabelText("Message text"), "x");
    await user.click(screen.getByRole("button", { name: "Run verification" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Fixture pipeline failure"));
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows the server's refusal message, such as a rate limit", async () => {
    streamBody = () => json({ error: "rate limit exceeded, try again in a minute" }, 429);
    const user = userEvent.setup();
    render(<Verifier />);
    await user.type(screen.getByLabelText("Message text"), "x");
    await user.click(screen.getByRole("button", { name: "Run verification" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("rate limit exceeded, try again in a minute");
  });

  it("rejects an over-limit file before upload, using limits from /v1/status", async () => {
    streamBody = () => streamResponse("");
    const user = userEvent.setup();
    render(<Verifier />);
    // Wait until the status limits (1 MB images) are applied to the hint.
    await screen.findByText(/Images up to 1 MB/);
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "too-big.png", { type: "image/png" });
    const small = new File([new Uint8Array(10)], "small.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Photos, video or audio"), [big, small]);
    expect(screen.getByText(/too-big\.png .*Too large/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Files to send" })).toHaveTextContent("small.png");
    expect(screen.getByRole("list", { name: "Files to send" })).not.toHaveTextContent("too-big.png");
  });
});
