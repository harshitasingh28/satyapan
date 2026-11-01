"""Matching a message to fact-checks that an AI planner query found, or that are in another language.

Offline: the model, the fact-check search and the embeddings are mocked inside this file. These tests check
the rules (what can count, and how much), not accuracy.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import numpy as np
import pytest

import satyapan.pipeline.compare as compare_mod
import satyapan.pipeline.graph as graph
from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.pipeline.graph import Context, new_state, run, to_report
from satyapan.sources.pib import PibStore

HOAX = "The new 2000 rupee notes have a GPS nano chip that lets the government track them."
HINDI_DENIAL = "2000 रुपये के नोट में जीपीएस चिप नहीं है"


def review(claim_text: str, site: str, lang: str = "en", rating: str = "False") -> dict:
    return {"claim_text": claim_text, "claimant": None, "claim_date": None, "publisher": site.split(".")[0].upper(),
            "site": site, "url": f"https://{site}/fc/{abs(hash(claim_text)) % 1000}", "title": "Fact check",
            "review_date": "2016-11-12", "rating": rating, "rating_class": "false" if rating == "False" else "true",
            "language": lang}


R_FACTLY = review("Rs 2000 notes contain a nano GPS chip for tracking", "factly.in")
R_BOOM = review("New 2000 notes come with a GPS chip so they can be traced", "boomlive.in")
R_FAR = review("Rs 2000 notes will be withdrawn from circulation", "altnews.in")


@pytest.fixture
def ctx(tmp_path: Path):
    s = dataclasses.replace(get_settings(), llm_base_url="https://router.huggingface.co/v1", llm_api_key="t" * 20,
                            llm_model="test-model", google_api_key="test-key", hf_embedding_model="test-embed")
    client = ApiClient(s, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    return Context(client=client, settings=s, pib=PibStore(tmp_path / "pib.jsonl"),
                   official_domains={"pib.gov.in"}, factcheckers={"factly.in", "boomlive.in", "altnews.in"},
                   work_dir=tmp_path / "w", embedder=object())


def setup(monkeypatch, *, queries, by_query, cosines, compare_answer):
    """queries: what the planner writes. by_query: search query -> reviews. cosines: reviewed text -> cosine
    with the claim. compare_answer: candidate text -> (relation, same_subject, evidence_quote, claim_quote)."""
    seen = {"compared": []}

    def fake_search(client, query=None, **kw):
        return {"reviews": [dict(r) for r in by_query.get(query, [])]}

    def fake_planner(client, system, user, max_tokens=900):
        if "You plan which checks" in system:
            return {"claim_type": "viral_rumour_or_hoax", "factcheck_queries": queries}, "test-model"
        raise ToolError(ToolStatus.SERVICE_ERROR, "not mocked")

    def fake_compare(client, system, user, max_tokens=900):
        import json
        payload = json.loads(user)
        pairs = []
        for c in payload["candidates"]:
            seen["compared"].append(c["text"])
            if c["text"] in compare_answer:
                rel, same, ev, cl = compare_answer[c["text"]]
                pairs.append({"candidate": c["candidate"], "relation": rel, "same_subject": same,
                              "evidence_quote": ev, "claim_quote": cl})
        return {"pairs": pairs}, "test-model"

    def fake_embed(state, ctx, texts, kind, target):
        if kind == "query":
            return np.array([[1.0, 0.0]])
        return np.array([[cosines.get(t, 0.1), (1 - cosines.get(t, 0.1) ** 2) ** 0.5] for t in texts])

    monkeypatch.setattr(graph.factcheck, "search", fake_search)
    monkeypatch.setattr(graph, "chat_json_with_model", fake_planner)
    monkeypatch.setattr(compare_mod, "chat_json_with_model", fake_compare)
    monkeypatch.setattr(graph, "llm_extract_claims", lambda *a, **k: ([], []))
    monkeypatch.setattr(graph, "_embed", fake_embed)
    return seen


def check(ctx, text):
    st = run(new_state(text=text, consent={"third_party_text": True}), ctx)
    return to_report(st), st


def notes(st, node):
    return [n for t in st["trace"] if t["node"] == node for n in t.get("notes", [])]


SAME = ("contain a nano GPS chip for tracking", "have a GPS nano chip")


def test_ai_query_finds_a_looser_match_that_counts_only_as_moderate(monkeypatch, ctx):
    setup(monkeypatch, queries=["2000 note GPS chip"], by_query={"2000 note GPS chip": [R_FACTLY]},
          cosines={R_FACTLY["claim_text"]: 0.72}, compare_answer={R_FACTLY["claim_text"]: ("supports", True, *SAME)})
    rep, st = check(ctx, HOAX)
    ev = [e for e in rep.evidence if e.origin == "ai_comparison" and e.stance == "contradicts"]
    assert ev and ev[0].strength == "moderate" and ev[0].source_url == R_FACTLY["url"]
    assert "second, independent source" in ev[0].established
    assert rep.verdict == "UNVERIFIED"                       # one looser match is never decisive alone
    assert any("F1: FACTLY reviewed a similar claim" in n and "AI query" in n for n in notes(st, "check_factchecks"))


def test_two_independent_looser_matches_make_it_fake(monkeypatch, ctx):
    setup(monkeypatch, queries=["2000 note GPS chip"], by_query={"2000 note GPS chip": [R_FACTLY, R_BOOM]},
          cosines={R_FACTLY["claim_text"]: 0.72, R_BOOM["claim_text"]: 0.70},
          compare_answer={R_FACTLY["claim_text"]: ("supports", True, *SAME),
                          R_BOOM["claim_text"]: ("supports", True, "come with a GPS chip", "have a GPS nano chip")})
    rep, _ = check(ctx, HOAX)
    assert rep.verdict == "FAKE"
    assert {e.source_url for e in rep.evidence if e.origin == "ai_comparison" and e.stance == "contradicts"} \
        == {R_FACTLY["url"], R_BOOM["url"]}


def test_a_distant_review_is_not_even_compared(monkeypatch, ctx):
    seen = setup(monkeypatch, queries=["2000 note"], by_query={"2000 note": [R_FAR]},
                 cosines={R_FAR["claim_text"]: 0.55}, compare_answer={R_FAR["claim_text"]: ("supports", True, *SAME)})
    rep, st = check(ctx, HOAX)
    assert R_FAR["claim_text"] not in seen["compared"]
    assert rep.verdict == "UNVERIFIED"
    assert any("not close enough to compare (best embedding similarity 0.55)" in n for n in notes(st, "check_factchecks"))


def test_the_lower_bar_is_only_for_ai_queries_and_other_languages(monkeypatch, ctx):
    # the same review found by the claim as written, in the same language: the normal 0.80 bar applies
    seen = setup(monkeypatch, queries=[], by_query={HOAX: [R_FACTLY]},
                 cosines={R_FACTLY["claim_text"]: 0.72}, compare_answer={R_FACTLY["claim_text"]: ("supports", True, *SAME)})
    rep, _ = check(ctx, HOAX)
    assert R_FACTLY["claim_text"] not in seen["compared"]
    assert rep.verdict == "UNVERIFIED"


def test_a_message_that_denies_the_reviewed_claim_is_not_matched(monkeypatch, ctx):
    r = review("Rs 2000 notes have a GPS chip", "factly.in")
    setup(monkeypatch, queries=[], by_query={HINDI_DENIAL: [r]}, cosines={r["claim_text"]: 0.9},
          compare_answer={r["claim_text"]: ("supports", True, "notes have a GPS chip", "नोट में जीपीएस चिप")})
    rep, st = check(ctx, HINDI_DENIAL)
    assert not [e for e in rep.evidence if e.stance == "contradicts" and e.tool == "factcheck_search"]
    assert any(e.data.get("negation_mismatch") for e in rep.evidence)
    assert rep.verdict == "UNVERIFIED"


def test_contradicts_on_a_reviewed_claim_never_counts_as_a_match(monkeypatch, ctx):
    setup(monkeypatch, queries=["2000 note GPS chip"], by_query={"2000 note GPS chip": [R_FACTLY, R_BOOM]},
          cosines={R_FACTLY["claim_text"]: 0.9, R_BOOM["claim_text"]: 0.9},
          compare_answer={R_FACTLY["claim_text"]: ("contradicts", True, *SAME),
                          R_BOOM["claim_text"]: ("contradicts", True, "come with a GPS chip", "have a GPS nano chip")})
    rep, _ = check(ctx, HOAX)
    assert not [e for e in rep.evidence if e.origin == "ai_comparison" and e.stance == "contradicts"]
    assert rep.verdict == "UNVERIFIED"


def test_prompt_separates_same_claim_from_truth():
    p = compare_mod.COMPARE_PROMPT
    assert "You are NOT judging whether it is true" in p
    assert "3 to 15 consecutive words copied EXACTLY" in p
