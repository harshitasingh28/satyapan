import { API_BASE } from "./config";
import { readSseStream, type SseMessage } from "./sse";
import type { CreatedEvent, DoneEvent, ErrorEvent, InvestigationRecord, QueuedEvent, Status, StepEvent } from "./types";

export class ApiError extends Error {
  /** HTTP status, or 0 when the server could not be reached. */
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

function unreachable(): ApiError {
  return new ApiError(0, `Could not reach the Satyapan API at ${API_BASE}. Check your connection, then try again.`);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Turns {"detail": ...} or {"error": ...} into one readable sentence. */
async function errorFrom(res: Response): Promise<ApiError> {
  let message = "";
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const b = body as Record<string, unknown>;
      const raw = b.detail ?? b.error;
      if (typeof raw === "string") message = raw;
      else if (Array.isArray(raw)) {
        message = raw
          .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : String(item)))
          .join(" ");
      }
    }
  } catch {
    // Not JSON: fall through to the generic message.
  }
  if (res.status === 404) message = "Not found. It may have expired, or this browser does not hold its access key.";
  if (res.status === 413 && !message) message = "The upload is larger than the server accepts.";
  if (res.status === 429 && !message) message = "Too many requests. Wait a minute, then try again.";
  return new ApiError(res.status, message || `The server answered with status ${res.status}.`);
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch (error) {
    if (isAbort(error)) throw error;
    throw unreachable();
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await request(path, { ...init, headers: { Accept: "application/json", ...(init?.headers ?? {}) } });
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, "The server sent a response this page could not read.");
  }
}

const idPath = (id: string) => `/v1/investigations/${encodeURIComponent(id)}`;
const tokenHeader = (token: string) => ({ "X-Access-Token": token });

export function getStatus(signal?: AbortSignal): Promise<Status> {
  return getJson<Status>("/v1/status", { signal });
}

export function getInvestigation(id: string, token: string, signal?: AbortSignal): Promise<InvestigationRecord> {
  return getJson<InvestigationRecord>(idPath(id), { headers: tokenHeader(token), signal });
}

export async function getInvestigationEvents(id: string, token: string, signal?: AbortSignal): Promise<StepEvent[]> {
  const body = await getJson<{ events?: unknown }>(`${idPath(id)}/events`, { headers: tokenHeader(token), signal });
  return Array.isArray(body.events) ? body.events.filter(isStepEvent) : [];
}

/** Fetches report.md or report.json with the token header and saves it through a Blob. */
export async function downloadReport(id: string, token: string, format: "md" | "json"): Promise<void> {
  const res = await request(`${idPath(id)}/report.${format}`, { headers: tokenHeader(token) });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = `satyapan-${id}.${format}`;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Give the browser a moment to start the download before the URL is released.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
}

export function isStepEvent(value: unknown): value is StepEvent {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.seq === "number" && typeof v.node === "string" && (v.phase === "start" || v.phase === "end");
}

export type StreamHandlers = {
  onCreated: (event: CreatedEvent) => void;
  onQueued: (event: QueuedEvent) => void;
  onStep: (event: StepEvent) => void;
  onDone: (event: DoneEvent) => void;
  onError: (event: ErrorEvent) => void;
};

export type StreamOutcome = "done" | "error" | "ended";

function parseData(message: SseMessage): unknown {
  try {
    return JSON.parse(message.data);
  } catch {
    return undefined;
  }
}

/**
 * POSTs the form and reads the event stream until it closes.
 * Resolves "done" or "error" when the server sent that event, or "ended" when
 * the connection closed without either (the caller can then poll the record).
 * Throws ApiError when the request is refused or the network fails.
 */
export async function streamInvestigation(
  form: FormData,
  handlers: StreamHandlers,
  options: { signal?: AbortSignal; idleTimeoutMs?: number } = {},
): Promise<StreamOutcome> {
  const controller = new AbortController();
  const outer = options.signal;
  const forwardAbort = () => controller.abort();
  if (outer) {
    if (outer.aborted) controller.abort();
    else outer.addEventListener("abort", forwardAbort, { once: true });
  }

  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let idleExpired = false;
  const idleMs = options.idleTimeoutMs ?? 60_000;
  const touch = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      idleExpired = true;
      controller.abort();
    }, idleMs);
  };

  let outcome: StreamOutcome = "ended";
  let created = false;
  try {
    const res = await request("/v1/investigations/stream", {
      method: "POST",
      body: form,
      headers: { Accept: "text/event-stream" },
      signal: controller.signal,
    });
    const type = res.headers.get("content-type") ?? "";
    if (!type.includes("text/event-stream") || !res.body) {
      throw new ApiError(res.status, "The server did not send a live event stream for this request.");
    }
    touch();
    await readSseStream(res.body, {
      onActivity: touch,
      onMessage: (message) => {
        const data = parseData(message);
        if (!data || typeof data !== "object") return;
        const d = data as Record<string, unknown>;
        switch (message.event) {
          case "created":
            if (typeof d.id === "string" && typeof d.access_token === "string") {
              created = true;
              handlers.onCreated(data as CreatedEvent);
            }
            break;
          case "queued":
            handlers.onQueued(data as QueuedEvent);
            break;
          case "step":
            if (isStepEvent(data)) handlers.onStep(data);
            break;
          case "done":
            if (d.report && typeof d.report === "object") {
              outcome = "done";
              handlers.onDone(data as DoneEvent);
            }
            break;
          case "error":
            outcome = "error";
            handlers.onError({
              id: typeof d.id === "string" ? d.id : null,
              status: "error",
              message: typeof d.message === "string" && d.message ? d.message : "The investigation failed on the server.",
            });
            break;
          default:
            break;
        }
      },
    });
  } catch (error) {
    if (outcome !== "ended") return outcome;
    if (error instanceof ApiError) throw error;
    if (isAbort(error) && !idleExpired && outer?.aborted) throw error;
    // Network drop, or no bytes for too long. Once the server has created the
    // record, the caller can resume by polling it, so report "ended".
    if (idleExpired || created) return "ended";
    throw unreachable();
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
    outer?.removeEventListener("abort", forwardAbort);
  }
  return outcome;
}

export const POLL_INTERVAL_MS = 2000;

/** Waits ms, or rejects with AbortError when the signal fires. */
export function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export { isAbort };
