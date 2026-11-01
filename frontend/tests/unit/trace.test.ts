import { describe, expect, it } from "vitest";
import { announce, buildTraceRows, mergeSteps } from "@/lib/trace";
import { fixtureSteps } from "../fixtures/fixture-report";

describe("buildTraceRows", () => {
  it("makes one row per node run, closing it on end", () => {
    const rows = buildTraceRows(fixtureSteps);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ node: "fixture_extract", label: "Fixture extracting", open: false, ms: 321 });
    expect(rows[0]?.toolRuns).toHaveLength(1);
    expect(rows[0]?.newEvidence).toEqual(["E1", "E2"]);
    // Unknown node with no label is shown generically by its node name, still open
    expect(rows[1]).toMatchObject({ node: "fixture_unknown_node", label: "fixture_unknown_node", open: true });
  });

  it("shows an end that arrived without its start", () => {
    const rows = buildTraceRows([{ seq: 7, ts: "", node: "late", phase: "end", label: "Late step", ms: 5 }]);
    expect(rows).toEqual([expect.objectContaining({ node: "late", open: false, ms: 5 })]);
  });

  it("orders by seq even when events arrive out of order", () => {
    const rows = buildTraceRows([...fixtureSteps].reverse());
    expect(rows.map((r) => r.node)).toEqual(["fixture_extract", "fixture_unknown_node"]);
  });
});

describe("mergeSteps", () => {
  it("drops repeated seq numbers, as when saved events overlap live ones", () => {
    const merged = mergeSteps(fixtureSteps.slice(0, 2), fixtureSteps);
    expect(merged.map((s) => s.seq)).toEqual([1, 2, 3]);
  });
});

describe("announce", () => {
  it("describes start and end for screen readers", () => {
    expect(announce(fixtureSteps[0]!)).toBe("Fixture extracting started.");
    expect(announce(fixtureSteps[1]!)).toBe("Fixture extracting finished in 321 milliseconds. 2 new pieces of evidence.");
  });
});
