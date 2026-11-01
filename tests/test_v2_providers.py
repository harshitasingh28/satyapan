"""Hosted-provider configuration: Hugging Face, or a free OpenAI-compatible provider (Gemini, Groq).

TEST FIXTURES ONLY: the providers are replaced by a scripted fake transport. Keys below are fake.
"""
from __future__ import annotations

import json

import httpx
import pytest

from satyapan.config import get_settings

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ = "https://api.groq.com/openai/v1"


@pytest.fixture
def env(monkeypatch):
    def apply(**values):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        return get_settings()
    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def test_gemini_settings_ignore_leftover_hugging_face_names(env):
    s = env(HF_TOKEN="hf_" + "x" * 34, HF_CHAT_MODEL="Qwen/Qwen3-235B:deepinfra", HF_CHAT_FALLBACK_MODEL="openai/gpt-oss:groq",
            LLM_BASE_URL=GEMINI + "/", LLM_API_KEY="AIza" + "k" * 35, LLM_MODEL="gemini-3.5-flash-lite",
            EMBEDDING_BASE_URL=GEMINI, EMBEDDING_API_KEY="AIza" + "k" * 35, EMBEDDING_MODEL="gemini-embedding-001")
    assert s.llm_model == "gemini-3.5-flash-lite" and s.llm_api_key.startswith("AIza")
    assert s.hf_chat_fallback_model == ""                       # the HF fallback name is not sent to Gemini
    assert s.hf_embedding_provider == "openai" and s.embeddings_configured
    assert s.hf_embedding_model == "gemini-embedding-001"


def test_fallback_runs_on_a_second_provider_with_its_own_key(env):
    from satyapan.http import ApiClient
    from satyapan.llm import chat_json_with_model
    s = env(LLM_BASE_URL=GEMINI, LLM_API_KEY="AIza" + "a" * 35, LLM_MODEL="gemini-3.5-flash-lite",
            LLM_FALLBACK_BASE_URL=GROQ, LLM_FALLBACK_API_KEY="gsk_" + "b" * 40, LLM_FALLBACK_MODEL="openai/gpt-oss-120b")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["authorization"][:11]))
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(429, json={"error": "free tier rate limit"})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]})

    data, model = chat_json_with_model(ApiClient(s, transport=httpx.MockTransport(handler)), "sys", "user")
    assert data == {"ok": True} and model == "openai/gpt-oss-120b"
    assert seen[0] == ("generativelanguage.googleapis.com", "Bearer AIza") and seen[-1] == ("api.groq.com", "Bearer gsk_")


def test_openai_compatible_embeddings_route(env):
    from satyapan.hf import Embedder
    from satyapan.http import ApiClient
    s = env(EMBEDDING_BASE_URL=GEMINI, EMBEDDING_API_KEY="AIza" + "c" * 35, EMBEDDING_MODEL="gemini-embedding-001")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((str(request.url), body["model"], len(body["input"])))
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, float(i), 0.5] + [0.0] * 7}
                                                  for i in range(len(body["input"]))]})

    import satyapan.hf as hf
    hf.get_settings = get_settings          # the module captured the function, the cache was cleared above
    mat = Embedder(ApiClient(s, transport=httpx.MockTransport(handler)), cache={}).embed(["एक", "two"], "passage")
    assert calls == [(GEMINI + "/embeddings", "gemini-embedding-001", 2)]
    assert mat.shape == (2, 10) and abs(float((mat[0] ** 2).sum()) - 1) < 1e-5


def test_provider_keys_are_redacted():
    from satyapan.logging_setup import redact
    text = "error AIza" + "Z" * 35 + " and gsk_" + "Y" * 40 + " and hf_" + "W" * 34
    out = redact(text)
    assert "Z" * 35 not in out and "Y" * 40 not in out and "W" * 34 not in out
