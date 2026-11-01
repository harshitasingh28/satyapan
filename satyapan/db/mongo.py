"""MongoDB Atlas store.

Collections (investigation-scoped ones carry ``expires_at`` with a TTL index, expireAfterSeconds 0):
  investigations        one per submission: status, times, token hash, input summary (no file bytes)
  extracted_claims      one per claim found
  evidence              one per evidence item
  verification_results  verdict, statements and the full report
  workflow_events       the live trace, replayed when a page is reloaded
  media_analysis        hashes, credentials and match tiers per media item (never the pixels)
  source_documents      the trusted corpus: PIB releases and curated known debunks (no TTL)
  embedding_cache       vectors of PUBLIC texts (corpus, fact-check claims), keyed by model and text hash.
                        Vectors of user text are never stored.

Atlas M0 notes: 512 MB storage, 100 operations per second, 500 connections. One MongoClient per
process, small pool, writes batched per collection.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from satyapan.config import get_settings
from satyapan.sources.pib import PibStore
from satyapan.storage import Store, iso, public_record, token_hash, token_ok, utcnow

TTL_COLLECTIONS = ("investigations", "extracted_claims", "evidence", "verification_results",
                   "workflow_events", "media_analysis")


def _plain(value):
    """BSON dates back to ISO strings for JSON responses."""
    if isinstance(value, datetime):
        return iso(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def ensure_indexes(db) -> None:
    for name in TTL_COLLECTIONS:
        db[name].create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    db.investigations.create_index([("created_at", -1)], name="created_at_desc")
    for name in ("extracted_claims", "evidence", "media_analysis"):
        db[name].create_index("investigation_id", name="by_investigation")
    db.workflow_events.create_index([("investigation_id", 1), ("seq", 1)], unique=True, name="by_investigation_seq")
    db.source_documents.create_index([("kind", 1), ("prid", 1)], name="kind_prid")
    db.source_documents.create_index("url", unique=True, sparse=True, name="url_unique")


class MongoPibStore(PibStore):
    """PIB releases kept in source_documents (kind pib_release), searched in memory with BM25."""

    REFRESH_S = 300

    def __init__(self, db) -> None:
        super().__init__(path=None)            # type: ignore[arg-type]
        self.db = db
        self._docs: list[dict] | None = None
        self._loaded_at = 0.0

    def load(self) -> list[dict]:
        if self._docs is None or time.time() - self._loaded_at > self.REFRESH_S:
            rows = self.db.source_documents.find({"kind": "pib_release"}, {"_id": 0, "embedding": 0})
            self._docs = [{"title": r.get("title", ""), "link": r.get("url", ""), "summary": r.get("summary", ""),
                           "published": r.get("published_at"), "language": r.get("language"),
                           "feed": r.get("feed"), "prid": r.get("prid"), "fixture": r.get("fixture", False)}
                          for r in rows]
            self._loaded_at = time.time()
            self._index = None
        return self._docs

    def add(self, items: list[dict]) -> int:
        from satyapan.sources.pib import prid_of
        new = 0
        for i in items:
            if not i.get("link"):
                continue
            res = self.db.source_documents.update_one(
                {"url": i["link"]},
                {"$setOnInsert": {"kind": "pib_release", "url": i["link"], "title": i.get("title", ""),
                                  "summary": i.get("summary", ""), "published_at": i.get("published"),
                                  "date_source": i.get("date_source") or ("feed" if i.get("published") else None),
                                  "language": i.get("language"), "feed": i.get("feed"), "prid": prid_of(i["link"]),
                                  "first_seen_at": utcnow(), "added_by": i.get("added_by", "ingest_pib"),
                                  "licence_note": "PIB content, reproduced with attribution"}},
                upsert=True)
            new += bool(res.upserted_id)
        self._docs = None
        return new


    def set_published(self, prid: int, published: str, source: str = "page") -> bool:
        res = self.db.source_documents.update_many({"kind": "pib_release", "prid": prid},
                                                   {"$set": {"published_at": published, "date_source": source}})
        self._docs = None
        return res.matched_count > 0


class MongoStore(Store):
    kind = "mongo"

    def __init__(self, db, root=None) -> None:
        super().__init__(root)                  # local folders are still used for uploads and work files
        self.db = db
        self._pib: MongoPibStore | None = None

    @classmethod
    def connect(cls, uri: str, db_name: str) -> "MongoStore":
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, maxPoolSize=10,
                             tz_aware=True, appname="satyapan")
        client.admin.command("ping")
        db = client[db_name]
        ensure_indexes(db)
        return cls(db)

    def ping(self) -> bool:
        try:
            self.db.client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _expiry(self) -> datetime:
        return utcnow() + timedelta(hours=get_settings().retention_hours)

    def create(self, investigation_id: str, token: str, meta: dict | None = None) -> dict:
        now = utcnow()
        rec = {"_id": investigation_id, "id": investigation_id, "status": "queued", "created_at": now,
               "expires_at": self._expiry(), "access_token_hash": token_hash(token), **(meta or {})}
        self.db.investigations.insert_one(rec)
        return _plain(rec)

    def save(self, investigation_id: str, payload: dict) -> None:
        payload = dict(payload)
        report = payload.pop("report", None)
        payload["updated_at"] = utcnow()
        self.db.investigations.update_one({"_id": investigation_id}, {"$set": payload,
                                          "$setOnInsert": {"id": investigation_id, "created_at": utcnow(),
                                                           "expires_at": self._expiry()}}, upsert=True)
        if report is not None:
            self.save_detail(investigation_id, report)

    def load(self, investigation_id: str) -> dict | None:
        if not investigation_id.isalnum():
            return None
        rec = self.db.investigations.find_one({"_id": investigation_id})
        if rec is None:
            return None
        result = self.db.verification_results.find_one({"_id": investigation_id}, {"report": 1})
        out = _plain(rec)
        out["access_token_hash"] = rec.get("access_token_hash")
        if result and result.get("report"):
            out["report"] = _plain(result["report"])
        return out

    def get_authorized(self, investigation_id: str, token: str | None) -> dict | None:
        rec = self.load(investigation_id)
        if rec is None or not token_ok(token, rec.get("access_token_hash")):
            return None
        return public_record(rec)

    def save_detail(self, investigation_id: str, report: dict) -> None:
        exp = self._expiry()
        base = {"investigation_id": investigation_id, "expires_at": exp}
        self.db.verification_results.replace_one({"_id": investigation_id}, {
            "_id": investigation_id, **base, "verdict": report.get("verdict"),
            "reason_code": report.get("verdict_reason"), "evidence_strength": report.get("evidence_strength"),
            "statements": report.get("reason", []), "limitations": report.get("limitations", []),
            "created_at": utcnow(), "report": report}, upsert=True)
        for name, rows in (("extracted_claims", report.get("claims") or []),
                           ("evidence", report.get("evidence") or []),
                           ("media_analysis", [{"media_id": k, **v} for k, v in
                                               (report.get("media_assessment") or {}).items()])):
            self.db[name].delete_many({"investigation_id": investigation_id})
            if rows:
                self.db[name].insert_many([{**base, **row} for row in rows])
        self.db.investigations.update_one({"_id": investigation_id}, {"$set": {"verdict": report.get("verdict")}})

    def add_event(self, investigation_id: str, event: dict) -> None:
        self.db.workflow_events.insert_one({"investigation_id": investigation_id, "expires_at": self._expiry(),
                                            **event})

    def events(self, investigation_id: str) -> list[dict]:
        if not investigation_id.isalnum():
            return []
        rows = self.db.workflow_events.find({"investigation_id": investigation_id}).sort("seq", 1)
        return [{k: v for k, v in _plain(r).items() if k not in ("investigation_id", "expires_at")} for r in rows]

    def sweep(self, retention_hours: int | None = None) -> int:
        """MongoDB TTL indexes delete records. Only local upload and work folders are swept here."""
        hours = retention_hours if retention_hours is not None else get_settings().retention_hours
        cutoff = time.time() - min(hours, 24) * 3600
        removed = 0
        for base in (self.root / "uploads", self.root / "work"):
            if base.exists():
                for d in base.iterdir():
                    try:
                        if d.stat().st_mtime < cutoff:
                            import shutil
                            shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
                            removed += 1
                    except FileNotFoundError:
                        continue
        return removed

    def pib_store(self) -> MongoPibStore:
        if self._pib is None:
            self._pib = MongoPibStore(self.db)
        return self._pib

    def known_claims(self) -> list[dict]:
        rows = self.db.source_documents.find({"kind": "known_debunk"}, {"_id": 0, "embedding": 0})
        return [{"text": r.get("title", ""), "url": r.get("url"), "publisher": r.get("publisher"),
                 "date": r.get("published_at"), "language": r.get("language")} for r in rows]

    def load_vectors(self, model: str) -> dict:
        import numpy as np
        return {r["_id"]: np.frombuffer(bytes(r["v"]), dtype=np.float32).copy()
                for r in self.db.embedding_cache.find({"model": model})}

    def save_vectors(self, vectors: dict) -> None:
        import numpy as np
        from bson.binary import Binary
        from pymongo import UpdateOne
        model = get_settings().hf_embedding_model
        ops = [UpdateOne({"_id": k}, {"$set": {"model": model, "v": Binary(np.asarray(v, dtype=np.float32).tobytes()),
                                              "created_at": utcnow()}}, upsert=True) for k, v in vectors.items()]
        if not ops:
            return
        try:
            self.db.embedding_cache.bulk_write(ops, ordered=False)
        except TypeError:          # mongomock (tests) does not support every bulk option of pymongo 4.x
            for k, v in vectors.items():
                self.db.embedding_cache.update_one({"_id": k}, {"$set": {
                    "model": model, "v": Binary(np.asarray(v, dtype=np.float32).tobytes()), "created_at": utcnow()}},
                    upsert=True)

    def add_known_claims(self, rows: list[dict]) -> int:
        new = 0
        for r in rows:
            if not r.get("url") or not r.get("text"):
                continue
            res = self.db.source_documents.update_one(
                {"url": r["url"]}, {"$setOnInsert": {"kind": "known_debunk", "url": r["url"], "title": r["text"],
                                                     "publisher": r.get("publisher"), "published_at": r.get("date"),
                                                     "language": r.get("language"), "rating": r.get("rating"),
                                                     "added_by": r.get("added_by", "import"), "added_at": utcnow()}},
                upsert=True)
            new += bool(res.upserted_id)
        return new
