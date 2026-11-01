"use client";

import { type ChangeEvent, type FormEvent, useId, useRef, useState } from "react";
import { ACCEPT_ATTRIBUTE, mediaKindOf, parseLinks, type RejectedFile, validateFiles } from "@/lib/files";
import { formatBytes, formatNumber } from "@/lib/format";
import type { Limits } from "@/lib/types";
import { MediaIcon } from "../Icons";

export type FormValues = {
  text: string;
  links: string;
  files: File[];
  consentText: boolean;
  consentLinks: boolean;
  consentMedia: boolean;
};

export const EMPTY_FORM: FormValues = {
  text: "",
  links: "",
  files: [],
  consentText: false,
  consentLinks: false,
  consentMedia: false,
};

type Props = {
  values: FormValues;
  onChange: (values: FormValues) => void;
  onSubmit: () => void;
  limits: Limits;
  limitsKnown: boolean;
  busy: boolean;
  aiHost?: string | null;
};

const PROVIDER_NAMES: Record<string, string> = {
  "router.huggingface.co": "Hugging Face",
  "api.cloudflare.com": "Cloudflare Workers AI",
  "generativelanguage.googleapis.com": "Google Gemini",
  "api.groq.com": "Groq",
};

export function providerName(host: string | null | undefined): string | null {
  if (!host) return null;
  return PROVIDER_NAMES[host] ?? host;
}

export function textConsentDetail(aiHost: string | null | undefined): string {
  const name = providerName(aiHost);
  const who = name ? `The AI model runs at ${name}. It` : "The AI model";
  const freeTier =
    aiHost === "generativelanguage.googleapis.com"
      ? " On Google’s free Gemini tier, Google may use submitted text to improve its products, and people at Google may read it."
      : "";
  return (
    `${who} reads the text to pull out claims, compares them with the evidence and writes the explanation. ` +
    "Google Fact Check Tools searches fact checks that others have published. The text leaves the Satyapan server and " +
    `those companies’ own terms apply.${freeTier}`
  );
}

const CONSENTS = (aiHost: string | null | undefined) => [
  {
    key: "consentText",
    title: "Send the message text to the AI model and Google Fact Check Tools",
    detail: textConsentDetail(aiHost),
  },
  {
    key: "consentLinks",
    title: "Send links to third-party link checkers",
    detail:
      "Services such as Google Safe Browsing check whether a link is known for phishing or malware. Only the links are sent, not your message.",
  },
  {
    key: "consentMedia",
    title: "Send photos, video and audio to third-party media services",
    detail:
      "Used for provenance checks such as reverse image search. Without this, files are only compared with Satyapan’s own index. Satyapan deletes your uploads from its server once the report is made.",
  },
] as const;

