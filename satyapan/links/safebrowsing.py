"""Google Safe Browsing. v5 urls:search first, v4 threatMatches:find as fallback.

v4 is deprecated ("The Safe Browsing APIs (v4) are deprecated", no shutdown date given):
  https://developers.google.com/safe-browsing/v4
v5 urls:search (max 50 URLs, sends raw URLs to Google):
  https://developers.google.com/safe-browsing/reference/rest/v5/urls/search
Terms: non-commercial use only without a separate agreement. When showing a warning you
must attribute it ("Advisory provided by Google") and must not present it as certain.
"""
from __future__ import annotations

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error

V5_URL = "https://safebrowsing.googleapis.com/v5/urls:search"
V4_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]
ATTRIBUTION = "Advisory provided by Google"


def _key() -> str:
    key = get_settings().google_api_key
    if not key:
        raise ToolError(ToolStatus.AUTH_REQUIRED, "GOOGLE_API_KEY not configured")
    return key


def lookup_v5(client: ApiClient, urls: list[str]) -> tuple[dict[str, list[str]], float]:
    params = [("urls", u) for u in urls[:50]] + [("key", _key())]
    resp, ms = client.request("safe_browsing_v5", "GET", V5_URL, params=params)
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    hits: dict[str, list[str]] = {}
    for t in json_or_error(resp, "safe_browsing_v5").get("threats", []):
        hits.setdefault(t.get("url", ""), []).extend(t.get("threatTypes", []))
    return hits, ms


def lookup_v4(client: ApiClient, urls: list[str]) -> tuple[dict[str, list[str]], float]:
    body = {"client": {"clientId": "satyapan", "clientVersion": "0.2"},
            "threatInfo": {"threatTypes": THREAT_TYPES, "platformTypes": ["ANY_PLATFORM"],
                           "threatEntryTypes": ["URL"], "threatEntries": [{"url": u} for u in urls[:500]]}}
    resp, ms = client.request("safe_browsing_v4", "POST", V4_URL, params={"key": _key()}, json=body)
    if resp.status_code == 400 and "API key" in resp.text:
        raise ToolError(ToolStatus.AUTH_REQUIRED, "API key rejected", 400)
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    hits: dict[str, list[str]] = {}
    for m in json_or_error(resp, "safe_browsing_v4").get("matches", []):
        hits.setdefault(m["threat"]["url"], []).append(m["threatType"])
    return hits, ms


def lookup(client: ApiClient, urls: list[str]) -> tuple[dict[str, list[str]], float]:
    try:
        return lookup_v5(client, urls)
    except ToolError as err:
        if err.status in (ToolStatus.AUTH_REQUIRED, ToolStatus.BLOCKED, ToolStatus.RATE_LIMITED):
            raise
        return lookup_v4(client, urls)
