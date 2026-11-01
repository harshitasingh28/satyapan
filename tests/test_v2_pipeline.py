"""Satyapan 2.0 verification rules, offline.

TEST FIXTURES ONLY: the Hugging Face router, the embedding model and the Fact Check API are
replaced by a scripted fake transport inside this file. Release records are fixtures for matching
logic, not real PIB data. Nothing here measures accuracy, it checks that the rules hold.
"""
from __future__ import annotations

import dataclasses
import json
import math
import re
from pathlib import Path

import httpx
import pytest

from satyapan.config import get_settings
from satyapan.http import ApiClient
from satyapan.pipeline.graph import Context, new_state, run, to_report
from satyapan.sources.pib import PibStore

OFFICIAL = {"pib.gov.in", "pmkisan.gov.in"}
REL_A = {"fixture": True, "title": "PM Kisan 21st instalment of Rs 2000 released to farmers",
         "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100005",
         "summary": "The 21st instalment of Rs 2000 was released to 9 crore farmers under PM-KISAN."}
REL_B = {"fixture": True, "title": "Cabinet approves new national highway projects in four states",
         "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100077", "summary": ""}

# test-only "embedding": shared concept dimensions for English and Hindi words, hashing for the rest
CONCEPTS = {"laptop": 0, "लैपटॉप": 0, "student": 1, "students": 1, "छात्रों": 1, "छात्र": 1, "free": 2, "मुफ्त": 2,
            "kisan": 3, "किसान": 3, "farmers": 3, "instalment": 4, "किस्त": 4, "2000": 5, "government": 6, "सरकार": 6}


def fake_vec(text: str) -> list[float]:
    text = text.split("Query: ", 1)[-1].lower()
    v = [0.0] * 32
    for tok in re.findall(r"[^\s.,:!?'\"()]+", text):
        if tok in CONCEPTS:
            v[CONCEPTS[tok]] += 3.0
        else:
            v[8 + (sum(map(ord, tok)) % 24)] += 0.15
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeServices:
    """Scripted stand-ins for the HF router and Google Fact Check. Test fixture only."""

    def __init__(self) -> None:
        self.compare = None          # callable(payload) -> {"pairs": [...]} or an int HTTP status
        self.rewrite = None
        self.factchecks: list[dict] = []
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "factchecktools.googleapis.com":
            self.calls.append("factcheck")
            return httpx.Response(200, json={"claims": self.factchecks})
        if request.url.host != "router.huggingface.co":
            raise httpx.ConnectError("offline test transport", request=request)
        body = json.loads(request.content)
        if "/feature-extraction" in url:
            self.calls.append("embed")
            return httpx.Response(200, json=[fake_vec(t) for t in body["inputs"]])
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        if "extract checkable factual claims" in system:
            self.calls.append("extract")
            return self._chat({"claims": []})
        if "You compare ONE claim" in system:
            self.calls.append("compare")
            out = self.compare(json.loads(user)) if self.compare else {"pairs": []}
            return httpx.Response(out, json={"error": "unavailable"}) if isinstance(out, int) else self._chat(out)
        self.calls.append("rewrite")
        return self._chat(self.rewrite(json.loads(user)) if self.rewrite else {"statements": []})

    @staticmethod
    def _chat(content: dict) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]})


@pytest.fixture
def svc(monkeypatch, tmp_path: Path):
    s = dataclasses.replace(get_settings(), hf_token="hf_" + "t" * 30, llm_base_url="https://router.huggingface.co/v1",
                            llm_api_key="hf_" + "t" * 30, llm_model="Qwen/test:deepinfra", hf_chat_model="Qwen/test",
                            hf_embedding_model="intfloat/multilingual-e5-large-instruct", hf_embedding_provider="hf-inference",
                            google_api_key="test-key")
    import satyapan.hf as hf
    import satyapan.llm as llm
    import satyapan.pipeline.graph as graph
    import satyapan.sources.factcheck as fc
    for mod in (hf, llm, fc):
        monkeypatch.setattr(mod, "get_settings", lambda: s)
    graph._VECTOR_CACHE.clear()
    fake = FakeServices()
    client = ApiClient(s, transport=httpx.MockTransport(fake))

    def make_ctx(releases=(), known=()):
        from satyapan.hf import Embedder
        ctx = Context(client=client, settings=s, pib=PibStore(tmp_path / "pib.jsonl"), official_domains=OFFICIAL,
                      factcheckers={"boomlive.in", "factly.in"}, work_dir=tmp_path / "w", known_claims=list(known),
                      embedder=Embedder(client, cache=graph._VECTOR_CACHE))
        ctx.pib.add([dict(r) for r in releases])
        return ctx
    fake.make_ctx = make_ctx
    return fake


