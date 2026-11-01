"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  ApiError,
  getInvestigation,
  getInvestigationEvents,
  isAbort,
  POLL_INTERVAL_MS,
  streamInvestigation,
  wait,
} from "@/lib/api";
import { FALLBACK_LIMITS, parseLinks } from "@/lib/files";
import { makePreview, saveHistoryEntry, updateHistoryVerdict } from "@/lib/history";
import { announce, buildTraceRows, mergeSteps } from "@/lib/trace";
import type { Report, StepEvent } from "@/lib/types";
import { useStatus } from "@/lib/useStatus";
import { IconAlert } from "../Icons";
import { ResultView } from "../result/ResultView";
import { WorkflowTrace } from "../WorkflowTrace";
import { EMPTY_FORM, type FormValues, VerifyForm } from "./VerifyForm";

type Phase = "idle" | "running" | "done" | "failed";

type RunState = {
  phase: Phase;
  id: string | null;
  token: string | null;
  queuedMessage: string | null;
  steps: StepEvent[];
  announcement: string;
  report: Report | null;
  error: string | null;
  /** True when the server has the investigation, so "try again" should resume instead of resubmitting. */
  resumable: boolean;
  /** True once the live stream was lost and the page fell back to polling. */
  polling: boolean;
};

type Action =
  | { type: "submit" }
  | { type: "created"; id: string; token: string }
  | { type: "queued"; message: string }
  | { type: "step"; step: StepEvent }
  | { type: "steps"; steps: StepEvent[] }
  | { type: "polling" }
  | { type: "done"; report: Report }
  | { type: "failed"; message: string; resumable: boolean }
  | { type: "reset" };

const INITIAL: RunState = {
  phase: "idle",
  id: null,
  token: null,
  queuedMessage: null,
  steps: [],
  announcement: "",
  report: null,
  error: null,
  resumable: false,
  polling: false,
};

function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case "submit":
      return { ...INITIAL, phase: "running", announcement: "Sending the message to Satyapan." };
    case "created":
      return { ...state, id: action.id, token: action.token, announcement: "Investigation created. Waiting for the first step." };
    case "queued":
      return { ...state, queuedMessage: action.message, announcement: action.message };
    case "step":
      return { ...state, queuedMessage: null, steps: mergeSteps(state.steps, [action.step]), announcement: announce(action.step) };
    case "steps":
      return { ...state, steps: mergeSteps(state.steps, action.steps) };
    case "polling":
      return { ...state, phase: "running", error: null, polling: true };
    case "done":
      return { ...state, phase: "done", report: action.report, queuedMessage: null, announcement: `Verdict: ${action.report.verdict}.` };
    case "failed":
      return { ...state, phase: "failed", error: action.message, resumable: action.resumable, queuedMessage: null };
    case "reset":
      return INITIAL;
  }
}

function buildForm(values: FormValues): FormData {
  const form = new FormData();
  form.append("text", values.text);
  form.append("links", parseLinks(values.links).join("\n"));
  for (const file of values.files) form.append("files", file, file.name);
  form.append("consent_third_party_text", String(values.consentText));
  form.append("consent_third_party_links", String(values.consentLinks));
  form.append("consent_third_party_media", String(values.consentMedia));
  return form;
}

