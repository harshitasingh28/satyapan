"""Google Fact Check Tools API (Claim Search).

Docs: https://developers.google.com/fact-check/tools/api
      https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
      https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/imageSearch
Auth: API key. Quota: shown in the Google Cloud console, not published.
"""
from __future__ import annotations

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error

BASE = "https://factchecktools.googleapis.com/v1alpha1"

MIXED = ("partly", "partially", "half", "mixture", "mostly")
FALSE = ("false", "fake", "misleading", "altered", "manipulated", "doctored", "edited", "scam", "hoax",
         "fabricated", "out of context", "missing context", "incorrect", "not true", "untrue",
         "गलत", "फर्जी", "फ़र्ज़ी", "भ्रामक", "झूठ", "फेक", "తప్పు", "నకిలీ")
TRUE = ("true", "correct", "accurate", "सही", "सच", "నిజం")


def rating_class(rating: str | None) -> str:
    text = (rating or "").strip().lower()
    if not text:
        return "unknown"
    if any(w in text for w in MIXED):
        return "mixed"
    if any(w in text for w in FALSE):
        return "false"
    if any(w in text for w in TRUE):
        return "true"
    return "other"


def _flatten(claim: dict) -> list[dict]:
    out = []
    for rv in claim.get("claimReview", []):
        pub = rv.get("publisher", {})
        out.append({"claim_text": claim.get("text") or "", "claimant": claim.get("claimant"),
                    "claim_date": claim.get("claimDate"), "publisher": pub.get("name"),
                    "site": pub.get("site"), "url": rv.get("url"), "title": rv.get("title"),
                    "review_date": rv.get("reviewDate"), "rating": rv.get("textualRating"),
                    "rating_class": rating_class(rv.get("textualRating")), "language": rv.get("languageCode")})
    return out


def _get(client: ApiClient, tool: str, path: str, params: dict) -> tuple[dict, float]:
    key = get_settings().google_api_key
    if not key:
        raise ToolError(ToolStatus.AUTH_REQUIRED, "GOOGLE_API_KEY not configured")
    resp, ms = client.request(tool, "GET", f"{BASE}/{path}", params={**params, "key": key})
    if resp.status_code == 400 and "API key" in resp.text:
        raise ToolError(ToolStatus.AUTH_REQUIRED, "API key rejected", 400)
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    return json_or_error(resp, tool), ms


def search(client: ApiClient, query: str | None = None, *, language: str | None = None,
           publisher_site: str | None = None, max_age_days: int | None = None, page_size: int = 10,
           page_token: str | None = None) -> dict:
    if not query and not publisher_site:
        raise ValueError("query is required unless publisher_site is set (per the API docs)")
    params = {"pageSize": page_size}
    for k, v in (("query", query), ("languageCode", language), ("reviewPublisherSiteFilter", publisher_site),
                 ("maxAgeDays", max_age_days), ("pageToken", page_token)):
        if v:
            params[k] = v
    data, ms = _get(client, "factcheck_search", "claims:search", params)
    reviews = [r for c in data.get("claims", []) for r in _flatten(c)]
    return {"reviews": reviews, "next_page_token": data.get("nextPageToken"), "ms": ms,
            "fields": sorted(data.keys())}


def image_search(client: ApiClient, public_image_url: str, language: str | None = None) -> dict:
    params = {"imageUri": public_image_url}
    if language:
        params["languageCode"] = language
    data, ms = _get(client, "factcheck_image_search", "claims:imageSearch", params)
    reviews = [r for res in data.get("results", []) for r in _flatten(res.get("claim", {}))]
    return {"reviews": reviews, "ms": ms, "fields": sorted(data.keys())}
