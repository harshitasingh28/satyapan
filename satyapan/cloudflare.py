"""Cloudflare Workers AI (hosted, free plan friendly): error handling, free-allocation guard, embeddings.

Endpoints (official REST API, https://developers.cloudflare.com/workers-ai/):
  chat        POST https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions  (OpenAI format)
  embeddings  POST https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}  {"text": [...]}
  token check GET  https://api.cloudflare.com/client/v4/user/tokens/verify
Auth: Authorization: Bearer CLOUDFLARE_API_TOKEN.

Free plan: 10,000 neurons a day, reset at 00:00 UTC. When it is used up, Workers AI answers HTTP 429
with error 3036 ("used up your daily free allocation"). It does not start charging: billing exists
only on the Workers Paid plan, and Satyapan never changes plans. After a 3036 this module stops
calling Cloudflare until the next 00:00 UTC, so a busy demo does not hammer a closed door, and the
investigation continues with code-only evidence.

Other codes handled: 3040 out of capacity (retry later or use the fallback model), 5035 model needs
the Workers Paid plan (choose another model), 3007 and 3008 timeout, 5007 and 3042 unknown model,
10000 authentication error.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

from satyapan.errors import ToolError, ToolStatus

_lock = threading.Lock()
_exhausted_until: datetime | None = None

FRIENDLY = {
    3036: (ToolStatus.RATE_LIMITED, "Cloudflare free daily allocation (10,000 neurons) is used up. It resets at 00:00 UTC."),
    3040: (ToolStatus.RATE_LIMITED, "Cloudflare Workers AI is temporarily out of capacity for this model. Try again shortly."),
    5035: (ToolStatus.AUTH_REQUIRED, "This model needs the Workers Paid plan. Choose a free-plan model in .env."),
    3007: (ToolStatus.SERVICE_ERROR, "Cloudflare Workers AI timed out."),
    3008: (ToolStatus.SERVICE_ERROR, "Cloudflare Workers AI aborted the request."),
    5007: (ToolStatus.SERVICE_ERROR, "Unknown Workers AI model. Check the model name in .env."),
    3042: (ToolStatus.SERVICE_ERROR, "Invalid Workers AI model name. Check the model name in .env."),
    10000: (ToolStatus.AUTH_REQUIRED, "Cloudflare rejected the API token. Check CLOUDFLARE_API_TOKEN and its Workers AI permission."),
}


def is_cloudflare(url: str | None) -> bool:
    return bool(url) and "api.cloudflare.com/" in url


def _next_utc_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def guard(now: datetime | None = None) -> None:
    """Raise RATE_LIMITED without a network call while the free allocation is known to be used up."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        until = _exhausted_until
    if until and now < until:
        minutes = int((until - now).total_seconds() // 60)
        raise ToolError(ToolStatus.RATE_LIMITED, f"Cloudflare free daily allocation is used up. It resets at 00:00 UTC "
                                                 f"(in about {minutes} minutes). Code-only checks still run.")


def mark_exhausted(now: datetime | None = None) -> None:
    global _exhausted_until
    with _lock:
        _exhausted_until = _next_utc_midnight(now or datetime.now(timezone.utc))


def reset_guard() -> None:
    global _exhausted_until
    with _lock:
        _exhausted_until = None


def error_codes(text: str) -> list[int]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None
    codes = []
    if isinstance(data, dict):
        for e in data.get("errors") or []:
            if isinstance(e, dict) and isinstance(e.get("code"), int):
                codes.append(e["code"])
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("code"), int):
            codes.append(err["code"])
    for code in FRIENDLY:                      # the code may only appear inside a message string
        if str(code) in (text or "") and code not in codes and code != 10000:
            codes.append(code)
    if "daily free allocation" in (text or "").lower() and 3036 not in codes:
        codes.append(3036)
    return codes


def translate(err: ToolError) -> ToolError:
    """Map a Cloudflare error body to a clear status and message. Records a used-up free allocation."""
    codes = error_codes(err.message)
    for code in codes:
        if code in FRIENDLY:
            if code == 3036:
                mark_exhausted()
            status, text = FRIENDLY[code]
            return ToolError(status, f"{text} (Cloudflare error {code})", err.http_status)
    return err


def check_response(resp) -> None:
    """Raise a translated ToolError for a non-200 Cloudflare response."""
    if resp.status_code != 200:
        raise translate(ToolError(ToolStatus.SERVICE_ERROR, resp.text[:300], resp.status_code))


def parse_embeddings(payload: dict, n: int) -> list:
    """Embedding vectors from a Workers AI /ai/run response. Accepts the documented envelope
    {"result": {...}, "success": true} with the vectors under "data" (shape + data, as other BGE models
    return) or "response" (list of vectors or of objects with an "embedding")."""
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ToolError(ToolStatus.SERVICE_ERROR, f"Workers AI error: {json.dumps(payload)[:200]}")
    result = payload.get("result", payload)
    rows = None
    if isinstance(result, dict):
        rows = result.get("data") if result.get("data") is not None else result.get("response")
    elif isinstance(result, list):
        rows = result
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        rows = [r.get("embedding") or r.get("vector") or r.get("values") for r in rows]
    if not isinstance(rows, list) or len(rows) != n or any(not isinstance(r, list) for r in rows):
        raise ToolError(ToolStatus.SERVICE_ERROR, "unexpected Workers AI embedding response shape")
    return rows


def embed(client, base_url: str, api_key: str, model: str, batch: list[str]) -> np.ndarray:
    from satyapan.hf import _as_matrix
    guard()
    try:
        resp, _ = client.request("hf_embeddings", "POST", f"{base_url}/run/{model}",
                                 json={"text": batch, "truncate_inputs": True},
                                 headers={"Authorization": f"Bearer {api_key}"})
    except ToolError as err:
        raise translate(err) from None
    check_response(resp)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ToolError(ToolStatus.SERVICE_ERROR, "Workers AI returned non-JSON") from exc
    return _as_matrix(parse_embeddings(payload, len(batch)), len(batch))


def verify_token(client, api_key: str) -> dict:
    """Cloudflare's own token check. Returns {"status": "active", ...} for a usable token."""
    resp, _ = client.request("cloudflare_token", "GET", "https://api.cloudflare.com/client/v4/user/tokens/verify",
                             headers={"Authorization": f"Bearer {api_key}"})
    check_response(resp)
    data = resp.json()
    return {"status": (data.get("result") or {}).get("status"), "success": data.get("success")}
