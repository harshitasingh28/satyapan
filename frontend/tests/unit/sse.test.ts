// @vitest-environment node
import { describe, expect, it } from "vitest";
import { readSseStream, type SseMessage, SseParser } from "@/lib/sse";

const STREAM =
  ": connected\n\n" +
  'event: created\ndata: {"id":"inv-1","access_token":"tok"}\n\n' +
  'event: step\ndata: {"seq":1,\ndata: "node":"extract_claims"}\n\n' +
  ": keep-alive\n" +
  'event: done\ndata: {"id":"inv-1"}\n\n';

function parseChunks(chunks: string[]): { messages: SseMessage[]; comments: number } {
  const parser = new SseParser();
  const messages: SseMessage[] = [];
  for (const chunk of chunks) messages.push(...parser.push(chunk));
  messages.push(...parser.end());
  return { messages, comments: parser.comments };
}

const EXPECTED: SseMessage[] = [
  { event: "created", data: '{"id":"inv-1","access_token":"tok"}' },
  { event: "step", data: '{"seq":1,\n"node":"extract_claims"}' },
  { event: "done", data: '{"id":"inv-1"}' },
];

describe("SseParser", () => {
  it("parses named events and skips comments", () => {
    const { messages, comments } = parseChunks([STREAM]);
    expect(messages).toEqual(EXPECTED);
    expect(comments).toBe(2);
  });

  it("joins multi-line data with a newline, giving valid JSON", () => {
    const { messages } = parseChunks([STREAM]);
    expect(JSON.parse(messages[1]!.data)).toEqual({ seq: 1, node: "extract_claims" });
  });

  it("gives the same result when a chunk boundary falls anywhere, including mid-event", () => {
    for (let i = 1; i < STREAM.length; i += 1) {
      expect(parseChunks([STREAM.slice(0, i), STREAM.slice(i)]).messages).toEqual(EXPECTED);
    }
  });

  it("handles one character per chunk", () => {
    expect(parseChunks(STREAM.split("")).messages).toEqual(EXPECTED);
  });

  it("handles CRLF and lone CR line endings, even when \\r and \\n arrive in separate chunks", () => {
    const crlf = STREAM.replace(/\n/g, "\r\n");
    for (let i = 1; i < crlf.length; i += 1) {
      expect(parseChunks([crlf.slice(0, i), crlf.slice(i)]).messages).toEqual(EXPECTED);
    }
    const cr = STREAM.replace(/\n/g, "\r");
    expect(parseChunks([cr]).messages).toEqual(EXPECTED);
  });

  it("does not dispatch comment-only blocks or events without data", () => {
    const { messages, comments } = parseChunks([": ping\n\n: ping\n\nevent: step\n\n"]);
    expect(messages).toEqual([]);
    expect(comments).toBe(2);
  });

  it("uses 'message' when no event name is given and strips one leading space only", () => {
    const { messages } = parseChunks(["data:  two spaces\n\ndata:none\n\n"]);
    expect(messages).toEqual([
      { event: "message", data: " two spaces" },
      { event: "message", data: "none" },
    ]);
  });

  it("delivers a last event that has no closing blank line when the stream ends", () => {
    const { messages } = parseChunks(['event: done\ndata: {"id":"x"}']);
    expect(messages).toEqual([{ event: "done", data: '{"id":"x"}' }]);
  });

  it("ignores a leading byte order mark", () => {
    const { messages } = parseChunks(["﻿event: queued\ndata: {}\n\n"]);
    expect(messages).toEqual([{ event: "queued", data: "{}" }]);
  });
});

function streamOf(parts: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(part);
      controller.close();
    },
  });
}

describe("readSseStream", () => {
  it("decodes Hindi and Telugu correctly when a multi-byte character is split across chunks", async () => {
    const text = 'event: step\ndata: {"label":"దావాలను గుర్తించడం और दावे"}\n\n';
    const bytes = new TextEncoder().encode(text);
    for (let i = 1; i < bytes.length; i += 1) {
      const received: SseMessage[] = [];
      await readSseStream(streamOf([bytes.slice(0, i), bytes.slice(i)]), { onMessage: (m) => received.push(m) });
      expect(received).toHaveLength(1);
      expect(JSON.parse(received[0]!.data)).toEqual({ label: "దావాలను గుర్తించడం और दावे" });
    }
  });

  it("reports activity for keep-alive chunks", async () => {
    let activity = 0;
    const enc = new TextEncoder();
    await readSseStream(streamOf([enc.encode(": keep-alive\n\n"), enc.encode(": keep-alive\n\n")]), {
      onMessage: () => undefined,
      onActivity: () => {
        activity += 1;
      },
    });
    expect(activity).toBe(2);
  });
});
