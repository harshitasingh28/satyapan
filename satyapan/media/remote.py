"""Third-party media services. All of them need explicit user consent.

Cloud Vision Web Detection (billing required, 1,000 free units/month):
  https://docs.cloud.google.com/vision/docs/detecting-web
Sightengine genai (free plan 2,000 operations/month, max 500/day):
  https://sightengine.com/docs/ai-generated-image-detection
Images are re-encoded (metadata stripped) before upload. See security/uploads.py.
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
SIGHTENGINE_URL = "https://api.sightengine.com/1.0/check.json"


def vision_configured(s=None) -> bool:
    s = s or get_settings()
    return bool(s.google_vision_api_key or (s.vision_use_gcloud and s.google_cloud_project))


def sightengine_configured(s=None) -> bool:
    s = s or get_settings()
    return bool(s.sightengine_user and s.sightengine_secret)


def _vision_auth() -> tuple[dict, dict]:
    s = get_settings()
    if s.google_vision_api_key:
        return {"key": s.google_vision_api_key}, {}
    if s.vision_use_gcloud and s.google_cloud_project:
        out = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=False)
        if out.returncode == 0:
            return {}, {"Authorization": f"Bearer {out.stdout.strip()}", "x-goog-user-project": s.google_cloud_project}
    raise ToolError(ToolStatus.AUTH_REQUIRED, "Cloud Vision credentials not configured (billing required)")


def web_detection(client: ApiClient, clean_jpeg: Path, max_results: int = 10) -> dict:
    params, headers = _vision_auth()
    body = {"requests": [{"image": {"content": base64.b64encode(clean_jpeg.read_bytes()).decode()},
                          "features": [{"type": "WEB_DETECTION", "maxResults": max_results}]}]}
    resp, ms = client.request("cloud_vision_web", "POST", VISION_URL, params=params, headers=headers, json=body)
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    first = (json_or_error(resp, "cloud_vision_web").get("responses") or [{}])[0]
    if "error" in first:
        raise ToolError(ToolStatus.SERVICE_ERROR, str(first["error"])[:200])
    web = first.get("webDetection", {})
    return {"pages": [{"url": p.get("url"), "title": p.get("pageTitle")} for p in web.get("pagesWithMatchingImages", [])],
            "full_matches": [i.get("url") for i in web.get("fullMatchingImages", [])],
            "partial_matches": [i.get("url") for i in web.get("partialMatchingImages", [])],
            "best_guess": [b.get("label") for b in web.get("bestGuessLabels", [])], "ms": ms}


def sightengine_genai(client: ApiClient, clean_jpeg: Path) -> dict:
    s = get_settings()
    if not (s.sightengine_user and s.sightengine_secret):
        raise ToolError(ToolStatus.AUTH_REQUIRED, "SIGHTENGINE_USER / SIGHTENGINE_SECRET not configured")
    resp, ms = client.request("sightengine_genai", "POST", SIGHTENGINE_URL,
                              data={"models": "genai", "api_user": s.sightengine_user, "api_secret": s.sightengine_secret},
                              files={"media": (clean_jpeg.name, clean_jpeg.read_bytes())})
    body = json_or_error(resp, "sightengine_genai")
    if body.get("status") != "success":
        err = body.get("error", {})
        msg = f"{err.get('type')}: {err.get('message')}"
        status = ToolStatus.RATE_LIMITED if "limit" in msg.lower() else ToolStatus.SERVICE_ERROR
        raise ToolError(status, msg, resp.status_code)
    return {"score": body.get("type", {}).get("ai_generated"),
            "operations": body.get("request", {}).get("operations"), "ms": ms}