export function Verifier() {
  const status = useStatus();
  const limits = status.kind === "ok" ? status.status.limits : FALLBACK_LIMITS;
  const [values, setValues] = useState<FormValues>(EMPTY_FORM);
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const abortRef = useRef<AbortController | null>(null);
  const movedUrl = useRef(false);
  const pathname = usePathname();

  useEffect(() => () => abortRef.current?.abort(), []);

  const finish = useCallback((report: Report, id: string) => {
    updateHistoryVerdict(id, report.verdict);
    dispatch({ type: "done", report });
  }, []);

  /** Polls the stored record every 2 s until it settles. Used when the live stream is lost. */
  const resume = useCallback(
    async (id: string, token: string, signal: AbortSignal) => {
      dispatch({ type: "polling" });
      for (;;) {
        const [record, events] = await Promise.all([
          getInvestigation(id, token, signal),
          getInvestigationEvents(id, token, signal).catch((error: unknown) => {
            if (isAbort(error)) throw error;
            return null;
          }),
        ]);
        if (events) dispatch({ type: "steps", steps: events });
        if (record.status === "done" && record.report) {
          finish(record.report, id);
          return;
        }
        if (record.status === "error" || record.status === "interrupted") {
          dispatch({
            type: "failed",
            message:
              record.status === "interrupted"
                ? "The investigation was interrupted on the server before it finished."
                : `The investigation failed on the server${record.error ? `: ${record.error}` : "."}`,
            resumable: false,
          });
          return;
        }
        await wait(POLL_INTERVAL_MS, signal);
      }
    },
    [finish],
  );

  const start = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const created: { current: { id: string; token: string } | null } = { current: null };
    dispatch({ type: "submit" });

    try {
      const outcome = await streamInvestigation(
        buildForm(values),
        {
          onCreated: (e) => {
            created.current = { id: e.id, token: e.access_token };
            saveHistoryEntry({
              id: e.id,
              access_token: e.access_token,
              created_at: new Date().toISOString(),
              text_preview: makePreview(values.text),
              verdict: null,
            });
            // Give the investigation its own address without leaving this page,
            // so the live stream keeps running.
            try {
              window.history.replaceState(window.history.state, "", `/investigations/${encodeURIComponent(e.id)}`);
              movedUrl.current = true;
            } catch {
              // Some embedded browsers block history changes. The stream still works.
            }
            dispatch({ type: "created", id: e.id, token: e.access_token });
          },
          onQueued: (e) => dispatch({ type: "queued", message: e.message || "Waiting for other investigations to finish." }),
          onStep: (e) => dispatch({ type: "step", step: e }),
          onDone: (e) => finish(e.report, e.id),
          onError: (e) => dispatch({ type: "failed", message: e.message, resumable: false }),
        },
        { signal: controller.signal },
      );
      if (outcome === "ended") {
        if (created.current) await resume(created.current.id, created.current.token, controller.signal);
        else
          dispatch({
            type: "failed",
            message: "The connection closed before the server confirmed the investigation. Nothing was saved.",
            resumable: false,
          });
      }
    } catch (error) {
      if (isAbort(error) && controller.signal.aborted) return;
      dispatch({
        type: "failed",
        message: error instanceof ApiError ? error.message : "Something went wrong while sending the message.",
        resumable: created.current !== null,
      });
    }
  }, [values, finish, resume]);

  const retry = useCallback(() => {
    if (state.resumable && state.id && state.token) {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      resume(state.id, state.token, controller.signal).catch((error: unknown) => {
        if (isAbort(error)) return;
        dispatch({
          type: "failed",
          message: error instanceof ApiError ? error.message : "The investigation could not be checked.",
          resumable: true,
        });
      });
    } else {
      void start();
    }
  }, [state.resumable, state.id, state.token, resume, start]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "reset" });
    setValues(EMPTY_FORM);
    if (movedUrl.current) {
      movedUrl.current = false;
      try {
        window.history.replaceState(window.history.state, "", "/verify");
      } catch {
        // Ignore: only the address bar is affected.
      }
    }
  }, []);

  // The header's "Verify" link points at this page. When the address was
  // moved to /investigations/{id} and the person then navigates back to
  // /verify, show a fresh form, unless an investigation is still running.
  // Only a real change of pathname back to /verify counts, so nothing resets
  // if the router does not report the replaceState above.
  const previousPath = useRef(pathname);
  useEffect(() => {
    const before = previousPath.current;
    previousPath.current = pathname;
    if (movedUrl.current && before !== pathname && pathname === "/verify" && state.phase !== "running") {
      movedUrl.current = false;
      dispatch({ type: "reset" });
      setValues(EMPTY_FORM);
    }
  }, [pathname, state.phase]);

  const rows = useMemo(() => buildTraceRows(state.steps), [state.steps]);
  const evidenceIds = useMemo(() => new Set((state.report?.evidence ?? []).map((e) => e.id)), [state.report]);
  const showForm = state.phase === "idle" || (state.phase === "failed" && !state.id);

  return (
    <div className="space-y-10">
      {state.phase === "failed" && state.error && (
        <div role="alert" className="rounded-lg border border-fake bg-fake-tint p-4 text-fake sm:p-5">
          <p className="flex items-start gap-2 font-semibold">
            <IconAlert size={20} className="mt-0.5 flex-none" />
            {state.resumable ? "The live connection was lost" : "The verification did not finish"}
          </p>
          <p className="mt-1 break-anywhere">{state.error}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary btn-small" onClick={retry}>
              {state.resumable ? "Check progress again" : "Try again"}
            </button>
            {state.id && (
              <button type="button" className="btn btn-secondary btn-small" onClick={reset}>
                Start a new verification
              </button>
            )}
          </div>
        </div>
      )}

      {showForm ? (
        <VerifyForm
          values={values}
          onChange={setValues}
          onSubmit={() => void start()}
          limits={limits}
          limitsKnown={status.kind === "ok"}
          busy={false}
          aiHost={status.kind === "ok" ? status.status.providers?.chat ?? null : null}
        />
      ) : (
        <SubmittedSummary values={values} />
      )}

      {state.phase !== "idle" && (state.steps.length > 0 || state.phase === "running") && (
        <WorkflowTrace
          rows={rows}
          running={state.phase === "running"}
          queuedMessage={state.queuedMessage}
          announcement={state.announcement}
          evidenceIds={evidenceIds}
        />
      )}

      {state.phase === "running" && state.polling && (
        <p className="text-sm text-muted" role="status">
          The live connection closed, so this page is checking the saved investigation every 2 seconds.
        </p>
      )}

      {state.phase === "done" && state.report && state.id && (
        <>
          <ResultView report={state.report} id={state.id} token={state.token} focusOnMount />
          <div className="border-t border-rule pt-6">
            <button type="button" className="btn btn-secondary" onClick={reset}>
              Check another message
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function SubmittedSummary({ values }: { values: FormValues }) {
  const links = parseLinks(values.links).length;
  const parts = [
    values.text.trim() ? `message text (${values.text.length} characters)` : null,
    links ? `${links} ${links === 1 ? "link" : "links"}` : null,
    values.files.length ? `${values.files.length} ${values.files.length === 1 ? "file" : "files"}` : null,
  ].filter(Boolean);
  const allowed = [
    values.consentText ? "text to AI and fact check services" : null,
    values.consentLinks ? "links to link checkers" : null,
    values.consentMedia ? "media to media services" : null,
  ].filter(Boolean);
  return (
    <div className="rounded-lg border border-rule bg-surface p-4 text-sm sm:p-5">
      <p>
        <span className="font-semibold">Sent: </span>
        {parts.join(", ") || "nothing"}.
      </p>
      <p className="mt-1 text-muted">
        {allowed.length > 0 ? `You allowed: ${allowed.join(", ")}.` : "You did not allow any outside services."}
      </p>
    </div>
  );
}
