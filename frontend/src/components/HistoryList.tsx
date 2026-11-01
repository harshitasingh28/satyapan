"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { formatRetention } from "@/lib/format";
import { clearHistory, type HistoryEntry, isStorageAvailable, readHistory, removeHistoryEntry } from "@/lib/history";
import { verdictTone } from "@/lib/labels";
import { useStatus } from "@/lib/useStatus";
import { IconDash, VerdictIcon } from "./Icons";
import { DateTime } from "./primitives";

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return (
      <span className="chip">
        <IconDash size={14} />
        No verdict yet
      </span>
    );
  }
  const tone = verdictTone(verdict);
  const chipTone = tone === "genuine" ? "good" : tone === "fake" ? "bad" : "warn";
  return (
    <span className="chip" data-tone={chipTone}>
      <VerdictIcon verdict={verdict} size={14} strokeWidth={2.4} />
      {verdict}
    </span>
  );
}

export function HistoryList() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState("");
  const status = useStatus();
  const retention = status.kind === "ok" ? formatRetention(status.status.retention_hours) : "the retention period";

  useEffect(() => {
    setAvailable(isStorageAvailable());
    setEntries(readHistory());
  }, []);

  function remove(entry: HistoryEntry) {
    removeHistoryEntry(entry.id);
    setEntries(readHistory());
    setNotice("Removed from this browser.");
  }

  function clearAll() {
    clearHistory();
    setEntries(readHistory());
    setConfirming(false);
    setNotice("History cleared from this browser.");
  }

  return (
    <div className="space-y-6">
      <p className="measure text-muted">
        This list is kept only in this browser. Removing an entry deletes the access key stored here, so this browser can no longer
        open that investigation. Copies on the server are deleted automatically after {retention}.
      </p>

      <p role="status" aria-live="polite" className="text-sm text-muted">
        {notice}
      </p>

      {!available && (
        <p role="alert" className="rounded-md border border-unverified bg-unverified-tint px-4 py-3 text-unverified">
          This browser is not letting Satyapan store data, for example in a private window, so history is not available. You can still
          verify messages, but keep the page open until the result appears.
        </p>
      )}

      {entries === null && <p className="text-muted">Loading history.</p>}

      {entries !== null && entries.length === 0 && available && (
        <div className="rounded-lg border border-dashed border-rule-strong p-6">
          <p className="font-medium">No investigations in this browser yet.</p>
          <p className="mt-1 text-sm text-muted">Messages you check here appear in this list so you can open them again.</p>
          <Link href="/verify" className="btn btn-primary mt-4">
            Verify a message
          </Link>
        </div>
      )}

      {entries !== null && entries.length > 0 && (
        <>
          <ul className="divide-y divide-rule border-y border-rule" aria-label="Investigations">
            {entries.map((entry) => (
              <li key={entry.id} className="grid gap-x-4 gap-y-2 py-4 sm:grid-cols-[9rem_minmax(0,1fr)_auto] sm:items-start">
                <div>
                  <VerdictBadge verdict={entry.verdict} />
                </div>
                <div className="min-w-0">
                  <Link href={`/investigations/${encodeURIComponent(entry.id)}`} className="font-medium break-anywhere">
                    {entry.text_preview || "No message text (links or files only)"}
                  </Link>
                  <p className="mt-0.5 text-sm text-muted">
                    <DateTime iso={entry.created_at} />
                  </p>
                </div>
                <div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-small"
                    onClick={() => remove(entry)}
                    aria-label={`Remove ${entry.text_preview ? `“${entry.text_preview}”` : "this investigation"} from history`}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-3">
            {!confirming ? (
              <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
                Clear all
              </button>
            ) : (
              <>
                <p className="text-sm font-medium">Remove all {entries.length} entries from this browser?</p>
                <button type="button" className="btn btn-primary btn-small" onClick={clearAll}>
                  Clear all
                </button>
                <button type="button" className="btn btn-secondary btn-small" onClick={() => setConfirming(false)}>
                  Cancel
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
