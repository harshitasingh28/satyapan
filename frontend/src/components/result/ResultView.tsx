"use client";

import { type RefObject, useEffect, useRef } from "react";
import {
  claimSourceLabel,
  evidenceStrengthLabel,
  langAttribute,
  languageLabel,
  toolStatusInfo,
  verdictMeaning,
  verdictReasonText,
  verdictTone,
} from "@/lib/labels";
import type { Claim, Report, Statement, ToolRun } from "@/lib/types";
import { evidenceAnchorId } from "@/lib/url";
import { VerdictIcon } from "../Icons";
import { Chip, DateTime } from "../primitives";
import { AiBlock } from "./AiBlock";
import { EvidenceCard } from "./EvidenceCard";
import { MediaFindings } from "./MediaFindings";
import { ReportActions } from "./ReportActions";
import { ToolRunsTable } from "./ToolRunsTable";

type Props = {
  report: Report;
  id: string;
  token: string | null;
  /** Move keyboard and screen reader focus to the verdict when it first appears. */
  focusOnMount?: boolean;
};

export function ResultView({ report, id, token, focusOnMount = false }: Props) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusOnMount) headingRef.current?.focus();
  }, [focusOnMount]);

  const evidence = report.evidence ?? [];
  const knownIds = new Set(evidence.map((e) => e.id));
  const reason = report.reason ?? [];
  const runs = report.tool_runs ?? [];

  return (
    <article aria-label="Verification result" className="space-y-12">
      <VerdictBanner report={report} headingRef={headingRef} animate={focusOnMount} />
      <ReportActions id={id} token={token} />
      <ClaimsSection main={report.claim} claims={report.claims ?? []} />

      <div className="space-y-10">
        <StatementSection
          id="verified"
          title="Verified from sources"
          intro="Facts stated directly by the evidence, each tied to the source that says it."
          statements={reason.filter((s) => s.kind === "verified_fact")}
          knownIds={knownIds}
          empty="No statement could be confirmed directly from a source."
        />
        <StatementSection
          id="ai-explanation"
          title="AI explanation, checked against sources"
          intro="Written by the AI model from the evidence. Code checked that each quote and citation it uses exists in the evidence."
          statements={reason.filter((s) => s.kind === "ai_explanation")}
          knownIds={knownIds}
          empty="No AI explanation was written for this report."
        />
        <UnavailableSection
          statements={reason.filter((s) => s.kind === "unavailable")}
          runs={runs}
          limitations={report.limitations ?? []}
          knownIds={knownIds}
        />
      </div>

      <section aria-labelledby="evidence-heading" className="space-y-4">
        <h2 id="evidence-heading" className="text-xl font-semibold">
          Evidence ({evidence.length})
        </h2>
        <p className="measure text-sm text-muted">
          Each item was retrieved by a tool and saved with its source and the time it was retrieved.
        </p>
        {evidence.length === 0 ? (
          <p className="text-sm">No evidence was found for this message.</p>
        ) : (
          <div className="space-y-4">
            {evidence.map((e) => (
              <EvidenceCard key={e.id} evidence={e} />
            ))}
          </div>
        )}
      </section>

      <MediaFindings media={report.media_assessment ?? {}} />
      <ToolRunsTable runs={runs} />
      {report.ai && <AiBlock ai={report.ai} />}
    </article>
  );
}

function VerdictBanner({
  report,
  headingRef,
  animate,
}: {
  report: Report;
  headingRef: RefObject<HTMLHeadingElement | null>;
  animate: boolean;
}) {
  const tone = verdictTone(report.verdict);
  return (
    <section aria-labelledby="verdict-heading" className="rounded-lg border border-rule bg-surface p-4 sm:p-7">
      <h2 id="verdict-heading" ref={headingRef} tabIndex={-1} className="outline-none">
        <span className="sr-only">Verdict: </span>
        <span className={`stamp ${animate ? "stamp-press" : ""}`} data-tone={tone}>
          <VerdictIcon verdict={report.verdict} strokeWidth={2.4} />
          <span>{report.verdict}</span>
        </span>
      </h2>
      <p className="mt-5 measure font-serif text-lg">{verdictMeaning(report.verdict)}</p>
      <dl className="mt-5 grid gap-x-6 gap-y-2 text-base sm:grid-cols-[max-content_minmax(0,1fr)]">
        <dt className="font-semibold">Why</dt>
        <dd className="measure">{verdictReasonText(report.verdict_reason)}</dd>
        <dt className="font-semibold">Evidence strength</dt>
        <dd className="measure">
          {evidenceStrengthLabel(report.evidence_strength)}
          {report.strength_explanation ? `. ${report.strength_explanation}` : ""}
        </dd>
        <dt className="font-semibold">Checked</dt>
        <dd>
          <DateTime iso={report.created_at} />
          <span className="block break-anywhere text-sm text-muted">Investigation {report.investigation_id}</span>
        </dd>
      </dl>
    </section>
  );
}

function ClaimTags({ claim }: { claim: Claim }) {
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Claim details">
      <li>
        <Chip>{languageLabel(claim.language)}</Chip>
      </li>
      <li>
        <Chip>{claimSourceLabel(claim.source)}</Chip>
      </li>
    </ul>
  );
}

