"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import os
import re

_PATTERNS = [
    (re.compile(r"([?&](?:key|api_secret|api_key|token|access_token)=)[^&\s\"']+", re.I), r"\1REDACTED"),
    (re.compile(r"((?:API-Key|x-apikey|Authorization)[\"']?\s*[:=]\s*[\"']?)(Bearer\s+)?[^\s\"',}]+", re.I),
     r"\1REDACTED"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "hf_REDACTED"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "AIza_REDACTED"),          # Google keys (Gemini, Fact Check)
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "gsk_REDACTED"),             # Groq keys
    (re.compile(r"(mongodb(?:\+srv)?://)[^@\s/]+@", re.I), r"\1REDACTED@"),
]


SECRET_ENV = ("GOOGLE_API_KEY", "GOOGLE_VISION_API_KEY", "URLSCAN_API_KEY", "SIGHTENGINE_USER",
              "SIGHTENGINE_SECRET", "VIRUSTOTAL_API_KEY", "LLM_API_KEY", "HF_TOKEN", "MONGODB_URI",
              "LLM_FALLBACK_API_KEY", "EMBEDDING_API_KEY", "CLOUDFLARE_API_TOKEN")


def redact(text: str) -> str:
    """Remove secrets: key-like URL parameters and headers, plus the literal value of every
    configured secret (a service may echo a key back in an error body, in any format)."""
    text = str(text)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    for name in SECRET_ENV:
        value = os.environ.get(name, "").strip()
        if len(value) >= 6:
            text = text.replace(value, "REDACTED")
    return text


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                   "logger": record.name, "msg": redact(record.getMessage())}
        extra = getattr(record, "fields", None)
        if extra:
            payload["fields"] = json.loads(redact(json.dumps(extra, default=str)))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log(logger: logging.Logger, msg: str, **fields) -> None:
    logger.info(msg, extra={"fields": fields})