def verdict(ctx, text: str, consent: bool = True):
    st = run(new_state(text=text, consent={"third_party_text": consent}), ctx)
    return to_report(st), st


def supports(evidence_quote: str, claim_quote: str, cid: str = "K1", relation: str = "supports", same=True):
    return lambda payload: {"pairs": [{"candidate": c["candidate"], "same_subject": same, "relation": relation,
                                       "evidence_quote": evidence_quote, "claim_quote": claim_quote}
                                      for c in payload["candidates"] if c["candidate"] == cid]}


PARAPHRASE = "Farmers get Rs 2000 as the 21st PM Kisan instalment, see https://pib.gov.in/PressReleasePage.aspx?PRID=2100005"


def test_route2_paraphrase_linked_to_the_release_is_genuine(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("21st instalment of Rs 2000 was released to 9 crore farmers", "Farmers get Rs 2000")
    rep, st = verdict(ctx, PARAPHRASE)
    assert rep.verdict == "GENUINE"
    ev = [e for e in rep.evidence if e.stance == "supports" and e.strength == "strong"]
    assert ev and ev[0].origin == "ai_comparison" and ev[0].data["route"] == 2
    assert ev[0].quote and ev[0].quote in REL_A["summary"]
    assert rep.ai["comparison"] == "used"


def test_route2_invented_quote_is_rejected(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("Every farmer will also get a free tractor", "Farmers get Rs 2000")
    rep, st = verdict(ctx, PARAPHRASE)
    assert rep.verdict == "UNVERIFIED"
    assert any("evidence quote not found" in p for p in rep.ai["problems"])


def test_route2_wrong_amount_blocks_genuine_even_if_ai_agrees(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("21st instalment of Rs 2000", "Farmers get Rs 6000")
    rep, _ = verdict(ctx, PARAPHRASE.replace("Rs 2000", "Rs 6000"))
    assert rep.verdict == "UNVERIFIED"
    assert any("not confirmed" in e.established and "6000" in e.established for e in rep.evidence)


def test_paraphrase_without_release_link_stays_unverified(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("21st instalment of Rs 2000 was released to 9 crore farmers", "Farmers get Rs 2000")
    rep, _ = verdict(ctx, "Farmers get Rs 2000 as the 21st PM Kisan instalment")
    assert rep.verdict == "UNVERIFIED"
    assert any("not counted as confirmation" in e.established for e in rep.evidence)


def test_ai_veto_blocks_exact_title_route1(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("21st instalment of Rs 2000", "PM Kisan 21st instalment", relation="contradicts")
    rep, _ = verdict(ctx, f"{REL_A['title']}. {REL_A['link']}")
    assert rep.verdict == "UNVERIFIED" and rep.verdict_reason == "ai_veto"


def test_ai_unavailable_keeps_code_only_route1(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = lambda payload: 503
    rep, _ = verdict(ctx, f"{REL_A['title']}. {REL_A['link']}")
    assert rep.verdict == "GENUINE"
    assert rep.ai["comparison"].startswith("failed")
    assert any("AI comparison was unavailable" in lim for lim in rep.limitations)


def test_p3_real_title_with_link_of_another_release_is_not_genuine(offline_client, tmp_path):
    ctx = Context(client=offline_client, settings=get_settings(), pib=PibStore(tmp_path / "p.jsonl"),
                  official_domains=OFFICIAL, work_dir=tmp_path / "w")
    ctx.pib.add([dict(REL_A), dict(REL_B)])
    rep, _ = verdict(ctx, f"{REL_A['title']}. Official: {REL_B['link']}", consent=False)
    assert rep.verdict == "UNVERIFIED" and rep.verdict_reason == "link_mismatch"


def test_p5_old_release_presented_as_new_is_not_genuine(offline_client, tmp_path):
    ctx = Context(client=offline_client, settings=get_settings(), pib=PibStore(tmp_path / "p.jsonl"),
                  official_domains=OFFICIAL, work_dir=tmp_path / "w")
    ctx.pib.add([{**REL_A, "published": "2025-01-15T00:00:00+00:00"}])
    rep, _ = verdict(ctx, f"BREAKING TODAY: {REL_A['title']}. {REL_A['link']}", consent=False)
    assert rep.verdict == "UNVERIFIED" and rep.verdict_reason == "outdated"
    rep2, _ = verdict(ctx, f"{REL_A['title']}. {REL_A['link']}", consent=False)   # same release, no "new" framing
    assert rep2.verdict == "GENUINE"


def _review(text: str, rating: str = "False", site: str = "boomlive.in") -> dict:
    return {"text": text, "claimReview": [{"publisher": {"name": "BOOM", "site": site}, "url": f"https://{site}/fc/1",
                                           "textualRating": rating, "reviewDate": "2026-09-01T00:00:00Z",
                                           "languageCode": "en"}]}


HINDI = "सरकार सभी छात्रों को मुफ्त लैपटॉप दे रही है, अभी आवेदन करें"
REVIEWED = "Government is giving free laptops to all students"


def test_cross_language_factcheck_match_gives_fake(svc):
    svc.factchecks = [_review(REVIEWED)]
    svc.compare = supports("free laptops to all students", "सभी छात्रों को मुफ्त लैपटॉप", cid="F1")
    rep, _ = verdict(svc.make_ctx(), HINDI)
    assert rep.verdict == "FAKE"
    ev = [e for e in rep.evidence if e.stance == "contradicts" and e.origin == "ai_comparison"]
    assert ev and ev[0].strength == "strong" and ev[0].source_url == "https://boomlive.in/fc/1"


def test_similarity_alone_never_gives_fake(svc):
    svc.factchecks = [_review(REVIEWED)]
    svc.compare = lambda payload: 503                      # the AI is down: only embeddings remain
    rep, _ = verdict(svc.make_ctx(), HINDI)
    assert rep.verdict == "UNVERIFIED"
    assert not [e for e in rep.evidence if e.stance == "contradicts" and e.tool == "factcheck_search"]


def test_ai_says_different_claim_no_fake(svc):
    svc.factchecks = [_review(REVIEWED)]
    svc.compare = supports("free laptops to all students", "मुफ्त लैपटॉप", cid="F1", same=False)
    rep, _ = verdict(svc.make_ctx(), HINDI)
    assert rep.verdict == "UNVERIFIED"


def test_conflicting_numbers_block_semantic_fake(svc):
    svc.factchecks = [_review("Government is giving 5000 free laptops to students")]
    svc.compare = supports("free laptops to students", "छात्रों को मुफ्त लैपटॉप", cid="F1")
    rep, _ = verdict(svc.make_ctx(), "सरकार 200 छात्रों को मुफ्त लैपटॉप दे रही है")
    assert rep.verdict == "UNVERIFIED"


def test_llm_output_cannot_set_the_verdict(svc):
    svc.factchecks = [_review(REVIEWED)]
    svc.compare = lambda payload: {"verdict": "GENUINE", "pairs": [{"candidate": "F1", "same_subject": False,
                                   "relation": "insufficient", "evidence_quote": "free laptops", "claim_quote": "मुफ्त लैपटॉप"}]}
    rep, _ = verdict(svc.make_ctx(), HINDI)
    assert rep.verdict == "UNVERIFIED"


def test_no_consent_means_no_ai_or_embedding_calls(svc):
    svc.factchecks = [_review(REVIEWED)]
    rep, _ = verdict(svc.make_ctx([REL_A]), HINDI, consent=False)
    assert not {"embed", "compare", "extract", "rewrite"} & set(svc.calls)
    assert rep.ai["comparison"] == "no_consent"


def test_ai_explanation_is_added_and_labelled(svc):
    ctx = svc.make_ctx([REL_A])
    svc.compare = supports("21st instalment of Rs 2000", "PM Kisan 21st instalment")
    svc.rewrite = lambda payload: {"statements": [{"text": "An official PIB release matches the claim",
                                                    "evidence_ids": [payload["evidence"][0]["id"]]}]}
    rep, _ = verdict(ctx, f"{REL_A['title']}. {REL_A['link']}")
    kinds = {s.kind for s in rep.reason}
    assert rep.verdict == "GENUINE" and kinds == {"verified_fact", "ai_explanation"}
    assert all(s.evidence_ids for s in rep.reason)


def test_query_vectors_use_the_e5_instruction_and_documents_do_not():
    from satyapan.hf import prepare
    m = "intfloat/multilingual-e5-large-instruct"
    assert prepare(m, "x y", "query").startswith("Instruct: ") and prepare(m, "x y", "passage") == "x y"
    assert prepare("intfloat/multilingual-e5-large", "x", "passage") == "passage: x"
