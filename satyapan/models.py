"""Data records passed between pipeline stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

Stance = Literal["supports", "contradicts", "neutral"]
Strength = Literal["strong", "moderate", "weak", "none"]
Kind = Literal["fact_check", "official_record", "provenance", "credentials",
               "synthetic_signal", "link_risk", "context"]
VerdictLabel = Literal["GENUINE", "FAKE", "UNVERIFIED"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Claim:
    id: str
    text: str
    source: str                     # "user_text", "ocr:<media id>", "llm"
    language: str                   # "en", "hi", "te", "mixed", "unknown"
    entities: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    calls_to_action: list[str] = field(default_factory=list)
    checkworthiness: float = 0.0


@dataclass
class Evidence:
    id: str
    tool: str
    source_name: str
    source_url: str | None
    target: str                     # claim id, link URL or media id
    kind: Kind
    stance: Stance
    strength: Strength
    established: str                # what the tool established, in plain words, from data only
    independence_key: str           # evidence with the same key counts once
    limitations: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    retrieved_at: str = field(default_factory=now_iso)
    external: bool = True           # False for local algorithms
    # 2.0: where the evidence came from, the exact text quoted from the source (checked in code),
    # and when the source says it was published.
    origin: str = ""                # api | official_index | local_algorithm | deterministic_check | ai_comparison
    quote: str | None = None
    published_at: str | None = None


@dataclass
class ToolRun:
    tool: str
    status: str
    target: str
    ms: float
    detail: str = ""


@dataclass
class Statement:
    text: str
    evidence_ids: list[str]
    kind: str = "verified_fact"     # verified_fact | ai_explanation | unavailable


@dataclass
class Report:
    investigation_id: str
    claim: Claim | None
    verdict: VerdictLabel
    strength_explanation: str
    reason: list[Statement]
    evidence: list[Evidence]
    media_assessment: dict
    limitations: list[str]
    tool_runs: list[ToolRun]
    trace: list[dict]
    created_at: str = field(default_factory=now_iso)
    claims: list[Claim] = field(default_factory=list)
    verdict_reason: str = ""
    evidence_strength: str = "n/a"
    ai: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
