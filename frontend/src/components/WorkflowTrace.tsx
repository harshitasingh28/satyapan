import { formatMs } from "@/lib/format";
import { toolStatusInfo } from "@/lib/labels";
import type { TraceRow } from "@/lib/trace";
import { evidenceAnchorId } from "@/lib/url";
import { IconCheck } from "./Icons";
import { Chip } from "./primitives";

type Props = {
  rows: TraceRow[];
  running: boolean;
  queuedMessage?: string | null;
  /** Latest sentence for the polite live region. */
  announcement?: string;
  /** Evidence ids present in the final report, so they can link to their cards. */
  evidenceIds?: Set<string>;
  headingLevel?: 2 | 3;
};

export function WorkflowTrace({ rows, running, queuedMessage, announcement = "", evidenceIds, headingLevel = 2 }: Props) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby="trace-heading" aria-busy={running} className="rounded-lg border border-rule bg-surface p-5 sm:p-6">
      <Heading id="trace-heading" className="text-xl font-semibold">
        Workflow trace
      </Heading>
      <p className="mt-1 measure text-sm text-muted">
        {running
          ? "Each row appears when the server reports that step. Times are measured on the server."
          : "The steps the server reported for this investigation. Times are measured on the server."}
      </p>

      {queuedMessage && (
        <p className="mt-4 rounded-md border border-rule bg-sunk px-3 py-2 text-sm">{queuedMessage}</p>
      )}

      {rows.length === 0 && running && (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted">
          <span className="spinner" aria-hidden="true" />
          Waiting for the server to report the first step.
        </p>
      )}

      {rows.length === 0 && !running && <p className="mt-4 text-sm text-muted">No steps were saved for this investigation.</p>}

      {rows.length > 0 && (
        <ol className="mt-5" aria-label="Steps">
          {rows.map((row, index) => (
            <li key={row.key} className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3 pb-5 last:pb-0" data-node={row.node}>
              {index < rows.length - 1 && (
                <span aria-hidden="true" className="absolute top-6 bottom-0 left-[0.6875rem] w-px bg-rule" />
              )}
              <span className="relative z-10 mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-surface">
                {row.open ? (
                  <span className="spinner" aria-hidden="true" />
                ) : (
                  <IconCheck size={18} className="text-accent" />
                )}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium break-anywhere">{row.label}</span>
                  <span className="tabular text-sm text-muted">
                    {row.open ? "In progress" : row.ms !== undefined ? formatMs(row.ms) : "Finished"}
                  </span>
                </div>
                {row.toolRuns.length > 0 && (
                  <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={`Tools run in ${row.label}`}>
                    {row.toolRuns.map((run, i) => {
                      const info = toolStatusInfo(run.status);
                      return (
                        <li key={`${run.tool}-${i}`}>
                          <Chip tone={info.tone}>
                            <span className="font-normal break-anywhere">{run.tool}</span>
                            <span>{info.label}</span>
                          </Chip>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {row.newEvidence.length > 0 && (
                  <p className="mt-1 text-sm text-muted">
                    {row.newEvidence.length} new {row.newEvidence.length === 1 ? "piece" : "pieces"} of evidence:{" "}
                    {row.newEvidence.map((eid, i) => (
                      <span key={`${eid}-${i}`}>
                        {i > 0 && ", "}
                        {evidenceIds?.has(eid) ? (
                          <a href={`#${evidenceAnchorId(eid)}`} className="tabular">
                            {eid}
                          </a>
                        ) : (
                          <span className="tabular">{eid}</span>
                        )}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}
