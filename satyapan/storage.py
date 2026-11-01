"""Investigation storage: one interface, two backends.

JsonStore (``Store``)  files under SATYAPAN_DATA_DIR. Used for local runs, tests and as the
                       fallback when MongoDB is unreachable.
MongoStore             MongoDB Atlas (satyapan/db/mongo.py), used when MONGODB_URI is set.

Privacy and retention
  * Uploaded files are deleted as soon as an investigation finishes. Only hashes and match
    results are kept.
  * Investigation records contain the user's text, so they expire after SATYAPAN_RETENTION_HOURS
    (default 168 h = 7 days). JSON: a sweep at start-up and every 10 minutes. MongoDB: TTL indexes.
  * Every record is private to the browser that created it. The API returns a random access
    token once. Only its SHA-256 hash is stored, and lookups compare hashes in constant time.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from satyapan.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_ok(token: str | None, stored_hash: str | None) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(token_hash(token), stored_hash)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def public_record(rec: dict) -> dict:
    """What the API may return: never the token hash."""
    return {k: v for k, v in rec.items() if k not in ("access_token_hash", "_id")}


class Store:
    """JSON-file store (the original spike store, extended)."""

    kind = "json"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().data_dir
        for sub in ("investigations", "uploads", "events"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.note = ""

    # -- files ------------------------------------------------------------------------------
    def upload_dir(self, investigation_id: str) -> Path:
        d = self.root / "uploads" / investigation_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def discard_files(self, investigation_id: str) -> None:
        """Delete an investigation's uploads and working files once it has finished."""
        for base in (self.root / "uploads", self.root / "work"):
            shutil.rmtree(base / investigation_id, ignore_errors=True)

    # -- records ----------------------------------------------------------------------------
    def _path(self, investigation_id: str) -> Path:
        return self.root / "investigations" / f"{investigation_id}.json"

    def create(self, investigation_id: str, token: str, meta: dict | None = None) -> dict:
        now = utcnow()
        rec = {"id": investigation_id, "status": "queued", "created_at": iso(now),
               "expires_at": iso(now + timedelta(hours=get_settings().retention_hours)),
               "access_token_hash": token_hash(token), **(meta or {})}
        self._write(investigation_id, rec)
        return rec

    def _write(self, investigation_id: str, rec: dict) -> None:
        path = self._path(investigation_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(path)       # a poller never reads a half-written record

    def save(self, investigation_id: str, payload: dict) -> None:
        """Merge fields into the record (creating it if needed)."""
        rec = self.load(investigation_id) or {"id": investigation_id}
        rec.update(payload)
        self._write(investigation_id, rec)

    def load(self, investigation_id: str) -> dict | None:
        if not investigation_id.isalnum():
            return None
        path = self._path(investigation_id)
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except ValueError:
            return None

    def get_authorized(self, investigation_id: str, token: str | None) -> dict | None:
        rec = self.load(investigation_id)
        if rec is None or not token_ok(token, rec.get("access_token_hash")):
            return None
        return public_record(rec)

    def save_detail(self, investigation_id: str, report: dict) -> None:
        """MongoDB splits a report into collections. The JSON store keeps it inside the record."""

    # -- workflow events --------------------------------------------------------------------
    def add_event(self, investigation_id: str, event: dict) -> None:
        if not investigation_id.isalnum():
            return
        with (self.root / "events" / f"{investigation_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def events(self, investigation_id: str) -> list[dict]:
        if not investigation_id.isalnum():
            return []
        path = self.root / "events" / f"{investigation_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # -- retention --------------------------------------------------------------------------
    def sweep(self, retention_hours: int | None = None) -> int:
        """Delete uploads, working files, events AND investigation records older than the window.

        Investigation records contain the user's text, so they expire too. The API runs
        this at start-up and at most every 10 minutes while handling requests.
        """
        hours = retention_hours if retention_hours is not None else get_settings().retention_hours
        cutoff = time.time() - hours * 3600
        removed = 0
        for base in (self.root / "uploads", self.root / "work", self.root / "investigations", self.root / "events"):
            if not base.exists():
                continue
            for d in base.iterdir():
                try:
                    old = d.stat().st_mtime < cutoff
                except FileNotFoundError:
                    continue
                if old:
                    shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
                    removed += 1
        return removed

    # -- trusted corpus (PIB releases, known debunks) ---------------------------------------
    def pib_store(self):
        from satyapan.sources.pib import PibStore
        return PibStore(self.root / "pib_releases.jsonl")

    def known_claims(self) -> list[dict]:
        path = self.root / "known_claims.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def ping(self) -> bool:
        return self.root.exists()

    # -- embedding cache (public corpus and fact-check texts only, never user text) -----------
    def _vec_path(self) -> Path:
        return self.root / "embeddings.jsonl"

    def load_vectors(self, model: str) -> dict:
        import base64

        import numpy as np
        out = {}
        path = self._vec_path()
        if not path.exists():
            return out
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("m") == model:
                out[row["k"]] = np.frombuffer(base64.b64decode(row["v"]), dtype=np.float32).copy()
        return out

    def save_vectors(self, vectors: dict) -> None:
        import base64

        import numpy as np
        model = get_settings().hf_embedding_model
        with self._vec_path().open("a", encoding="utf-8") as fh:
            for k, v in vectors.items():
                fh.write(json.dumps({"m": model, "k": k, "v": base64.b64encode(
                    np.asarray(v, dtype=np.float32).tobytes()).decode()}) + "\n")


JsonStore = Store


def open_store() -> Store:
    """MongoDB when configured and reachable, otherwise the JSON store (with a note saying why)."""
    s = get_settings()
    if s.store == "mongo" and s.mongodb_uri:
        try:
            from satyapan.db.mongo import MongoStore
            store = MongoStore.connect(s.mongodb_uri, s.mongodb_db)
            return store
        except Exception as exc:  # noqa: BLE001  the API must still answer if the database is down
            from satyapan.logging_setup import redact
            fallback = Store()
            fallback.note = f"MongoDB unavailable ({type(exc).__name__}: {redact(str(exc))[:120]}), using local JSON store"
            return fallback
    return Store()
