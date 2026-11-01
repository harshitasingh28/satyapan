"""Evidence collection helpers and ranking (modules 8 and 9).

Ranking rules
  * Weight: strong 3, moderate 2, weak 1.
  * Independence: evidence sharing an independence_key counts once (the strongest).
    Ten fact-check pages copying one PIB post are one source, not ten.
  * Conflict: strong support and strong contradiction at the same time.
"""
from __future__ import annotations

from satyapan.models import Evidence

WEIGHT = {"strong": 3, "moderate": 2, "weak": 1, "none": 0}

API_TOOLS = {"factcheck_search", "factcheck_image_search", "safe_browsing", "rdap", "wikidata", "urlscan",
             "cloud_vision_web", "sightengine_genai", "virustotal_url"}


def origin_of(tool: str, external: bool) -> str:
    if tool in API_TOOLS or tool.startswith("safe_browsing") or tool.startswith("rdap"):
        return "api"
    if tool == "pib_release_index":
        return "official_index"
    if tool in ("url_rules", "url_analysis", "domain_rules"):
        return "deterministic_check"
    if tool == "ai_comparison":
        return "ai_comparison"
    return "api" if external else "local_algorithm"


class EvidenceLog:
    def __init__(self) -> None:
        self.items: list[Evidence] = []

    def add(self, **fields) -> Evidence:
        fields.setdefault("origin", origin_of(fields.get("tool", ""), fields.get("external", True)))
        ev = Evidence(id=f"E{len(self.items) + 1}", **fields)
        self.items.append(ev)
        return ev


def aggregate(evidence: list[Evidence]) -> dict:
    groups: dict[str, dict[str, Evidence]] = {"contradicts": {}, "supports": {}}
    for e in evidence:
        if e.stance == "neutral" or WEIGHT[e.strength] == 0:
            continue
        g = groups[e.stance]
        cur = g.get(e.independence_key)
        if cur is None or WEIGHT[e.strength] > WEIGHT[cur.strength]:
            g[e.independence_key] = e
    out = {}
    for stance, g in groups.items():
        out[stance] = {"score": sum(WEIGHT[e.strength] for e in g.values()),
                       "strong": [e.id for e in g.values() if e.strength == "strong"],
                       "counted": [e.id for e in g.values()],
                       "groups": len(g)}
    out["conflict"] = bool(out["contradicts"]["strong"] and out["supports"]["strong"])
    return out
