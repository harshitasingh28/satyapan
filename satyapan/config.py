"""Runtime configuration, read from environment variables (.env). No secrets in code."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
CF_ACCOUNT_RE = re.compile(r"[0-9a-f]{32}")
# Free-plan defaults (checked on Cloudflare's model catalog 1 Nov 2026, confirm with the live check):
# Qwen3 30B A3B is multilingual (the Qwen3 family lists Hindi and Telugu) and has the lowest neuron
# cost of the multilingual chat models. bge-m3 is a multilingual embedding model.
CF_DEFAULT_CHAT = "@cf/qwen/qwen3-30b-a3b-fp8"
CF_DEFAULT_CHAT_FALLBACK = "@cf/meta/llama-4-scout-17b-16e-instruct"
CF_DEFAULT_EMBEDDING = "@cf/baai/bge-m3"
load_dotenv(ROOT / ".env")


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool = False) -> bool:
    return _str(name, str(default)).lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    contact: str
    google_api_key: str
    google_vision_api_key: str
    vision_use_gcloud: bool
    google_cloud_project: str
    urlscan_api_key: str
    sightengine_user: str
    sightengine_secret: str
    virustotal_api_key: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    http_retries: int
    http_timeout_s: float
    retention_hours: int
    max_image_mb: int
    max_video_mb: int
    max_audio_mb: int
    max_media_seconds: int
    max_image_pixels: int
    ai_image_detector_calibrated: bool
    tesseract_langs: str
    rate_limit_per_minute: int
    max_concurrent_jobs: int
    # Satyapan 2.0: Hugging Face hosted inference (no local models), MongoDB, deployment
    hf_token: str = ""
    hf_router_url: str = "https://router.huggingface.co"
    hf_chat_model: str = ""
    hf_chat_fallback_model: str = ""
    hf_embedding_model: str = ""
    hf_embedding_provider: str = "hf-inference"
    hf_embedding_fallback_provider: str = ""
    daily_llm_calls: int = 600
    daily_embedding_calls: int = 3000
    mongodb_uri: str = ""
    mongodb_db: str = "satyapan"
    store: str = "json"
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    trusted_proxy_hops: int = 0
    max_text_chars: int = 5000
    llm_timeout_s: float = 45.0
    # Any OpenAI-compatible HOSTED provider (Gemini, Groq, Cloudflare...), for chat fallback and embeddings
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    chat_provider: str = ""
    cloudflare_account_id: str = ""
    cloudflare_note: str = ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @property
    def embeddings_configured(self) -> bool:
        if not self.hf_embedding_provider:
            return False
        if self.hf_embedding_provider in ("openai", "cloudflare"):
            return bool(self.embedding_base_url and self.hf_embedding_model)
        return bool(self.hf_token and self.hf_embedding_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(_str("SATYAPAN_DATA_DIR", str(ROOT / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    hf_token = _str("HF_TOKEN")
    hf_router = (_str("HF_ROUTER_URL") or "https://router.huggingface.co").rstrip("/")
    cf_account = _str("CLOUDFLARE_ACCOUNT_ID").lower()
    cf_token = _str("CLOUDFLARE_API_TOKEN")
    cf_ready = bool(CF_ACCOUNT_RE.fullmatch(cf_account) and cf_token)   # 32 hex characters, nothing else
    cf_base = f"{CLOUDFLARE_API}/accounts/{cf_account}/ai"

    # Chat and embeddings are configured INDEPENDENTLY. Explicit AI_*_PROVIDER wins. Otherwise:
    # Cloudflare if its account and token are set, then any OpenAI-compatible URL, then Hugging Face.
    def pick(explicit: str, openai_url: str) -> str:
        if explicit in ("cloudflare", "openai", "huggingface", "none"):
            return "" if explicit == "none" else explicit
        return "cloudflare" if cf_ready else "openai" if openai_url else "huggingface" if hf_token else ""
    chat_provider = pick(_str("AI_CHAT_PROVIDER").lower(), _str("LLM_BASE_URL"))
    emb_provider = pick(_str("AI_EMBEDDING_PROVIDER").lower(), _str("EMBEDDING_BASE_URL"))

    if chat_provider == "cloudflare":
        llm_base_url, llm_api_key = (f"{cf_base}/v1", cf_token) if cf_ready else ("", "")
        llm_model = (_str("CLOUDFLARE_CHAT_MODEL") or CF_DEFAULT_CHAT)
        fallback_model = (_str("CLOUDFLARE_CHAT_FALLBACK_MODEL") or CF_DEFAULT_CHAT_FALLBACK)
    elif chat_provider == "openai":
        llm_base_url, llm_api_key, llm_model = _str("LLM_BASE_URL").rstrip("/"), _str("LLM_API_KEY"), _str("LLM_MODEL")
        fallback_model = ""
    elif chat_provider == "huggingface":
        llm_base_url, llm_api_key = (f"{hf_router}/v1", hf_token) if hf_token else ("", "")
        llm_model, fallback_model = _str("HF_CHAT_MODEL"), _str("HF_CHAT_FALLBACK_MODEL")
    else:
        llm_base_url = llm_api_key = llm_model = fallback_model = ""
    # An explicit fallback on ANOTHER provider (for example a free Groq key) works with any primary.
    fallback_base = _str("LLM_FALLBACK_BASE_URL").rstrip("/") or llm_base_url
    fallback_key = _str("LLM_FALLBACK_API_KEY") or (llm_api_key if fallback_base == llm_base_url else "")
    fallback_model = _str("LLM_FALLBACK_MODEL") or fallback_model

    if emb_provider == "cloudflare":
        embedding_provider, embedding_base_url = "cloudflare", (cf_base if cf_ready else "")
        embedding_api_key = cf_token if cf_ready else ""
        embedding_model = (_str("CLOUDFLARE_EMBEDDING_MODEL") or CF_DEFAULT_EMBEDDING)
    elif emb_provider == "openai":
        embedding_provider, embedding_base_url = "openai", _str("EMBEDDING_BASE_URL").rstrip("/")
        embedding_api_key, embedding_model = _str("EMBEDDING_API_KEY"), _str("EMBEDDING_MODEL")
    elif emb_provider == "huggingface":
        embedding_provider, embedding_base_url = (_str("HF_EMBEDDING_PROVIDER") or "hf-inference"), ""
        embedding_api_key, embedding_model = "", _str("HF_EMBEDDING_MODEL")
    else:
        embedding_provider = embedding_base_url = embedding_api_key = embedding_model = ""
    mongodb_uri = _str("MONGODB_URI")
    store = _str("SATYAPAN_STORE", "mongo" if mongodb_uri else "json").lower()
    origins = tuple(o.strip().rstrip("/") for o in _str("SATYAPAN_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
                    if o.strip())
    return Settings(
        data_dir=data_dir,
        contact=_str("SATYAPAN_CONTACT", "unset"),
        google_api_key=_str("GOOGLE_API_KEY"),
        google_vision_api_key=_str("GOOGLE_VISION_API_KEY"),
        vision_use_gcloud=_bool("VISION_USE_GCLOUD"),
        google_cloud_project=_str("GOOGLE_CLOUD_PROJECT"),
        urlscan_api_key=_str("URLSCAN_API_KEY"),
        sightengine_user=_str("SIGHTENGINE_USER"),
        sightengine_secret=_str("SIGHTENGINE_SECRET"),
        virustotal_api_key=_str("VIRUSTOTAL_API_KEY"),
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        http_retries=_int("SATYAPAN_RETRIES", 1),
        http_timeout_s=float(_int("SATYAPAN_TIMEOUT_S", 15)),
        retention_hours=_int("SATYAPAN_RETENTION_HOURS", 168),
        max_image_mb=_int("SATYAPAN_MAX_IMAGE_MB", 10),
        max_video_mb=_int("SATYAPAN_MAX_VIDEO_MB", 50),
        max_audio_mb=_int("SATYAPAN_MAX_AUDIO_MB", 10),
        max_media_seconds=_int("SATYAPAN_MAX_MEDIA_SECONDS", 180),
        max_image_pixels=_int("SATYAPAN_MAX_IMAGE_PIXELS", 40_000_000),
        ai_image_detector_calibrated=_bool("AI_IMAGE_DETECTOR_CALIBRATED"),
        tesseract_langs=_str("TESSERACT_LANGS", "eng+hin+tel"),
        rate_limit_per_minute=_int("SATYAPAN_RATE_LIMIT_PER_MINUTE", 10),
        # Investigations are CPU-bound (OCR, ORB, FFmpeg). More parallel jobs than cores made
        # every job slower and pushed OCR past its timeout in the audit, so jobs are queued.
        max_concurrent_jobs=max(1, _int("SATYAPAN_MAX_CONCURRENT_JOBS", max(1, (os.cpu_count() or 2) // 2))),
        hf_token=hf_token,
        hf_router_url=hf_router,
        hf_chat_model=llm_model,
        hf_chat_fallback_model=fallback_model,
        hf_embedding_model=embedding_model,
        hf_embedding_provider=embedding_provider,
        hf_embedding_fallback_provider=_str("HF_EMBEDDING_FALLBACK_PROVIDER") if emb_provider == "huggingface" else "",
        daily_llm_calls=_int("SATYAPAN_DAILY_LLM_CALLS", 600),
        daily_embedding_calls=_int("SATYAPAN_DAILY_EMBEDDING_CALLS", 3000),
        mongodb_uri=mongodb_uri,
        mongodb_db=_str("MONGODB_DB", "satyapan"),
        store=store if store in ("json", "mongo") else "json",
        allowed_origins=origins,
        trusted_proxy_hops=max(0, _int("SATYAPAN_TRUSTED_PROXY_HOPS", 0)),
        max_text_chars=_int("SATYAPAN_MAX_TEXT_CHARS", 5000),
        llm_timeout_s=float(_int("SATYAPAN_LLM_TIMEOUT_S", 45)),
        llm_fallback_base_url=fallback_base,
        llm_fallback_api_key=fallback_key,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
        chat_provider=chat_provider,
        cloudflare_account_id=cf_account if cf_ready else "",
        cloudflare_note=("" if cf_ready or not (cf_account or cf_token) else
                         "CLOUDFLARE_ACCOUNT_ID must be the 32-character account ID and CLOUDFLARE_API_TOKEN must be set"),
    )
