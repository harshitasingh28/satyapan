import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultView } from "@/components/result/ResultView";
import type { Report } from "@/lib/types";
import { fixtureReport } from "../fixtures/fixture-report";

function renderReport(report: Report = fixtureReport) {
  return render(<ResultView report={report} id={report.investigation_id} token="fixture-token" />);
}

function section(name: string): HTMLElement {
  const heading = screen.getByRole("heading", { level: 2, name });
  const el = heading.closest("section");
  if (!el) throw new Error(`no section for ${name}`);
  return el;
}

describe("ResultView", () => {
  it("shows the verdict as a word with its meaning, not only a colour", () => {
    renderReport();
    const heading = screen.getByRole("heading", { level: 2, name: /Verdict: FAKE/ });
    expect(heading).toHaveTextContent("FAKE");
    expect(screen.getByText("Contradicted by reliable evidence.")).toBeInTheDocument();
    expect(screen.getByText(/Fixture strength explanation/)).toBeInTheDocument();
  });

  it.each([
    ["GENUINE", "Supported by a specific official source with matching facts."],
    ["UNVERIFIED", "Not enough reliable evidence to decide. This is not the same as true."],
  ] as const)("shows %s with its plain meaning", (verdict, meaning) => {
    renderReport({ ...fixtureReport, verdict });
    expect(screen.getByRole("heading", { level: 2, name: new RegExp(`Verdict: ${verdict}`) })).toBeInTheDocument();
    expect(screen.getByText(meaning)).toBeInTheDocument();
  });

  it("puts each statement kind in its own section", () => {
    renderReport();
    const verified = section("Verified from sources");
    const ai = section("AI explanation, checked against sources");
    const unavailable = section("Not available");

    expect(within(verified).getByText("Fixture verified statement.")).toBeInTheDocument();
    expect(within(verified).queryByText(/Fixture AI statement/)).toBeNull();

    expect(within(ai).getByText(/Fixture AI statement/)).toBeInTheDocument();
    expect(within(ai).queryByText("Fixture verified statement.")).toBeNull();

    expect(within(unavailable).getByText("Fixture unavailable statement.")).toBeInTheDocument();
    // Failed and skipped tool runs and report limitations also belong here.
    expect(within(unavailable).getByText("fixture_remote")).toBeInTheDocument();
    expect(within(unavailable).getByText("fixture_consent")).toBeInTheDocument();
    expect(within(unavailable).queryByText("fixture_tool")).toBeNull();
    expect(within(unavailable).getByText("Fixture report limitation.")).toBeInTheDocument();
  });

  it("links evidence ids to their cards and marks unknown ids", () => {
    renderReport();
    const ai = section("AI explanation, checked against sources");
    expect(within(ai).getByRole("link", { name: "E1" })).toHaveAttribute("href", "#evidence-E1");
    expect(within(ai).getByText("E9 (not in this report)")).toBeInTheDocument();
    expect(document.getElementById("evidence-E1")).not.toBeNull();
  });

  it("renders a source as a link only for http(s) URLs, opening safely in a new tab", () => {
    const { container } = renderReport();
    const link = screen.getByRole("link", { name: /https:\/\/fixture\.example\/release\/1/ });
    expect(link).toHaveAttribute("href", "https://fixture.example/release/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");

    // javascript: URL is shown as text, never as a link
    expect(screen.getByText("javascript:alert(3)").closest("a")).toBeNull();
    for (const a of Array.from(container.querySelectorAll("a"))) {
      const href = a.getAttribute("href") ?? "";
      expect(href.startsWith("#") || href.startsWith("http://") || href.startsWith("https://")).toBe(true);
    }
    // Links quoted from the suspect message are not clickable
    expect(container.querySelector('a[href="http://fixture.example/claim-link"]')).toBeNull();
  });

  it("renders server text as plain text, never as HTML", () => {
    const { container } = renderReport();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getAllByText(/<img src=x onerror=alert\(1\)>/).length).toBeGreaterThan(0);
    expect(screen.getByText(/<script>alert\(2\)<\/script>/)).toBeInTheDocument();
  });

  it("labels quotes, shows evidence chips and the media note", () => {
    renderReport();
    expect(screen.getByText("Quoted from the source")).toBeInTheDocument();
    expect(screen.getByText("Fixture quote copied from the source.").tagName).toBe("BLOCKQUOTE");
    expect(screen.getByText("Contradicts the claim")).toBeInTheDocument();
    expect(screen.getByText("Official index")).toBeInTheDocument();
    expect(screen.getByText("Media authenticity and provenance audit. Satyapan does not detect deepfakes.")).toBeInTheDocument();
    expect(screen.getByText(/This is not evidence that the file is fake/)).toBeInTheDocument();
  });

  it("shows tool runs, AI use and download actions", () => {
    renderReport();
    const tools = section("Tool runs");
    expect(within(tools).getByRole("table")).toBeInTheDocument();
    expect(within(tools).getByText("Service error")).toBeInTheDocument();
    const ai = section("How AI was used");
    expect(within(ai).getByText("fixture-chat-model")).toBeInTheDocument();
    expect(within(ai).getByText("Fixture rejected AI output.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download report (Markdown)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download report (JSON)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });
});
