"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ApiError, getInvestigation, getInvestigationEvents, isAbort, POLL_INTERVAL_MS, wait } from "@/lib/api";
import { formatRetention } from "@/lib/format";
import { findHistoryEntry, removeHistoryEntry, updateHistoryVerdict } from "@/lib/history";
import { buildTraceRows, mergeSteps } from "@/lib/trace";
import type { InvestigationRecord, StepEvent } from "@/lib/types";
import { useStatus } from "@/lib/useStatus";
import { IconAlert } from "./Icons";
import { DateTime } from "./primitives";
import { ResultView } from "./result/ResultView";
import { WorkflowTrace } from "./WorkflowTrace";

type ViewState =
  | { kind: "loading" }
  | { kind: "no-token" }
  | { kind: "not-found" }
  | { kind: "error"; message: string }
  | { kind: "record"; record: InvestigationRecord };

export function InvestigationView({ id }: { id: string }) {
  const [view, setView] = useState<ViewState>({ kind: "loading" });
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [removed, setRemoved] = useState(false);
  const status = useStatus();

  useEffect(() => {
    const entry = findHistoryEntry(id);
    if (!entry) {
      setView({ kind: "no-token" });
      return;
    }
    setToken(entry.access_token);
    const controller = new AbortController();
    const { signal } = controller;

    (async () => {
      try {
        for (;;) {
          const [record, events] = await Promise.all([
            getInvestigation(id, entry.access_token, signal),
            getInvestigationEvents(id, entry.access_token, signal).catch((error: unknown) => {
              if (isAbort(error)) throw error;
              return null;
            }),
          ]);
          if (events) setSteps((prev) => mergeSteps(prev, events));
          setView({ kind: "record", record });
          if (record.status === "done" && record.report) {
            updateHistoryVerdict(id, record.report.verdict);
            return;
          }
          if (record.status !== "queued" && record.status !== "running") return;
          await wait(POLL_INTERVAL_MS, signal);
        }
      } catch (error) {
        if (isAbort(error)) return;
        if (error instanceof ApiError && error.status === 404) setView({ kind: "not-found" });
        else setView({ kind: "error", message: error instanceof ApiError ? error.message : "The investigation could not be loaded." });
      }
    })();

    return () => controller.abort();
  }, [id, attempt]);

  const rows = useMemo(() => buildTraceRows(steps), [steps]);
  const record = view.kind === "record" ? view.record : null;
  const evidenceIds = useMemo(() => new Set((record?.report?.evidence ?? []).map((e) => e.id)), [record]);
  const retention = status.kind === "ok" ? formatRetention(status.status.retention_hours) : "the retention period";

  if (view.kind === "loading") {
    return (
      <div className="page py-12">
        <h1 className="text-2xl font-semibold">Investigation</h1>
        <p className="mt-4 flex items-center gap-2 text-muted" role="status">
          <span className="spinner" aria-hidden="true" />
          Loading the investigation.
        </p>
      </div>
    );
  }

  if (view.kind === "no-token") {
    return (
      <div className="page py-12">
        <h1 className="measure text-2xl font-semibold">This investigation is private to the browser that created it</h1>
        <div className="mt-4 measure space-y-3">
          <p>
            Each investigation has an access key that is stored only in the browser that sent the message. This browser does not have
            the key for this one, so it cannot be opened here.
          </p>
          <p>Open the link in the browser you used, or check the message again here.</p>
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/verify" className="btn btn-primary">
            Verify a message
          </Link>
          <Link href="/history" className="btn btn-secondary">
            Open your history
          </Link>
        </div>
      </div>
    );
  }

  if (view.kind === "not-found") {
    return (
      <div className="page py-12">
        <h1 className="measure text-2xl font-semibold">This investigation is no longer available</h1>
        <p className="mt-4 measure">
          The server did not find it. Server copies are deleted automatically after {retention}, so it has probably expired.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/verify" className="btn btn-primary">
            Verify the message again
          </Link>
          {!removed ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                removeHistoryEntry(id);
                setRemoved(true);
              }}
            >
              Remove from history
            </button>
          ) : (
            <p className="self-center text-sm text-muted" role="status">
              Removed from this browser’s history.
            </p>
          )}
        </div>
      </div>
    );
  }

  if (view.kind === "error") {
    return (
      <div className="page py-12">
        <h1 className="text-2xl font-semibold">Investigation</h1>
        <div role="alert" className="mt-6 rounded-lg border border-fake bg-fake-tint p-4 text-fake sm:p-5">
          <p className="flex items-start gap-2 font-semibold">
            <IconAlert size={20} className="mt-0.5 flex-none" />
            The investigation could not be loaded
          </p>
          <p className="mt-1">{view.message}</p>
          <button type="button" className="btn btn-primary btn-small mt-3" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  const rec = view.record;
  const running = rec.status === "queued" || rec.status === "running";

  return (
    <div className="page space-y-10 py-10">
      <header>
        <h1 className="text-2xl font-semibold">Investigation</h1>
        <p className="mt-2 break-anywhere text-sm text-muted">
          {rec.id}. Started <DateTime iso={rec.created_at} />. The server copy is deleted after <DateTime iso={rec.expires_at} />.
        </p>
      </header>

      {running && (
        <>
          <p className="text-muted" role="status">
            {rec.status === "queued" ? "Waiting for other investigations to finish." : "Still running."} This page checks again every 2
            seconds.
          </p>
          <WorkflowTrace rows={rows} running />
        </>
      )}

      {(rec.status === "error" || rec.status === "interrupted") && (
        <div role="alert" className="rounded-lg border border-fake bg-fake-tint p-4 text-fake sm:p-5">
          <p className="flex items-start gap-2 font-semibold">
            <IconAlert size={20} className="mt-0.5 flex-none" />
            {rec.status === "interrupted" ? "The investigation was interrupted before it finished" : "The investigation failed"}
          </p>
          {rec.error && <p className="mt-1 break-anywhere">{rec.error}</p>}
          <Link href="/verify" className="btn btn-primary btn-small mt-3">
            Verify the message again
          </Link>
        </div>
      )}

      {rec.status === "done" && rec.report && (
        <>
          <ResultView report={rec.report} id={rec.id} token={token} />
          <details className="group">
            <summary className="cursor-pointer text-md font-semibold text-accent">
              Show the workflow trace ({rows.length} {rows.length === 1 ? "step" : "steps"})
            </summary>
            <div className="mt-4">
              <WorkflowTrace rows={rows} running={false} evidenceIds={evidenceIds} />
            </div>
          </details>
        </>
      )}

      {rec.status === "done" && !rec.report && (
        <p role="alert">The server marked this investigation as done but sent no report.</p>
      )}
    </div>
  );
}
