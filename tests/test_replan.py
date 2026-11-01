"""The one bounded re-plan: when the first searches find nothing usable, the AI sees what came back and may write
up to 2 new queries, once. Offline, with the model and the fact-check search mocked in this file."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import pytest

import satyapan.pipeline.graph as graph
from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.pipeline.graph import Context, new_state, run, to_report
from satyapan.sources.pib import PibStore

HOAX = "The new 2000 rupee notes have a GPS nano chip that lets the government track them."
REVIEW = {"claim_text": "The new 2000 rupee notes have a GPS nano chip that lets the government track them", "claimant": None,
          "claim_date": None, "publisher": "FACTLY", "site": "factly.in", "url": "https://factly.in/2000-note-gps-chip/",
          "title": "No, the Rs 2000 note has no GPS chip", "review_date": "2016-11-10", "rating": "False",
          "rating_class": "false", "language": "en"}
UNRELATED = {**REVIEW, "claim_text": "Rs 2000 notes will be withdrawn from circulation", "url": "https://x.example/withdrawn"}


@pytest.fixture
def ctx(tmp_path: Path):
    s = dataclasses.replace(get_settings(), llm_base_url="https://router.huggingface.co/v1", llm_api_key="t" * 20,
                            llm_model="test-model", google_api_key="test-key", hf_embedding_model="")
    client = ApiClient(s, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    return Context(client=client, settings=s, pib=PibStore(tmp_path / "pib.jsonl"),
                   official_domains={"pib.gov.in"}, factcheckers={"factly.in"}, work_dir=tmp_path / "w")


def mock(monkeypatch, plan, replan, by_query):
    calls = {"plan": 0, "replan": 0, "searches": []}

    def fake_chat(client, system, user, max_tokens=900):
        if "You plan which checks" in system:
            calls["plan"] += 1
            return plan, "test-model"
        if "You planned fact-check searches" in system:
            calls["replan"] += 1
            calls["replan_brief"] = user
            if isinstance(replan, Exception):
                raise replan
            return replan, "test-model"
        raise ToolError(ToolStatus.SERVICE_ERROR, "not mocked")

    def fake_search(client, query=None, **kw):
        calls["searches"].append(query)
        return {"reviews": [dict(r) for r in by_query.get(query, [])]}

    monkeypatch.setattr(graph, "chat_json_with_model", fake_chat)
    monkeypatch.setattr(graph.factcheck, "search", fake_search)
    monkeypatch.setattr(graph, "llm_extract_claims", lambda *a, **k: ([], []))
    return calls


def check(ctx, text=HOAX):
    st = run(new_state(text=text, consent={"third_party_text": True}), ctx)
    return to_report(st), st


def notes(st):
    return [n for t in st["trace"] if t["node"] == "check_factchecks" for n in t.get("notes", [])]


HOAX_PLAN = {"claim_type": "viral_rumour_or_hoax", "factcheck_queries": ["currency tracking technology"]}


def test_replan_finds_the_fact_check_the_first_searches_missed(monkeypatch, ctx):
    calls = mock(monkeypatch, HOAX_PLAN,
                 {"factcheck_queries": ["2000 rupee note GPS chip"], "why": "use the words a fact-check would use"},
                 {"currency tracking technology": [UNRELATED], "2000 rupee note GPS chip": [REVIEW]})
    rep, st = check(ctx)
    assert calls["replan"] == 1 and "2000 rupee note GPS chip" in calls["searches"]
    assert "Rs 2000 notes will be withdrawn" in calls["replan_brief"]       # the AI saw what came back
    assert rep.verdict == "FAKE"
    fc = [e for e in rep.evidence if e.tool == "factcheck_search" and e.stance == "contradicts"]
    assert fc and fc[0].data["found_by"] == "AI re-plan query '2000 rupee note GPS chip'"
    rp = rep.ai["plan"]["replan"]
    assert rp["status"] == "used" and rp["queries"] == ["2000 rupee note GPS chip"] and rp["found"] == 1
    assert any("re-planned once" in n for n in notes(st))


def test_no_replan_when_the_first_searches_already_found_evidence(monkeypatch, ctx):
    calls = mock(monkeypatch, {**HOAX_PLAN, "factcheck_queries": ["2000 rupee note GPS chip"]},
                 {"factcheck_queries": ["anything"]}, {"2000 rupee note GPS chip": [REVIEW]})
    rep, _ = check(ctx)
    assert calls["replan"] == 0 and rep.verdict == "FAKE"
    assert "replan" not in rep.ai["plan"]


def test_no_replan_for_link_scams(monkeypatch, ctx):
    calls = mock(monkeypatch, {"claim_type": "scam_or_phishing", "factcheck_queries": ["kyc scam"]},
                 {"factcheck_queries": ["anything"]}, {})
    check(ctx, "Update your KYC today or your account is blocked https://sbi-kyc-update.top/login")
    assert calls["replan"] == 0


def test_replan_queries_obey_the_same_rules(monkeypatch, ctx):
    calls = mock(monkeypatch, HOAX_PLAN,
                 {"factcheck_queries": ["5000 rupee note GPS chip", "currency tracking technology",
                                        "see https://evil.example/x"]}, {})
    rep, st = check(ctx)
    searches_after_plan = calls["searches"][2:]                # the claim as written, then the plan's one query
    assert searches_after_plan == []
    problems = rep.ai["plan"]["replan"]["problems"]
    assert len(problems) == 3
    assert any("(5000)" in p for p in problems) and any("repeats an earlier search" in p for p in problems)
    assert rep.verdict == "UNVERIFIED"


def test_replan_happens_at_most_once(monkeypatch, ctx):
    calls = mock(monkeypatch, HOAX_PLAN, {"factcheck_queries": ["new rupee note features"]},
                 {"new rupee note features": [UNRELATED]})
    rep, st = check(ctx)
    assert calls["replan"] == 1 and calls["plan"] == 1
    assert rep.verdict == "UNVERIFIED"


def test_replan_failure_is_harmless(monkeypatch, ctx):
    mock(monkeypatch, HOAX_PLAN, ToolError(ToolStatus.SERVICE_ERROR, "model down"), {})
    rep, st = check(ctx)
    assert rep.ai["plan"]["replan"]["status"].startswith("failed")
    assert rep.verdict == "UNVERIFIED"
    assert any("re-plan was unavailable" in n for n in notes(st))
