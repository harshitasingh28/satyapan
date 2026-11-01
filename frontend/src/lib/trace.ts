import type { StepEvent, ToolRun } from "./types";

export type TraceRow = {
  key: string;
  node: string;
  label: string;
  open: boolean;
  ms?: number;
  toolRuns: ToolRun[];
  newEvidence: string[];
  startedAt?: string;
};

/** Adds events, ignoring repeats of the same seq, kept in seq order. */
export function mergeSteps(existing: readonly StepEvent[], incoming: readonly StepEvent[]): StepEvent[] {
  const bySeq = new Map<number, StepEvent>();
  for (const e of existing) bySeq.set(e.seq, e);
  for (const e of incoming) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/**
 * One row per node run. A "start" opens a row, the next "end" for the same
 * node closes it. An "end" with no open row still gets a row, so nothing the
 * server reported is hidden. Only what the events say is shown.
 */
export function buildTraceRows(steps: readonly StepEvent[]): TraceRow[] {
  const rows: TraceRow[] = [];
  const openByNode = new Map<string, TraceRow>();
  for (const step of [...steps].sort((a, b) => a.seq - b.seq)) {
    const label = step.label?.trim() || step.node;
    if (step.phase === "start") {
      const row: TraceRow = {
        key: `${step.node}-${step.seq}`,
        node: step.node,
        label,
        open: true,
        toolRuns: [],
        newEvidence: [],
        startedAt: step.ts,
      };
      rows.push(row);
      openByNode.set(step.node, row);
      continue;
    }
    let row = openByNode.get(step.node);
    if (!row) {
      row = { key: `${step.node}-${step.seq}`, node: step.node, label, open: false, toolRuns: [], newEvidence: [] };
      rows.push(row);
    }
    openByNode.delete(step.node);
    row.open = false;
    row.label = label;
    if (typeof step.ms === "number") row.ms = step.ms;
    row.toolRuns = Array.isArray(step.tool_runs) ? step.tool_runs : [];
    row.newEvidence = Array.isArray(step.new_evidence) ? step.new_evidence : [];
  }
  return rows;
}

/** One sentence for the screen reader live region. */
export function announce(step: StepEvent): string {
  const label = step.label?.trim() || step.node;
  if (step.phase === "start") return `${label} started.`;
  const evidence = step.new_evidence?.length ?? 0;
  const parts = [`${label} finished`];
  if (typeof step.ms === "number") parts.push(`in ${Math.round(step.ms)} milliseconds`);
  let sentence = parts.join(" ") + ".";
  if (evidence > 0) sentence += ` ${evidence} new ${evidence === 1 ? "piece" : "pieces"} of evidence.`;
  return sentence;
}
