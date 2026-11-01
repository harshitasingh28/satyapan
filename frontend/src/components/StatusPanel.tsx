"use client";

import { API_BASE } from "@/lib/config";
import { formatNumber, formatRetention } from "@/lib/format";
import { integrationLabel } from "@/lib/labels";
import { useStatus } from "@/lib/useStatus";
import { IconAlert, IconCheck, IconDash } from "./Icons";

export function StatusPanel({ headingLevel = 2 }: { headingLevel?: 2 | 3 }) {
  const state = useStatus();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const Sub = headingLevel === 2 ? "h3" : "h4";

  return (
    <section aria-labelledby="status-heading" className="rounded-lg border border-rule bg-surface p-5">
      <Heading id="status-heading" className="text-lg font-semibold">
        System status
      </Heading>

      {state.kind === "loading" && (
        <p className="mt-3 flex items-center gap-2 text-sm text-muted" role="status">
          <span className="spinner" aria-hidden="true" />
          Checking the Satyapan API.
        </p>
      )}

      {state.kind === "error" && (
        <div className="mt-3 space-y-3 text-sm" role="alert">
          <p className="flex items-start gap-2 text-fake">
            <IconAlert size={18} className="mt-0.5 flex-none" />
            <span>
              The Satyapan API is not reachable, so verification will not work right now.
              <span className="mt-1 block text-muted">{state.message}</span>
            </span>
          </p>
          <button type="button" className="btn btn-secondary btn-small" onClick={state.reload}>
            Check again
          </button>
        </div>
      )}

      {state.kind === "ok" && (
        <div className="mt-3 space-y-5 text-sm">
          <p className="text-muted">
            Connected to <span className="break-anywhere">{API_BASE}</span>, version {state.status.version}. Records are kept in{" "}
            {state.status.store === "mongo" ? "MongoDB" : "local JSON files"} and deleted after{" "}
            {formatRetention(state.status.retention_hours)}.
          </p>

          <div>
            <Sub className="font-sans text-base font-semibold text-ink">Outside services</Sub>
            {Object.keys(state.status.integrations).length === 0 ? (
              <p className="mt-1 text-muted">The server lists no outside services.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {Object.entries(state.status.integrations).map(([key, on]) => (
                  <li key={key} className="flex items-start justify-between gap-3">
                    <span>{integrationLabel(key)}</span>
                    <span className={`flex flex-none items-center gap-1 ${on ? "text-genuine" : "text-muted"}`}>
                      {on ? <IconCheck size={16} /> : <IconDash size={16} />}
                      {on ? "Configured" : "Not configured"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <Sub className="font-sans text-base font-semibold text-ink">Models</Sub>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
              <dt className="text-muted">Chat</dt>
              <dd className="break-anywhere">{state.status.models.chat ?? "None"}</dd>
              <dt className="text-muted">Chat fallback</dt>
              <dd className="break-anywhere">{state.status.models.chat_fallback ?? "None"}</dd>
              <dt className="text-muted">Embeddings</dt>
              <dd className="break-anywhere">{state.status.models.embedding ?? "None"}</dd>
              {state.status.providers?.chat && (
                <>
                  <dt className="text-muted">Text sent to</dt>
                  <dd className="break-anywhere">
                    {[state.status.providers.chat, state.status.providers.chat_fallback, state.status.providers.embedding]
                      .filter((h, i, all): h is string => Boolean(h) && all.indexOf(h) === i)
                      .join(", ")}
                  </dd>
                </>
              )}
            </dl>
          </div>

          <div>
            <Sub className="font-sans text-base font-semibold text-ink">Reference data</Sub>
            <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5">
              <dt className="text-muted">Official press releases</dt>
              <dd className="tabular text-right">{formatNumber(state.status.corpus.pib_releases)}</dd>
              <dt className="text-muted">Fact-checked claims</dt>
              <dd className="tabular text-right">{formatNumber(state.status.corpus.known_claims)}</dd>
              <dt className="text-muted">Known images</dt>
              <dd className="tabular text-right">{formatNumber(state.status.corpus.known_images)}</dd>
              <dt className="text-muted">Known audio clips</dt>
              <dd className="tabular text-right">{formatNumber(state.status.corpus.known_audio)}</dd>
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}
