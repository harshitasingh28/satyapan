"""Embed the trusted corpus (PIB releases and known debunks) once, so requests do not have to.

Vectors are cached in the store (MongoDB embedding_cache, or data/embeddings.jsonl) keyed by
model and text. Only public corpus texts are embedded here, never user submissions.
Usage: python scripts/embed_corpus.py            (needs HF_TOKEN and HF_EMBEDDING_MODEL)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.errors import ToolError  # noqa: E402
from satyapan.hf import Embedder  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.storage import open_store  # noqa: E402


def main() -> None:
    s = get_settings()
    if not s.embeddings_configured:
        raise SystemExit("HF_TOKEN and HF_EMBEDDING_MODEL must be set in .env")
    store = open_store()
    cache = store.load_vectors(s.hf_embedding_model)
    emb = Embedder(ApiClient(s), cache=cache, persist=store.save_vectors)
    texts = [f"{d['title']} {d.get('summary', '')}" for d in store.pib_store().load()]
    texts += [k["text"] for k in store.known_claims()]
    before = len(cache)
    start = time.perf_counter()
    try:
        mat = emb.embed(texts, "passage")
    except ToolError as err:
        raise SystemExit(f"embedding failed: {err.status.value} {err.message[:200]}")
    print(f"{len(texts)} corpus texts, {len(cache) - before} newly embedded in {emb.calls} call(s), "
          f"{time.perf_counter() - start:.1f} s, dimensions {mat.shape[1] if len(texts) else '-'}, store {store.kind}")


if __name__ == "__main__":
    main()
