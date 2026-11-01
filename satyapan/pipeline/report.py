"""Report text. Deterministic templates by default, optional LLM rewrite that must pass validation."""
from __future__ import annotations

import json

from satyapan.errors import ToolError
from satyapan.http import ApiClient
from satyapan.llm import chat_json
from satyapan.models import Evidence, Statement
from satyapan.pipeline.citations import validate

REWRITE_PROMPT = (
    "Rewrite these evidence statements for a citizen in simple words. Return JSON only: "
    '{"statements": [{"text": "...", "evidence_ids": ["E1"]}]}. Use only facts present in the evidence. '
    "Keep every evidence id you use. Do not add numbers, names or links that are not in the evidence."
)


STRENGTH_ORDER = {"strong": 0, "moderate": 1, "weak": 2, "none": 3}


def template_statements(evidence: list[Evidence], basis: list[str]) -> list[Statement]:
    """One statement per evidence item in the verdict basis, strongest first."""
    by_id = {e.id: e for e in evidence}
    out = []
    for eid in sorted(basis, key=lambda i: (STRENGTH_ORDER.get(by_id[i].strength, 9), int(i[1:]) if i[1:].isdigit() else 0)):
        e = by_id[eid]
        src = f" ({e.source_url})" if e.source_url else ""
        out.append(Statement(text=f"{e.source_name}: {e.established}{src}", evidence_ids=[eid]))
    return out


def llm_rewrite(client: ApiClient, statements: list[Statement], evidence: list[Evidence], verdict: str,
                language: str = "en") -> tuple[list[Statement], list[dict], str]:
    payload = {"language": language, "verdict": verdict,
               "evidence": [{"id": e.id, "source": e.source_name, "url": e.source_url, "established": e.established}
                            for e in evidence if any(e.id in s.evidence_ids for s in statements)]}
    try:
        data = chat_json(client, REWRITE_PROMPT, json.dumps(payload, ensure_ascii=False))
    except ToolError as err:
        return statements, [{"problem": f"LLM unavailable: {err.status.value}"}], "template"
    proposed = [Statement(text=str(s.get("text", "")), evidence_ids=list(s.get("evidence_ids", [])))
                for s in data.get("statements", []) if isinstance(s, dict)]
    kept, problems = validate(proposed, evidence, verdict)
    if not kept:
        return statements, problems + [{"problem": "all LLM statements rejected, using templates"}], "template"
    return kept, problems, "llm_validated"


VERDICT_MEANING = {
    "GENUINE": "Supported by a specific official source with matching facts.",
    "FAKE": "Contradicted by reliable evidence.",
    "UNVERIFIED": "Not enough reliable evidence for a verdict. This does not mean the message is true.",
}


def _md(text) -> str:
    """User and source text is shown as text: neutralise Markdown and HTML control characters."""
    out = str(text if text is not None else "")
    for ch in ("\\", "`", "*", "_", "[", "]", "<", ">", "#", "|"):
        out = out.replace(ch, "\\" + ch)
    return " ".join(out.split())


def markdown_report(rep: dict) -> str:
    """The downloadable audit report. Every line is built from the stored report, nothing is added."""
    lines = [f"# Satyapan verification report", "",
             f"- Investigation: `{rep.get('investigation_id')}`",
             f"- Created: {rep.get('created_at')} (UTC)",
             f"- Verdict: **{rep.get('verdict')}** ({VERDICT_MEANING.get(rep.get('verdict'), '')})",
             f"- Reason code: {rep.get('verdict_reason') or 'n/a'}, evidence strength: {rep.get('evidence_strength')}",
             "", _md(rep.get("strength_explanation")), ""]
    claim = rep.get("claim") or {}
    lines += ["## Claim checked", "", f"> {_md(claim.get('text'))}", "",
              f"Language: {claim.get('language')}, source: {claim.get('source')}", ""]
    others = [c for c in rep.get("claims") or [] if c.get("id") != claim.get("id")]
    if others:
        lines += ["Other claims found:", ""] + [f"- {_md(c.get('text'))} ({c.get('language')})" for c in others] + [""]
    reasons = rep.get("reason") or []
    for kind, title in (("verified_fact", "Verified from sources"),
                        ("ai_explanation", "AI explanation, checked against the sources")):
        part = [r for r in reasons if r.get("kind", "verified_fact") == kind]
        if part:
            lines += [f"## {title}", ""] + [f"- {_md(r['text'])} [{', '.join(r['evidence_ids'])}]" for r in part] + [""]
    lines += ["## Evidence", ""]
    for e in rep.get("evidence") or []:
        lines += [f"### {e['id']}: {_md(e.get('source_name'))}", "",
                  f"- Stance: {e.get('stance')}, strength: {e.get('strength')}, origin: {e.get('origin') or 'n/a'}, "
                  f"tool: {e.get('tool')}",
                  f"- Established: {_md(e.get('established'))}"]
        if e.get("quote"):
            lines.append(f"- Quoted from the source: \"{_md(e['quote'])}\"")
        if e.get("source_url"):
            lines.append(f"- Source: <{e['source_url']}>" if str(e["source_url"]).startswith(("http://", "https://"))
                         else f"- Source: {_md(e['source_url'])}")
        if e.get("published_at"):
            lines.append(f"- Published: {e['published_at']}")
        lines.append(f"- Retrieved: {e.get('retrieved_at')}")
        for lim in e.get("limitations") or []:
            lines.append(f"- Limitation: {_md(lim)}")
        lines.append("")
    if not rep.get("evidence"):
        lines += ["No evidence was found.", ""]
    media = rep.get("media_assessment") or {}
    if media:
        lines += ["## Media provenance and reuse", "",
                  "Satyapan audits media provenance and reuse. It does not detect deepfakes.", ""]
        for mid, m in media.items():
            facts = ", ".join(f"{k}: {_md(v)}" for k, v in m.items() if k not in ("matches",) and not isinstance(v, (dict, list)))
            lines.append(f"- {mid}: {facts}")
            for mt in m.get("matches") or []:
                lines.append(f"  - match {_md(mt.get('known_id'))}: {mt.get('tier')}")
        lines.append("")
    ai = rep.get("ai") or {}
    lines += ["## AI use", "",
              f"- Chat model: {ai.get('chat_model') or 'not used'}",
              f"- Embedding model: {ai.get('embedding_model') or 'not used'}",
              f"- Claim extraction: {ai.get('extraction')}, comparison: {ai.get('comparison')}, "
              f"explanation: {ai.get('explanation')}",
              "- The AI never sets the verdict. Its quotes and citations are checked in code."]
    for p in ai.get("problems") or []:
        lines.append(f"- Rejected AI output: {_md(p)}")
    lines += ["", "## Tools run", "", "| Tool | Target | Status | ms |", "|---|---|---|---|"]
    for t in rep.get("tool_runs") or []:
        lines.append(f"| {_md(t.get('tool'))} | {_md(str(t.get('target'))[:60])} | {t.get('status')} | {t.get('ms')} |")
    lines += ["", "## Limitations", ""] + [f"- {_md(x)}" for x in rep.get("limitations") or []]
    lines += ["", "---", "Generated by Satyapan. The verdict is decided by code from retrieved evidence."]
    return "\n".join(lines) + "\n"
