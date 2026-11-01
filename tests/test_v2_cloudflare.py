"""Cloudflare Workers AI integration, offline.

TEST FIXTURES ONLY: Cloudflare is replaced by a scripted fake transport and the account ID and token
are fake. These tests check request formats, error handling and the free-allocation guard. Whether
the real models answer on the free plan is checked live by integration/run_all.py.
"""
from __future__ import annotations

import json

import httpx
import pytest

from satyapan import cloudflare
from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus

ACCOUNT = "0123456789abcdef0123456789abcdef"
TOKEN = "cf-test-token-" + "x" * 26
CF = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai"


@pytest.fixture
def cf(monkeypatch):
    def apply(**extra):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
        for k, v in extra.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        return get_settings()
    cloudflare.reset_guard()
    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()
    cloudflare.reset_guard()


def client_for(settings, handler):
    from satyapan.http import ApiClient
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)
    return ApiClient(settings, transport=httpx.MockTransport(wrapped)), calls


def chat_ok(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]})


def test_defaults_and_independent_providers(cf, monkeypatch):
    s = cf()
    assert s.chat_provider == "cloudflare" and s.llm_base_url == f"{CF}/v1" and s.llm_api_key == TOKEN
    assert s.llm_model == "@cf/qwen/qwen3-30b-a3b-fp8" and s.hf_chat_fallback_model.startswith("@cf/")
    assert s.hf_embedding_provider == "cloudflare" and s.hf_embedding_model == "@cf/baai/bge-m3" and s.embeddings_configured
    s2 = cf(AI_EMBEDDING_PROVIDER="huggingface", HF_TOKEN="hf_" + "y" * 34, HF_EMBEDDING_MODEL="intfloat/multilingual-e5-large")
    assert s2.chat_provider == "cloudflare" and s2.hf_embedding_provider == "hf-inference"
    s3 = cf(AI_CHAT_PROVIDER="none")
    assert not s3.llm_configured and s3.embeddings_configured
    for k in ("AI_EMBEDDING_PROVIDER", "AI_CHAT_PROVIDER", "HF_TOKEN", "HF_EMBEDDING_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "../../evil")
    get_settings.cache_clear()
    bad = get_settings()
    assert not bad.llm_configured and not bad.embeddings_configured and "32-character" in bad.cloudflare_note


def test_chat_request_format_and_thinking_switch(cf):
    from satyapan.llm import chat_json_with_model
    s = cf()

    def handler(request):
        assert str(request.url) == f"{CF}/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        body = json.loads(request.content)
        assert body["model"] == "@cf/qwen/qwen3-30b-a3b-fp8" and body["messages"][1]["content"].endswith("/no_think")
        return chat_ok({"ok": True})
    client, calls = client_for(s, handler)
    data, model = chat_json_with_model(client, "sys", "user")
    assert data == {"ok": True} and model == "@cf/qwen/qwen3-30b-a3b-fp8" and len(calls) == 1


def test_json_mode_rejection_is_retried_without_response_format(cf):
    from satyapan.llm import chat_json
    s = cf()

    def handler(request):
        body = json.loads(request.content)
        if "response_format" in body:
            return httpx.Response(400, json={"success": False, "errors": [{"code": 5006, "message": "bad input"}]})
        return chat_ok({"claims": []})
    client, calls = client_for(s, handler)
    assert chat_json(client, "sys", "user") == {"claims": []} and len(calls) == 2


def test_embeddings_native_endpoint_and_both_response_shapes(cf):
    from satyapan.hf import Embedder
    s = cf()
    shape = {"n": 0}

    def handler(request):
        assert str(request.url) == f"{CF}/run/@cf/baai/bge-m3"
        body = json.loads(request.content)
        vecs = [[1.0, float(i + 1)] + [0.0] * 1022 for i in range(len(body["text"]))]
        shape["n"] += 1
        result = {"shape": [len(vecs), 1024], "data": vecs} if shape["n"] == 1 else {"response": vecs}
        return httpx.Response(200, json={"result": result, "success": True, "errors": []})
    client, _ = client_for(s, handler)
    emb = Embedder(client, cache={})
    a = emb.embed(["PM Kisan", "पीएम किसान"], "passage")
    b = emb.embed(["పీఎం కిసాన్"], "query")
    assert a.shape == (2, 1024) and b.shape == (1, 1024)


def test_daily_free_allocation_stops_further_calls_until_midnight_utc(cf):
    from satyapan.llm import chat_json
    s = cf(CLOUDFLARE_CHAT_FALLBACK_MODEL="@cf/meta/llama-4-scout-17b-16e-instruct")

    def handler(request):
        return httpx.Response(429, json={"success": False, "errors": [
            {"code": 3036, "message": "Account limited: you have used up your daily free allocation of 10,000 neurons"}]})
    client, calls = client_for(s, handler)
    with pytest.raises(ToolError) as first:
        chat_json(client, "sys", "user")
    assert first.value.status == ToolStatus.RATE_LIMITED and "resets at 00:00 UTC" in first.value.message
    assert len(calls) == 1                         # the fallback on the same account is not tried
    with pytest.raises(ToolError) as second:
        chat_json(client, "sys", "user")
    assert second.value.status == ToolStatus.RATE_LIMITED and len(calls) == 1   # no network call at all


def test_paid_only_model_falls_back_to_the_next_model(cf):
    from satyapan.llm import chat_json_with_model
    s = cf(CLOUDFLARE_CHAT_MODEL="@cf/some/paid-model", CLOUDFLARE_CHAT_FALLBACK_MODEL="@cf/qwen/qwen3-30b-a3b-fp8")

    def handler(request):
        if json.loads(request.content)["model"] == "@cf/some/paid-model":
            return httpx.Response(403, json={"success": False, "errors": [{"code": 5035, "message": "requires paid"}]})
        return chat_ok({"ok": 1})
    client, _ = client_for(s, handler)
    data, model = chat_json_with_model(client, "sys", "user")
    assert model == "@cf/qwen/qwen3-30b-a3b-fp8"


def test_error_translation():
    t = cloudflare.translate(ToolError(ToolStatus.SERVICE_ERROR, json.dumps({"errors": [{"code": 5035}]}), 403))
    assert t.status == ToolStatus.AUTH_REQUIRED and "Workers Paid plan" in t.message
    t = cloudflare.translate(ToolError(ToolStatus.RATE_LIMITED, json.dumps({"errors": [{"code": 3040}]}), 429))
    assert t.status == ToolStatus.RATE_LIMITED and "capacity" in t.message
    cloudflare.reset_guard()


def test_investigation_still_completes_when_the_free_allocation_is_used_up(cf, tmp_path):
    from satyapan.http import ApiClient
    from satyapan.pipeline.graph import Context, new_state, run, to_report
    from satyapan.sources.pib import PibStore
    s = cf()
    cloudflare.mark_exhausted()
    hits = []

    def handler(request):
        hits.append(request.url.host)
        raise httpx.ConnectError("offline test transport", request=request)
    ctx = Context(client=ApiClient(s, transport=httpx.MockTransport(handler)), settings=s,
                  pib=PibStore(tmp_path / "p.jsonl"), official_domains={"pib.gov.in"}, work_dir=tmp_path / "w")
    rep = to_report(run(new_state(text="Free laptops for all students. Register at http://free-laptop-gov.top/apply",
                                  consent={"third_party_text": True}), ctx))
    assert rep.verdict in ("FAKE", "UNVERIFIED")
    assert "api.cloudflare.com" not in hits
    assert any(t.tool == "llm_claims" and t.status == "RATE_LIMITED" for t in rep.tool_runs)
