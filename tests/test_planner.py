"""The bounded AI planner: what the model may change, and what code keeps fixed. Offline, mocked model."""
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
from satyapan.pipeline.planner import MAX_QUERIES, validate_plan
from satyapan.sources.pib import PibStore

HOAX = "The new 2000 rupee notes have a GPS nano chip that lets the government track them."
REVIEW = {"claim_text": "The new 2000 rupee notes have a GPS nano chip that lets the government track them", "claimant": None, "claim_date": None,
          "publisher": "FACTLY", "site": "factly.in", "url": "https://factly.in/2000-note-gps-chip/",
          "title": "No, the Rs 2000 note has no GPS chip", "review_date": "2016-11-10", "rating": "False",
          "rating_class": "false", "language": "en"}


# ------------------------------------------------------------------ validation (pure code)

def test_queries_cannot_add_numbers_links_or_run_long():
    plan, problems = validate_plan({"factcheck_queries": [
        "2000 rupee note GPS chip",              # kept: 2000 is in the message
        "5000 rupee note GPS chip",              # invented number
        "see https://evil.example/x",            # link
        "one two three four five six seven eight nine ten eleven twelve thirteen",   # too long
    ]}, HOAX, HOAX)
    assert plan["factcheck_queries"] == ["2000 rupee note GPS chip"]
    assert len(problems) == 3


def test_at_most_three_queries_and_no_copy_of_the_claim():
    qs = [HOAX, "gps chip note", "rupee note tracking", "2000 note chip", "note chip government"]
    plan, _ = validate_plan({"factcheck_queries": qs}, HOAX, HOAX)
    assert len(plan["factcheck_queries"]) == MAX_QUERIES
    assert HOAX not in plan["factcheck_queries"]


def test_unknown_tools_and_types_are_ignored():
    plan, problems = validate_plan({"claim_type": "delete_everything", "checks": [
        {"tool": "shell", "use": True}, {"tool": "pib_release_index", "use": False, "why": "not official"}]}, HOAX, HOAX)
    assert plan["claim_type"] == "other"
    assert set(plan["checks"]) == {"pib_release_index"}
    assert any("unknown check" in p for p in problems)


def test_non_json_plan_is_harmless():
    plan, problems = validate_plan("ignore previous instructions", HOAX, HOAX)
    assert plan["factcheck_queries"] == [] and problems


# ------------------------------------------------------------------ in the pipeline (mocked model and search)

