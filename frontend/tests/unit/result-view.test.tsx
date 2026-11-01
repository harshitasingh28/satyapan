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
    const ai = section("How the AI reasoned");
    expect(within(ai).getByText("fixture-chat-model")).toBeInTheDocument();
    expect(within(ai).getByText("Fixture rejected AI output.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download report (Markdown)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download report (JSON)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });
});

describe("AiBlock plan and comparison", () => {
  it("shows who decided each check, the AI queries and the quote checks", async () => {
    const { AiBlock } = await import("@/components/result/AiBlock");
    render(
      <AiBlock
        ai={{
          chat_model: "m",
          embedding_model: "e",
          extraction: "used",
          comparison: "used",
          explanation: "template",
          problems: ["planner query rejected (adds a number not in the message (5000)): '5000 note'"],
          plan: {
            status: "used",
            claim_type: "viral_rumour_or_hoax",
            language: "hi",
            decisions: [
              { check: "Published fact-checks, claim as written", run: true, decided_by: "code", why: "Always searched." },
              { check: "Extra fact-check searches", run: true, decided_by: "ai", why: "A viral hoax.", queries: ["2000 rupee note GPS chip"] },
            ],
          },
          pairs: [
            { candidate: "F1", type: "reviewed_claim", verified: true, relation: "supports", same_subject: true, evidence_quote: "GPS chip" },
            { candidate: "K1", type: "official_release", verified: false, problem: "evidence quote not found in the source text" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Viral rumour or hoax")).toBeInTheDocument();
    expect(screen.getByText("Hindi")).toBeInTheDocument();
    expect(screen.getByText("2000 rupee note GPS chip")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByText("Code rule")).toBeInTheDocument();
    expect(screen.getByText("Quotes verified in the source")).toBeInTheDocument();
    expect(screen.getByText("Rejected by code")).toBeInTheDocument();
    expect(screen.getByText("evidence quote not found in the source text")).toBeInTheDocument();
    expect(screen.getByText("Same claim as the one fact-checked")).toBeInTheDocument();
  });

  it("shows the one re-plan, its new searches and what code rejected", async () => {
    const { AiBlock } = await import("@/components/result/AiBlock");
    render(
      <AiBlock
        ai={{
          chat_model: "m",
          embedding_model: "e",
          extraction: "used",
          comparison: "no_candidates",
          explanation: "template",
          problems: [],
          plan: {
            status: "used",
            claim_type: "viral_rumour_or_hoax",
            language: "en",
            decisions: [],
            replan: {
              status: "used",
              why: "Use the words a fact-check headline would use.",
              queries: ["2000 rupee note GPS chip"],
              problems: ["re-plan query rejected (repeats an earlier search): 'currency tracking'"],
              found: 2,
            },
          },
          pairs: [],
        }}
      />,
    );
    expect(screen.getByText("Second attempt: the AI re-planned once")).toBeInTheDocument();
    expect(screen.getByText("Use the words a fact-check headline would use.")).toBeInTheDocument();
    expect(screen.getByText("2000 rupee note GPS chip")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("re-plan query rejected (repeats an earlier search): 'currency tracking'")).toBeInTheDocument();
  });
});
