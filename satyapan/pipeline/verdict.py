"""Verdict rules (module 10). Deterministic. No LLM.

Unit of judgement: the MESSAGE and its central claim. A message is FAKE when its
central claim is contradicted by reliable evidence, or when it impersonates an
official source (for example claims government origin but sends people to a
lookalike domain).

GENUINE     strong supporting evidence AND zero contradicting evidence
FAKE        contradicting score >= 3 (one strong item, or independent moderate/weak items)
            AND no strong supporting evidence
UNVERIFIED  everything else: insufficient, conflicting, or tools unavailable
"""
from __future__ import annotations

from satyapan.models import Evidence


def decide(agg: dict, evidence: list[Evidence], failed_tools: list[str]) -> dict:
    c, s = agg["contradicts"], agg["supports"]
    by_id = {e.id: e for e in evidence}
    if agg["conflict"]:
        label, why = "UNVERIFIED", "conflict"
    elif c["score"] >= 3 and not s["strong"]:
        label, why = "FAKE", "contradicted"
    elif s["strong"] and c["score"] == 0:
        label, why = "GENUINE", "supported"
    else:
        label, why = "UNVERIFIED", "insufficient"

    if label == "FAKE":
        top = c["counted"]
        strength = "high" if len(c["strong"]) >= 2 or (c["strong"] and c["groups"] >= 2) else "medium"
    elif label == "GENUINE":
        top = s["counted"]
        strength = "high" if s["groups"] >= 2 else "medium"
    else:
        top = c["counted"] + s["counted"]
        strength = "n/a"

    explanation = (f"Contradicting evidence: score {c['score']} from {c['groups']} independent source group(s), "
                   f"{len(c['strong'])} strong. Supporting evidence: score {s['score']} from {s['groups']} "
                   f"group(s), {len(s['strong'])} strong.")
    if why == "conflict":
        explanation += " Strong evidence points both ways, so no verdict is given."
    if why == "insufficient":
        explanation += " Not enough reliable evidence for a verdict."
    if failed_tools:
        explanation += f" Unavailable tools: {', '.join(sorted(set(failed_tools)))}."
    return {"label": label, "why": why, "strength": strength,
            "basis": [i for i in top if i in by_id], "explanation": explanation}