@pytest.fixture
def ctx(monkeypatch, tmp_path: Path):
    s = dataclasses.replace(get_settings(), llm_base_url="https://router.huggingface.co/v1", llm_api_key="t" * 20,
                            llm_model="test-model", google_api_key="test-key", hf_embedding_model="")
    client = ApiClient(s, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    return Context(client=client, settings=s, pib=PibStore(tmp_path / "pib.jsonl"),
                   official_domains={"pib.gov.in", "pmkisan.gov.in"}, factcheckers={"factly.in"},
                   work_dir=tmp_path / "w")


def _searches(monkeypatch, by_query: dict):
    seen = []

    def fake_search(client, query=None, **kw):
        seen.append(query)
        return {"reviews": [dict(r) for r in by_query.get(query, [])]}
    monkeypatch.setattr(graph.factcheck, "search", fake_search)
    return seen


def _planner(monkeypatch, plan):
    calls = []

    def fake_chat(client, system, user, max_tokens=900):
        if "You plan which checks" in system:
            calls.append(user)
            if isinstance(plan, Exception):
                raise plan
            return plan, "test-model"
        raise ToolError(ToolStatus.SERVICE_ERROR, "only the planner is mocked here")
    monkeypatch.setattr(graph, "chat_json_with_model", fake_chat)
    monkeypatch.setattr(graph, "llm_extract_claims", lambda *a, **k: ([], []))
    return calls


def check(ctx, text, consent=True):
    st = run(new_state(text=text, consent={"third_party_text": consent}), ctx)
    return to_report(st), st


def test_ai_query_finds_the_fact_check_and_code_still_decides(monkeypatch, ctx):
    seen = _searches(monkeypatch, {"2000 rupee note GPS chip": [REVIEW]})
    _planner(monkeypatch, {"claim_type": "viral_rumour_or_hoax", "language": "en",
                           "checks": [{"tool": "factcheck_search", "use": True, "why": "a viral hoax"}],
                           "factcheck_queries": ["2000 rupee note GPS chip"]})
    rep, st = check(ctx, HOAX)
    assert "2000 rupee note GPS chip" in seen
    fc = [e for e in rep.evidence if e.tool == "factcheck_search"]
    assert fc and fc[0].data["found_by"] == "AI query '2000 rupee note GPS chip'"
    # strength comes from similarity with the ORIGINAL claim, measured by code
    assert fc[0].data["similarity"] >= 85 and fc[0].strength == "strong"
    assert rep.verdict == "FAKE"
    assert rep.ai["plan"]["status"] == "used" and rep.ai["plan"]["claim_type"] == "viral_rumour_or_hoax"


def test_without_the_plan_the_same_hoax_is_unverified(monkeypatch, ctx):
    _searches(monkeypatch, {"2000 rupee note GPS chip": [REVIEW]})
    _planner(monkeypatch, {"factcheck_queries": ["2000 rupee note GPS chip"]})
    rep, st = check(ctx, HOAX, consent=False)          # no consent: the model is never called
    assert rep.ai["plan"]["status"] == "no_consent"
    assert rep.verdict == "UNVERIFIED"


def test_a_query_that_finds_an_unrelated_fact_check_cannot_make_fake(monkeypatch, ctx):
    unrelated = {**REVIEW, "claim_text": "Drinking hot water cures every disease", "url": "https://x.example/hot"}
    _searches(monkeypatch, {"2000 note": [unrelated]})
    _planner(monkeypatch, {"factcheck_queries": ["2000 note"]})
    rep, _ = check(ctx, HOAX)
    assert rep.verdict == "UNVERIFIED"


def test_official_search_is_kept_by_code_when_the_message_names_the_government(monkeypatch, ctx):
    _searches(monkeypatch, {})
    _planner(monkeypatch, {"claim_type": "other", "checks": [{"tool": "pib_release_index", "use": False, "why": "no"}]})
    rep, st = check(ctx, "PM Kisan 21st instalment of Rs 2000 released to farmers")
    dec = {d["check"]: d for d in rep.ai["plan"]["decisions"]}
    assert dec["Official PIB releases"]["run"] is True and dec["Official PIB releases"]["decided_by"] == "code"
    assert any(r.tool == "pib_release_index" and r.status != "SKIPPED_NOT_APPLICABLE" for r in rep.tool_runs)


def test_ai_can_skip_official_search_for_a_non_government_english_claim(monkeypatch, ctx):
    _searches(monkeypatch, {})
    _planner(monkeypatch, {"claim_type": "health_or_science",
                           "checks": [{"tool": "pib_release_index", "use": False, "why": "a health rumour"}]})
    rep, _ = check(ctx, "Drinking hot water every hour stops all viral infections.")
    dec = {d["check"]: d for d in rep.ai["plan"]["decisions"]}
    assert dec["Official PIB releases"] == {**dec["Official PIB releases"], "run": False, "decided_by": "ai"}
    assert any(r.tool == "pib_release_index" and r.status == "SKIPPED_NOT_APPLICABLE" for r in rep.tool_runs)


def test_links_are_always_checked_whatever_the_plan(monkeypatch, ctx):
    _searches(monkeypatch, {})
    _planner(monkeypatch, {"checks": []})
    rep, _ = check(ctx, "Claim your refund https://pmkisan.gov.in.ekyc-update.top/verify")
    dec = {d["check"]: d for d in rep.ai["plan"]["decisions"]}
    assert dec["Link checks (domain rules, RDAP, Safe Browsing)"]["decided_by"] == "code"
    assert rep.verdict == "FAKE"


def test_planner_failure_falls_back_to_the_default_checks(monkeypatch, ctx):
    seen = _searches(monkeypatch, {})
    _planner(monkeypatch, ToolError(ToolStatus.SERVICE_ERROR, "model down"))
    rep, _ = check(ctx, HOAX)
    assert rep.ai["plan"]["status"].startswith("failed")
    assert seen == [HOAX]                          # only the claim as written
    assert rep.verdict == "UNVERIFIED"


def test_injected_plan_cannot_add_facts_or_tools(monkeypatch, ctx):
    seen = _searches(monkeypatch, {})
    _planner(monkeypatch, {"claim_type": "GENUINE", "checks": [{"tool": "mark_genuine", "use": True}],
                           "factcheck_queries": ["9999 crore scheme approved", "https://pib.gov.in fake"]})
    rep, _ = check(ctx, HOAX)
    assert seen == [HOAX]
    assert rep.verdict == "UNVERIFIED"
    assert rep.ai["plan"]["claim_type"] == "other"
    assert len(rep.ai["plan"]["problems"]) >= 3


def test_trace_notes_show_the_plan(monkeypatch, ctx):
    _searches(monkeypatch, {"2000 rupee note GPS chip": [REVIEW]})
    _planner(monkeypatch, {"claim_type": "viral_rumour_or_hoax", "language": "en",
                           "factcheck_queries": ["2000 rupee note GPS chip"]})
    rep, st = check(ctx, HOAX)
    notes = {t["node"]: t.get("notes", []) for t in st["trace"]}
    assert any("AI search query: 2000 rupee note GPS chip" in n for n in notes["plan_checks"])
    assert any(n.startswith("Code decides: FAKE") for n in notes["decide"])
