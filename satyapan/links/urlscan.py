"""urlscan.io sandbox scans. Runs in the background, never inside the fast verdict.

Docs: https://docs.urlscan.io/guides/quickstart  (wait >= 30 s, 404 while pending, 410 deleted)
Rate limits: https://docs.urlscan.io/pages/api-rate-limits  (your quotas: GET /api/v1/quotas)
Requires user consent: the link is sent to a third party. Scans are 'unlisted'.
"""
from __future__ import annotations

import time

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error

API = "https://urlscan.io/api/v1"


def _headers() -> dict:
    key = get_settings().urlscan_api_key
    if not key:
        raise ToolError(ToolStatus.AUTH_REQUIRED, "URLSCAN_API_KEY not configured")
    return {"API-Key": key}


def quotas(client: ApiClient) -> dict:
    resp, _ = client.request("urlscan_quotas", "GET", f"{API}/quotas", headers=_headers())
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    return json_or_error(resp, "urlscan_quotas")


def submit(client: ApiClient, url: str) -> dict:
    resp, ms = client.request("urlscan_scan", "POST", f"{API}/scan", headers=_headers(),
                              json={"url": url, "visibility": "unlisted", "tags": ["satyapan"]})
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code == 200:
        return {"status": "submitted", "uuid": body["uuid"], "ms": ms}
    if resp.status_code == 400:
        return {"status": "refused", "message": body.get("message") or body.get("description"), "ms": ms}
    raise ToolError(ToolStatus.SERVICE_ERROR, str(body)[:200] or resp.text[:200], resp.status_code)


def wait(client: ApiClient, uuid: str, first_wait: float = 30, interval: float = 5, timeout: float = 150) -> dict:
    start = time.perf_counter()
    time.sleep(first_wait)
    while time.perf_counter() - start < timeout:
        resp, _ = client.request("urlscan_result", "GET", f"{API}/result/{uuid}/", headers=_headers())
        if resp.status_code == 200:
            return {"status": "done", "result": json_or_error(resp, "urlscan_result"),
                    "elapsed_s": round(time.perf_counter() - start, 1)}
        if resp.status_code == 410:
            return {"status": "deleted"}
        if resp.status_code != 404:
            raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
        time.sleep(interval)
    return {"status": "timeout", "elapsed_s": round(time.perf_counter() - start, 1)}


def summarize(result: dict) -> dict:
    page, task = result.get("page", {}), result.get("task", {})
    overall = result.get("verdicts", {}).get("overall", {})
    return {"submitted_url": task.get("url"), "final_url": page.get("url"), "final_domain": page.get("domain"),
            "redirected": bool(task.get("url") and page.get("url") and task.get("url") != page.get("url")),
            "ip": page.get("ip"), "country": page.get("country"), "malicious": overall.get("malicious"),
            "score": overall.get("score"), "screenshot": f"https://urlscan.io/screenshots/{task.get('uuid')}.png"
            if task.get("uuid") else None}