function ClaimFacts({ claim }: { claim: Claim }) {
  const rows: { label: string; values: string[] }[] = [
    { label: "Amounts", values: claim.amounts ?? [] },
    { label: "Links in the claim", values: claim.urls ?? [] },
    { label: "Phone numbers", values: claim.phones ?? [] },
    { label: "Asks you to", values: claim.calls_to_action ?? [] },
    { label: "Names", values: claim.entities ?? [] },
  ].filter((r) => r.values.length > 0);
  if (rows.length === 0) return null;
  return (
    <dl className="mt-3 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-muted">{row.label}</dt>
          <dd className="break-anywhere">
            {row.label === "Links in the claim" ? (
              <ul className="space-y-0.5">
                {row.values.map((v, i) => (
                  // Links from the message are shown as text so nobody opens a suspect link by accident.
                  <li key={i} className="font-medium">
                    {v}
                  </li>
                ))}
              </ul>
            ) : (
              row.values.join(", ")
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ClaimsSection({ main, claims }: { main: Claim | null; claims: Claim[] }) {
  const others = claims.filter((c) => c.id !== main?.id);
  return (
    <section aria-labelledby="claims-heading">
      <h2 id="claims-heading" className="text-xl font-semibold">
        What the message claims
      </h2>
      {main ? (
        <div className="mt-3 rounded-lg border border-rule bg-surface p-4 sm:p-5">
          <p className="text-sm font-semibold text-muted">Main claim</p>
          <p lang={langAttribute(main.language)} className="mt-1 measure font-serif text-lg break-anywhere">
            {main.text}
          </p>
          <ClaimTags claim={main} />
          <ClaimFacts claim={main} />
          {(main.urls ?? []).length > 0 && (
            <p className="mt-2 text-xs text-muted">Links from the message are shown as text so they are not opened by accident.</p>
          )}
        </div>
      ) : (
        <p className="mt-3">No checkable claim was found in the message.</p>
      )}
      {others.length > 0 && (
        <div className="mt-6">
          <h3 className="font-sans text-base font-semibold">Other claims found ({others.length})</h3>
          <ul className="mt-2 divide-y divide-rule border-y border-rule">
            {others.map((c) => (
              <li key={c.id} className="py-3">
                <p lang={langAttribute(c.language)} className="measure break-anywhere">
                  {c.text}
                </p>
                <ClaimTags claim={c} />
                <ClaimFacts claim={c} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function EvidenceRefs({ ids, knownIds }: { ids: string[]; knownIds: Set<string> }) {
  if (ids.length === 0) return null;
  return (
    <p className="mt-1 text-sm text-muted">
      <span>Evidence: </span>
      {ids.map((eid, i) => (
        <span key={`${eid}-${i}`}>
          {i > 0 && ", "}
          {knownIds.has(eid) ? (
            <a href={`#${evidenceAnchorId(eid)}`} className="tabular font-semibold">
              {eid}
            </a>
          ) : (
            <span className="tabular">{eid} (not in this report)</span>
          )}
        </span>
      ))}
    </p>
  );
}

function StatementList({ statements, knownIds }: { statements: Statement[]; knownIds: Set<string> }) {
  return (
    <ul className="mt-3 space-y-3">
      {statements.map((s, i) => (
        <li key={i} className="border-l-2 border-rule-strong pl-4">
          <p className="measure">{s.text}</p>
          <EvidenceRefs ids={s.evidence_ids ?? []} knownIds={knownIds} />
        </li>
      ))}
    </ul>
  );
}

function StatementSection(props: {
  id: string;
  title: string;
  intro: string;
  statements: Statement[];
  knownIds: Set<string>;
  empty: string;
}) {
  return (
    <section aria-labelledby={`${props.id}-heading`} data-section={props.id}>
      <h2 id={`${props.id}-heading`} className="text-xl font-semibold">
        {props.title}
      </h2>
      <p className="mt-1 measure text-sm text-muted">{props.intro}</p>
      {props.statements.length === 0 ? (
        <p className="mt-3 text-sm">{props.empty}</p>
      ) : (
        <StatementList statements={props.statements} knownIds={props.knownIds} />
      )}
    </section>
  );
}

function RunList({ runs }: { runs: ToolRun[] }) {
  return (
    <ul className="mt-2 space-y-2">
      {runs.map((run, i) => {
        const info = toolStatusInfo(run.status);
        return (
          <li key={`${run.tool}-${i}`} className="text-sm">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-medium break-anywhere">{run.tool}</span>
              <Chip tone={info.tone}>{info.label}</Chip>
            </span>
            {(run.target || run.detail) && (
              <span className="mt-0.5 block break-anywhere text-muted">
                {[run.target, run.detail].filter(Boolean).join(". ")}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function UnavailableSection({
  statements,
  runs,
  limitations,
  knownIds,
}: {
  statements: Statement[];
  runs: ToolRun[];
  limitations: string[];
  knownIds: Set<string>;
}) {
  const failed = runs.filter((r) => toolStatusInfo(r.status).failed);
  const skipped = runs.filter((r) => toolStatusInfo(r.status).skipped);
  const nothing = statements.length === 0 && failed.length === 0 && skipped.length === 0 && limitations.length === 0;
  return (
    <section aria-labelledby="unavailable-heading" data-section="unavailable">
      <h2 id="unavailable-heading" className="text-xl font-semibold">
        Not available
      </h2>
      <p className="mt-1 measure text-sm text-muted">What could not be checked, and the limits of this report.</p>
      {nothing && <p className="mt-3 text-sm">Every check that applied to this message ran.</p>}
      {statements.length > 0 && <StatementList statements={statements} knownIds={knownIds} />}
      {failed.length > 0 && (
        <div className="mt-5">
          <h3 className="font-sans text-base font-semibold">Checks that failed</h3>
          <RunList runs={failed} />
        </div>
      )}
      {skipped.length > 0 && (
        <div className="mt-5">
          <h3 className="font-sans text-base font-semibold">Checks that were skipped</h3>
          <RunList runs={skipped} />
        </div>
      )}
      {limitations.length > 0 && (
        <div className="mt-5">
          <h3 className="font-sans text-base font-semibold">Limits of this report</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {limitations.map((l, i) => (
              <li key={i} className="measure">
                {l}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
