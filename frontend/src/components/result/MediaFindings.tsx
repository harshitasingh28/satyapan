import { humanise } from "@/lib/format";
import { credentialsLabel, manipulationLabel, mediaTierInfo, provenanceLabel } from "@/lib/labels";
import type { MediaAssessment } from "@/lib/types";
import { MediaIcon } from "../Icons";
import { Chip, SafeLink } from "../primitives";

export const MEDIA_NOTE = "Media authenticity and provenance audit. Satyapan does not detect deepfakes.";

function kindLabel(kind: string): string {
  if (kind === "image") return "Image";
  if (kind === "video") return "Video";
  if (kind === "audio") return "Audio";
  return humanise(kind);
}

function MediaItem({ mediaId, item }: { mediaId: string; item: MediaAssessment }) {
  const tier = item.tier ? mediaTierInfo(item.tier) : null;
  const matches = item.matches ?? [];
  const headingId = `media-${mediaId.replace(/[^A-Za-z0-9_-]/g, "_")}`;

  return (
    <article className="rounded-lg border border-rule bg-surface p-4 sm:p-5" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <MediaIcon kind={item.kind} size={20} className="text-muted" />
        <h3 id={headingId} className="break-anywhere font-sans text-md font-semibold">
          {item.name || mediaId}
        </h3>
        <Chip>{kindLabel(item.kind)}</Chip>
      </div>

      {tier && (
        <div className="mt-3">
          <Chip tone={tier.tone}>{tier.label}</Chip>
          {tier.meaning && <p className="mt-1.5 measure">{tier.meaning}</p>}
        </div>
      )}

      <dl className="mt-4 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        <dt className="text-muted">Content credentials (C2PA)</dt>
        <dd>{item.credentials ? credentialsLabel(item.credentials) : "Not checked"}</dd>
        <dt className="text-muted">Provenance</dt>
        <dd>{item.provenance ? provenanceLabel(item.provenance) : "Not checked"}</dd>
        <dt className="text-muted">Manipulation check</dt>
        <dd>{manipulationLabel(item.manipulation)}</dd>
        {typeof item.frames === "number" && (
          <>
            <dt className="text-muted">Video frames compared</dt>
            <dd className="tabular">{item.frames}</dd>
          </>
        )}
        {item.deepfake && (
          <>
            <dt className="text-muted">Synthetic face signal</dt>
            <dd>{humanise(item.deepfake)}</dd>
          </>
        )}
        {item.synthetic_signal !== undefined && item.synthetic_signal !== null && (
          <>
            <dt className="text-muted">AI-image detector (vendor)</dt>
            <dd>{syntheticSignalLabel(item.synthetic_signal)}</dd>
          </>
        )}
        {item.voice_authenticity && (
          <>
            <dt className="text-muted">Synthetic voice signal</dt>
            <dd>{humanise(item.voice_authenticity)}</dd>
          </>
        )}
      </dl>

      {item.ocr_text && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-accent">Text read from this file</summary>
          <p className="mt-2 rounded-md bg-sunk p-3 whitespace-pre-wrap break-anywhere">{item.ocr_text}</p>
        </details>
      )}

      <div className="mt-4">
        <h4 className="text-sm font-semibold">Matches in the index of known media</h4>
        {matches.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No matches.</p>
        ) : (
          <ul className="mt-2 space-y-3">
            {matches.map((m, i) => {
              const info = mediaTierInfo(m.tier);
              return (
                <li key={`${m.known_id}-${i}`} className="border-l-2 border-rule-strong pl-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="break-anywhere font-medium">{m.known_id}</span>
                    <Chip tone={info.tone}>{info.label}</Chip>
                  </div>
                  {m.publisher && <p className="mt-1">Published by {m.publisher}</p>}
                  {m.claim && <p className="mt-1">Claim recorded with this media: {m.claim}</p>}
                  {m.source_url && (
                    <p className="mt-1">
                      <SafeLink url={m.source_url} />
                    </p>
                  )}
                  <p className="tabular mt-1 text-muted">
                    {[
                      typeof m.phash_distance === "number" ? `Perceptual hash distance ${m.phash_distance}` : null,
                      typeof m.inliers === "number" ? `${m.inliers} matching feature points` : null,
                      typeof m.overlap_similarity === "number" ? `Overlap similarity ${m.overlap_similarity.toFixed(2)}` : null,
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </article>
  );
}


const VENDOR_SIGNAL: Record<string, string> = {
  VENDOR_FLAGGED_UNVALIDATED: "Flagged as likely AI-generated by Sightengine. Not validated by Satyapan, never changes the verdict.",
  VENDOR_NOT_FLAGGED_UNVALIDATED: "Not flagged as AI-generated by Sightengine. Not validated by Satyapan, never changes the verdict.",
  VENDOR_UNCLEAR_UNVALIDATED: "No clear answer from Sightengine. Not validated by Satyapan, never changes the verdict.",
  NOT_CALIBRATED: "Detector run, result not shown because it is not validated.",
};

function syntheticSignalLabel(value: string | number): string {
  if (typeof value === "number") return `Calibrated score ${value.toFixed(2)}`;
  return VENDOR_SIGNAL[value] ?? value;
}

export function MediaFindings({ media }: { media: Record<string, MediaAssessment> }) {
  const items = Object.entries(media ?? {});
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="media-heading" className="space-y-4">
      <h2 id="media-heading" className="text-xl font-semibold">
        Media findings
      </h2>
      <p className="measure rounded-md border border-rule bg-sunk px-4 py-3 text-sm font-medium">{MEDIA_NOTE}</p>
      {items.map(([id, item]) => (
        <MediaItem key={id} mediaId={id} item={item} />
      ))}
    </section>
  );
}
