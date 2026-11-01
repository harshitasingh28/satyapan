"""Shared fixtures. Local tests never need the network or API keys.

Media comes from scripts/fetch_test_media.py (public test files, not evaluation data).
Tests that need missing media are SKIPPED with a reason, never silently passed.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "tests" / "media"
_tmp = tempfile.mkdtemp(prefix="satyapan_test_")
os.environ["SATYAPAN_DATA_DIR"] = _tmp
os.environ["SATYAPAN_RETRIES"] = "0"
for key in ("GOOGLE_API_KEY", "GOOGLE_VISION_API_KEY", "URLSCAN_API_KEY", "SIGHTENGINE_USER",
            "SIGHTENGINE_SECRET", "VIRUSTOTAL_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
            "HF_TOKEN", "HF_CHAT_MODEL", "HF_CHAT_FALLBACK_MODEL", "HF_EMBEDDING_MODEL", "MONGODB_URI",
            "SATYAPAN_STORE", "SATYAPAN_TRUSTED_PROXY_HOPS", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_CHAT_MODEL", "CLOUDFLARE_CHAT_FALLBACK_MODEL", "CLOUDFLARE_EMBEDDING_MODEL",
            "AI_CHAT_PROVIDER", "AI_EMBEDDING_PROVIDER", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY",
            "EMBEDDING_MODEL", "LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_MODEL"):
    os.environ[key] = ""          # keep unit tests offline and deterministic even if .env has keys
if (MEDIA / "tessdata" / "eng.traineddata").exists():
    os.environ["TESSDATA_PREFIX"] = str(MEDIA / "tessdata")

import httpx  # noqa: E402
import pytest  # noqa: E402


def need(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"missing {path.relative_to(ROOT)}. Run: python scripts/fetch_test_media.py")
    return path


@pytest.fixture
def images() -> list[Path]:
    folder = need(MEDIA / "images")
    files = sorted(p for p in folder.iterdir() if p.suffix in (".png", ".jpg"))
    if len(files) < 10:
        pytest.skip("need >= 10 sample photos (scripts/fetch_test_media.py)")
    return files


@pytest.fixture
def offline_client():
    """An ApiClient whose network always fails, to test graceful degradation."""
    from satyapan.http import ApiClient

    def refuse(request: httpx.Request):
        raise httpx.ConnectError("offline test transport", request=request)

    client = ApiClient(transport=httpx.MockTransport(refuse))
    yield client
    client.close()


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path
