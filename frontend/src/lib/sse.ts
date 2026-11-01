// A small text/event-stream parser. EventSource cannot send a POST body, so the
// stream is read from fetch() and parsed here, following the WHATWG rules:
// lines end in \n, \r\n or \r, a blank line dispatches the event, lines
// starting with ":" are comments, repeated "data:" lines join with "\n".

export type SseMessage = { event: string; data: string; id?: string };

export class SseParser {
  private buffer = "";
  private eventName = "";
  private dataLines: string[] = [];
  private lastId: string | undefined;
  private started = false;
  /** Number of ":" comment lines seen (keep-alives). */
  comments = 0;

  /** Feed decoded text. Returns every message completed by this chunk. */
  push(chunk: string): SseMessage[] {
    if (!this.started) {
      this.started = true;
      if (chunk.charCodeAt(0) === 0xfeff) chunk = chunk.slice(1);
    }
    this.buffer += chunk;
    const out: SseMessage[] = [];
    let lineStart = 0;
    let i = 0;
    while (i < this.buffer.length) {
      const code = this.buffer.charCodeAt(i);
      if (code === 10 || code === 13) {
        // A trailing \r may be the first half of \r\n split across chunks: wait for more.
        if (code === 13 && i + 1 >= this.buffer.length) break;
        const line = this.buffer.slice(lineStart, i);
        if (code === 13 && this.buffer.charCodeAt(i + 1) === 10) i += 1;
        lineStart = i + 1;
        this.processLine(line, out);
      }
      i += 1;
    }
    this.buffer = this.buffer.slice(lineStart);
    return out;
  }

  /**
   * Call when the stream ends. A last event that the server did not finish
   * with a blank line is still delivered, so a final "done" is never dropped.
   */
  end(): SseMessage[] {
    const out: SseMessage[] = [];
    let rest = this.buffer;
    this.buffer = "";
    if (rest.endsWith("\r")) rest = rest.slice(0, -1);
    if (rest.length > 0) this.processLine(rest, out);
    this.dispatch(out);
    return out;
  }

  private processLine(line: string, out: SseMessage[]): void {
    if (line === "") {
      this.dispatch(out);
      return;
    }
    if (line.startsWith(":")) {
      this.comments += 1;
      return;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        this.eventName = value;
        break;
      case "data":
        this.dataLines.push(value);
        break;
      case "id":
        if (!value.includes("\u0000")) this.lastId = value;
        break;
      default:
        // "retry" and unknown fields are ignored.
        break;
    }
  }

  private dispatch(out: SseMessage[]): void {
    if (this.dataLines.length > 0) {
      const message: SseMessage = { event: this.eventName || "message", data: this.dataLines.join("\n") };
      if (this.lastId !== undefined) message.id = this.lastId;
      out.push(message);
    }
    this.eventName = "";
    this.dataLines = [];
  }
}

export type ReadSseOptions = {
  onMessage: (message: SseMessage) => void;
  /** Called for every chunk of bytes, including keep-alive comments. */
  onActivity?: () => void;
};

/** Reads a byte stream to the end, decoding UTF-8 safely across chunk boundaries. */
export async function readSseStream(stream: ReadableStream<Uint8Array>, options: ReadSseOptions): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      options.onActivity?.();
      if (value && value.byteLength > 0) {
        for (const message of parser.push(decoder.decode(value, { stream: true }))) options.onMessage(message);
      }
    }
    const tail = decoder.decode();
    if (tail) for (const message of parser.push(tail)) options.onMessage(message);
    for (const message of parser.end()) options.onMessage(message);
  } finally {
    reader.releaseLock();
  }
}
