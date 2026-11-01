import { evidenceKindLabel, originLabel, stanceInfo, strengthLabel } from "@/lib/labels";
import type { Evidence } from "@/lib/types";
import { evidenceAnchorId } from "@/lib/url";
import { Chip, DateTime, SafeLink } from "../primitives";

export function EvidenceCard({ evidence }: { evidence: Evidence }) {
  const anchor = evidenceAnchorId(evidence.id);
  const stance = stanceInfo(evidence.stance);
  const hasData = evidence.data && typeof evidence.data === "object" && Object.keys(evidence.data).length > 0;

  return (
    <article id={anchor} className="evidence-card p-4 sm:p-5" data-stance={evidence.stance} aria-labelledby={`${anchor}-title`}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="tabular text-sm font-bold text-muted">{evidence.id}</span>
        <h3 id={`${anchor}-title`} className="break-anywhere font-sans text-md font-semibold">
          {evidence.source_name || "Unnamed source"}
        </h3>
      </div>

      <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="About this evidence">
        <li>
          <Chip tone={stance.tone}>{stance.label}</Chip>
        </li>
        <li>
          <Chip>{strengthLabel(evidence.strength)}</Chip>
        </li>
        <li>
          <Chip tone="info">{originLabel(evidence.origin)}</Chip>
        </li>
        <li>
          <Chip>{evidenceKindLabel(evidence.kind)}</Chip>
        </li>
      </ul>

      {evidence.established && <p className="mt-3 measure">{evidence.established}</p>}

      {evidence.quote && (
        <figure className="mt-4">
          <figcaption className="text-sm font-semibold text-muted">Quoted from the source</figcaption>
          <blockquote className="quote mt-1.5 break-anywhere">{evidence.quote}</blockquote>
        </figure>
      )}

      <dl className="mt-4 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        <dt className="text-muted">Source</dt>
        <dd>
          <SafeLink url={evidence.source_url} />
        </dd>
        <dt className="text-muted">Published</dt>
        <dd>
          <DateTime iso={evidence.published_at} fallback="Not stated by the source" />
        </dd>
        <dt className="text-muted">Retrieved</dt>
        <dd>
          <DateTime iso={evidence.retrieved_at} />
        </dd>
        <dt className="text-muted">Checked against</dt>
        <dd className="break-anywhere">{evidence.target || "Not stated"}</dd>
        <dt className="text-muted">Tool</dt>
        <dd className="break-anywhere">
          {evidence.tool}
          {evidence.external ? ", an outside service" : ", run on the Satyapan server"}
        </dd>
      </dl>

      {(evidence.limitations ?? []).length > 0 && (
        <div className="mt-4 text-sm">
          <p className="font-semibold">Limits of this evidence</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {(evidence.limitations ?? []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {hasData && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-accent">Raw data from the tool</summary>
          <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-sunk p-3 text-xs whitespace-pre-wrap break-anywhere" tabIndex={0}>
            {JSON.stringify(evidence.data, null, 2)}
          </pre>
        </details>
      )}
    </article>
  );
}