export function VerifyForm({ values, onChange, onSubmit, limits, limitsKnown, busy, aiHost }: Props) {
  const uid = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const links = parseLinks(values.links);
  const tooManyLinks = links.length > limits.max_links;
  const ids = {
    text: `${uid}-text`,
    links: `${uid}-links`,
    files: `${uid}-files`,
  };

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  function onFiles(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    const result = validateFiles(values.files, picked, limits);
    setRejected(result.rejected);
    if (result.accepted.length > 0) set("files", [...values.files, ...result.accepted]);
    // Reset so the same file can be picked again after removal.
    e.target.value = "";
  }

  function removeFile(index: number) {
    set(
      "files",
      values.files.filter((_, i) => i !== index),
    );
    fileInput.current?.focus();
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!values.text.trim() && links.length === 0 && values.files.length === 0) {
      setFormError("Add message text, a link or a file to verify.");
      return;
    }
    setFormError(null);
    onSubmit();
  }

  const fileLimitText = `Up to ${limits.max_files} files. Images up to ${limits.max_image_mb} MB, video up to ${limits.max_video_mb} MB, audio up to ${limits.max_audio_mb} MB, and at most ${limits.max_media_seconds} seconds of video or audio.`;

  return (
    <form onSubmit={submit} noValidate className="space-y-8" aria-describedby={formError ? `${uid}-error` : undefined}>
      {formError && (
        <p id={`${uid}-error`} role="alert" className="rounded-md border border-fake bg-fake-tint px-4 py-3 font-medium text-fake">
          {formError}
        </p>
      )}

      <div>
        <label htmlFor={ids.text} className="block text-md font-semibold">
          Message text
        </label>
        <p id={`${ids.text}-hint`} className="mt-0.5 text-sm text-muted">
          Paste the message as you received it. English, Hindi, Telugu or a mix of them.
        </p>
        <textarea
          id={ids.text}
          name="text"
          rows={7}
          maxLength={limits.max_text_chars}
          value={values.text}
          onChange={(e) => set("text", e.target.value)}
          aria-describedby={`${ids.text}-hint ${ids.text}-count`}
          className="field mt-2 resize-y"
          disabled={busy}
        />
        <p id={`${ids.text}-count`} className="tabular mt-1 text-right text-sm text-muted">
          {formatNumber(values.text.length)} of {formatNumber(limits.max_text_chars)} characters
        </p>
      </div>

      <div>
        <label htmlFor={ids.links} className="block text-md font-semibold">
          Links
        </label>
        <p id={`${ids.links}-hint`} className="mt-0.5 text-sm text-muted">
          One link per line. Up to {limits.max_links} are checked.
        </p>
        <textarea
          id={ids.links}
          name="links"
          rows={3}
          value={values.links}
          onChange={(e) => set("links", e.target.value)}
          aria-describedby={`${ids.links}-hint${tooManyLinks ? ` ${ids.links}-warn` : ""}`}
          className="field mt-2 resize-y"
          spellCheck={false}
          autoCapitalize="off"
          inputMode="url"
          disabled={busy}
        />
        {tooManyLinks && (
          <p id={`${ids.links}-warn`} className="mt-1 text-sm font-medium text-unverified">
            {links.length} links entered. Only the first {limits.max_links} will be checked.
          </p>
        )}
      </div>

      <div>
        <label htmlFor={ids.files} className="block text-md font-semibold">
          Photos, video or audio
        </label>
        <p id={`${ids.files}-hint`} className="mt-0.5 text-sm text-muted">
          {fileLimitText}
          {!limitsKnown && " These are default limits because the server status could not be read."}
        </p>
        <input
          ref={fileInput}
          id={ids.files}
          type="file"
          multiple
          accept={ACCEPT_ATTRIBUTE}
          onChange={onFiles}
          aria-describedby={`${ids.files}-hint`}
          disabled={busy || values.files.length >= limits.max_files}
          className="mt-2 block w-full max-w-full text-sm text-muted file:mr-3 file:min-h-11 file:cursor-pointer file:rounded-md file:border file:border-solid file:border-rule-strong file:bg-surface file:px-4 file:font-semibold file:text-ink hover:file:border-accent"
        />

        {values.files.length > 0 && (
          <ul className="mt-3 divide-y divide-rule rounded-md border border-rule bg-surface" aria-label="Files to send">
            {values.files.map((file, i) => (
              <li key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center gap-3 px-3 py-2">
                <MediaIcon kind={mediaKindOf(file) ?? "image"} size={18} className="flex-none text-muted" />
                <span className="min-w-0 flex-1">
                  <span className="block break-anywhere text-sm font-medium">{file.name}</span>
                  <span className="tabular block text-xs text-muted">{formatBytes(file.size)}</span>
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-small"
                  onClick={() => removeFile(i)}
                  aria-label={`Remove ${file.name}`}
                  disabled={busy}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <div aria-live="polite">
          {rejected.length > 0 && (
            <div className="mt-3 rounded-md border border-fake bg-fake-tint px-4 py-3 text-sm text-fake">
              <p className="font-semibold">Not added</p>
              <ul className="mt-1 space-y-1">
                {rejected.map((r, i) => (
                  <li key={`${r.name}-${i}`} className="break-anywhere">
                    {r.name} ({formatBytes(r.size)}): {r.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <fieldset className="rounded-lg border border-rule bg-surface p-4 sm:p-5">
        <legend className="px-1 text-md font-semibold">Outside services</legend>
        <p className="measure text-sm text-muted">
          Satyapan’s own checks run on its server. The services below belong to other companies, and each runs only if you tick
          its box. A check you leave unticked is skipped and listed in the report.
        </p>
        <div className="mt-4 space-y-4">
          {CONSENTS(aiHost).map((c) => {
            const id = `${uid}-${c.key}`;
            return (
              <div key={c.key} className="flex items-start gap-3">
                <input
                  id={id}
                  type="checkbox"
                  className="check"
                  checked={values[c.key]}
                  onChange={(e) => set(c.key, e.target.checked)}
                  aria-describedby={`${id}-detail`}
                  disabled={busy}
                />
                <div>
                  <label htmlFor={id} className="font-medium">
                    {c.title}
                  </label>
                  <p id={`${id}-detail`} className="measure mt-0.5 text-sm text-muted">
                    {c.detail}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          Run verification
        </button>
        <p className="text-sm text-muted">You will see each step as the server runs it.</p>
      </div>
    </form>
  );
}
