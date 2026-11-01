"""Multilingual embeddings from HOSTED inference: Cloudflare Workers AI (@cf/baai/bge-m3, free plan, default),
Hugging Face feature extraction, or any OpenAI-compatible /embeddings endpoint. No local models.

Routes (the same ones huggingface_hub uses, called through Satyapan's ApiClient so every call is
on the host allowlist, timed, redacted and recorded):
  hf-inference  POST {router}/hf-inference/models/{model}/pipeline/feature-extraction  {"inputs": [...]}
  deepinfra     POST {router}/deepinfra/v1/openai/embeddings  {"input": [...], "model": model}

Default model: intfloat/multilingual-e5-large-instruct (1024 dimensions, 512 tokens). Its queries
need an instruction prefix and its documents do not. intfloat/multilingual-e5-large uses
"query: " and "passage: " prefixes instead. Vectors from different models are never compared:
every cached vector is keyed by model name.

Embedding similarity is only ever used to FIND candidates. It never decides a verdict.
"""
from __future__ import annotations

import hashlib
import threading

import numpy as np

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error

QUERY_TASK = ("Given a claim from a forwarded message, retrieve official announcements and fact-checks "
              "about the same claim")
MAX_CHARS = 1500          # about 512 tokens for Indic scripts, the model's limit
BATCH = 16


def prepare(model: str, text: str, kind: str) -> str:
    text = " ".join((text or "").split())[:MAX_CHARS]
    name = model.lower()
    if "e5" in name and "instruct" in name:
        return f"Instruct: {QUERY_TASK}\nQuery: {text}" if kind == "query" else text
    if "e5" in name:
        return f"{'query' if kind == 'query' else 'passage'}: {text}"
    return text


def cache_key(model: str, kind: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{kind}\x00{text}".encode()).hexdigest()


def _as_matrix(raw, n: int) -> np.ndarray:
    arr = np.asarray(raw, dtype=np.float32)
    if arr.ndim == 1 and n == 1:
        arr = arr[None, :]
    if arr.ndim == 3:                      # token embeddings: mean-pool
        arr = arr.mean(axis=1)
    if arr.ndim != 2 or arr.shape[0] != n or arr.shape[1] < 8:
        raise ToolError(ToolStatus.SERVICE_ERROR, f"unexpected embedding shape {getattr(arr, 'shape', None)}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def _call(client: ApiClient, provider: str, model: str, batch: list[str]) -> np.ndarray:
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.hf_token}"}
    if provider == "hf-inference":
        url = f"{s.hf_router_url}/hf-inference/models/{model}/pipeline/feature-extraction"
        resp, _ = client.request("hf_embeddings", "POST", url, json={"inputs": batch, "normalize": True,
                                                                     "truncate": True}, headers=headers)
        if resp.status_code != 200:
            raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
        return _as_matrix(json_or_error(resp, "hf_embeddings"), len(batch))
    if provider == "deepinfra":
        url = f"{s.hf_router_url}/deepinfra/v1/openai/embeddings"
        resp, _ = client.request("hf_embeddings", "POST", url, json={"input": batch, "model": model,
                                                                     "encoding_format": "float"}, headers=headers)
        if resp.status_code != 200:
            raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
        data = json_or_error(resp, "hf_embeddings")
        try:
            rows = [item["embedding"] for item in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except (KeyError, TypeError) as exc:
            raise ToolError(ToolStatus.SERVICE_ERROR, "embedding response missing data") from exc
        return _as_matrix(rows, len(batch))
    if provider == "cloudflare":         # Workers AI native endpoint, e.g. @cf/baai/bge-m3
        from satyapan import cloudflare
        return cloudflare.embed(client, s.embedding_base_url, s.embedding_api_key, model, batch)
    if provider == "openai":             # any OpenAI-compatible /embeddings endpoint
        hdrs = {"Authorization": f"Bearer {s.embedding_api_key}"} if s.embedding_api_key else {}
        resp, _ = client.request("hf_embeddings", "POST", f"{s.embedding_base_url}/embeddings",
                                 json={"input": batch, "model": model}, headers=hdrs)
        if resp.status_code != 200:
            raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
        data = json_or_error(resp, "hf_embeddings")
        try:
            rows = [item["embedding"] for item in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except (KeyError, TypeError) as exc:
            raise ToolError(ToolStatus.SERVICE_ERROR, "embedding response missing data") from exc
        return _as_matrix(rows, len(batch))
    raise ToolError(ToolStatus.NOT_TESTED, f"embedding provider {provider!r} is not supported")


class Embedder:
    """Embeds texts with a cache. The cache can be backed by the investigation store (vectors are
    kept with the source documents), so the corpus is embedded once, not on every request."""

    def __init__(self, client: ApiClient, cache: dict[str, np.ndarray] | None = None, persist=None) -> None:
        s = get_settings()
        self.client = client
        self.model = s.hf_embedding_model
        self.providers = [p for p in (s.hf_embedding_provider, s.hf_embedding_fallback_provider) if p]
        self.cache = cache if cache is not None else {}
        self.persist = persist           # callable(dict[key, vector]) or None
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return get_settings().embeddings_configured

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        if not self.configured:
            raise ToolError(ToolStatus.NOT_TESTED, "embedding model not configured (EMBEDDING_* or HF_*)")
        prepared = [prepare(self.model, t, kind) for t in texts]
        keys = [cache_key(self.model, kind, p) for p in prepared]
        missing = [i for i, k in enumerate(keys) if k not in self.cache]
        new: dict[str, np.ndarray] = {}
        for start in range(0, len(missing), BATCH):
            idx = missing[start:start + BATCH]
            batch = [prepared[i] for i in idx]
            last: ToolError | None = None
            for provider in self.providers:
                try:
                    mat = _call(self.client, provider, self.model, batch)
                    break
                except ToolError as err:
                    last = err
            else:
                raise last or ToolError(ToolStatus.NOT_TESTED, "no embedding provider configured")
            self.calls += 1
            for i, vec in zip(idx, mat):
                new[keys[i]] = vec
        if new:
            with self._lock:
                self.cache.update(new)
            if self.persist and kind == "passage":     # user-text query vectors are never stored
                try:
                    self.persist(new)
                except Exception:  # noqa: BLE001  a cache write failure must not fail the investigation
                    pass
        dims = {self.cache[k].shape[0] for k in keys}
        if len(dims) > 1:
            raise ToolError(ToolStatus.SERVICE_ERROR, "embedding dimensions differ, refusing to compare")
        return np.stack([self.cache[k] for k in keys]) if keys else np.zeros((0, 1), dtype=np.float32)


def cosine_top(query: np.ndarray, matrix: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Indices and cosine scores of the k most similar rows (vectors are already normalised)."""
    if matrix.size == 0:
        return []
    scores = matrix @ query
    order = np.argsort(-scores)[:k]
    return [(int(i), round(float(scores[i]), 4)) for i in order]
