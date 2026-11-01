"use client";

import { useState } from "react";
import { ApiError, downloadReport } from "@/lib/api";
import { IconDownload, IconLink } from "../Icons";

export function ReportActions({ id, token }: { id: string; token: string | null }) {
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState<"md" | "json" | null>(null);
  const [manualLink, setManualLink] = useState<string | null>(null);

  async function download(format: "md" | "json") {
    if (!token) {
      setMessage({ text: "This browser does not hold the access key for this report.", error: true });
      return;
    }
    setBusy(format);
    setMessage(null);
    try {
      await downloadReport(id, token, format);
      setMessage({ text: format === "md" ? "Markdown report downloaded." : "JSON report downloaded.", error: false });
    } catch (error) {
      setMessage({ text: error instanceof ApiError ? error.message : "The report could not be downloaded.", error: true });
    } finally {
      setBusy(null);
    }
  }

  async function copyLink() {
    const link = `${window.location.origin}/investigations/${encodeURIComponent(id)}`;
    try {
      await navigator.clipboard.writeText(link);
      setManualLink(null);
      setMessage({ text: "Link copied. It opens only in this browser, which holds the access key.", error: false });
    } catch {
      setManualLink(link);
      setMessage({ text: "Copying is blocked here. Select the link below and copy it.", error: false });
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-secondary btn-small" onClick={() => download("md")} disabled={busy !== null}>
          <IconDownload size={16} />
          {busy === "md" ? "Downloading" : "Download report (Markdown)"}
        </button>
        <button type="button" className="btn btn-secondary btn-small" onClick={() => download("json")} disabled={busy !== null}>
          <IconDownload size={16} />
          {busy === "json" ? "Downloading" : "Download report (JSON)"}
        </button>
        <button type="button" className="btn btn-secondary btn-small" onClick={copyLink}>
          <IconLink size={16} />
          Copy link
        </button>
      </div>
      <p role="status" aria-live="polite" className={`text-sm ${message?.error ? "text-fake" : "text-muted"}`}>
        {message?.text ?? ""}
      </p>
      {manualLink && (
        <div>
          <label htmlFor={`link-${id}`} className="sr-only">
            Link to this investigation
          </label>
          <input id={`link-${id}`} readOnly value={manualLink} className="field text-sm" onFocus={(e) => e.currentTarget.select()} />
        </div>
      )}
    </div>
  );
}
