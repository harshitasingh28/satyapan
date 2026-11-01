"""Satyapan 2.0 API and storage: streaming events, private records, downloads, MongoDB layout.

MongoDB is replaced by mongomock here (in-memory, offline). It checks the document layout and
indexes, not Atlas itself. A live Atlas check is integration/run_all.py --only mongodb.
"""
from __future__ import annotations

import dataclasses
import json

import mongomock
import numpy as np
import pytest
from fastapi.testclient import TestClient

import satyapan.api.app as api
from satyapan.config import get_settings

client = TestClient(api.app)


def parse_sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if not lines:
            continue
        event = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads("".join(ln[6:] for ln in lines if ln.startswith("data: ")))
        out.append((event, data))
    return out


def stream(text: str):
    api.bucket._state.clear()
    r = client.post("/v1/investigations/stream", data={"text": text})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


def test_stream_sends_created_then_real_steps_then_done():
    events = stream("PM Kisan Yojana gives Rs 10,000 to every farmer. Apply at http://pmkisan-gov.top/x")
    names = [e for e, _ in events]
    assert names[0] == "created" and names[-1] == "done"
    steps = [d for e, d in events if e == "step"]
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    started = [s["node"] for s in steps if s["phase"] == "start"]
    ended = [s["node"] for s in steps if s["phase"] == "end"]
    assert started == ended and "decide" in ended and "compare_evidence" in ended
    report = events[-1][1]["report"]
    assert report["verdict"] in ("FAKE", "UNVERIFIED")
    assert [t["node"] for t in report["trace"]] == ended          # the stream shows exactly what ran
    created = events[0][1]
    assert created["access_token"] and created["id"] == report["investigation_id"]


def test_records_are_private_to_the_token():
    events = stream("Government announces free laptops for students. Register at http://free-laptop-gov.top")
    created = events[0][1]
    inv, token = created["id"], created["access_token"]
    assert client.get(f"/v1/investigations/{inv}").status_code == 404
    assert client.get(f"/v1/investigations/{inv}", headers={"X-Access-Token": "wrong" * 8}).status_code == 404
    ok = client.get(f"/v1/investigations/{inv}", headers={"X-Access-Token": token})
    assert ok.status_code == 200 and ok.json()["status"] == "done" and "access_token_hash" not in ok.json()
    raw = (get_settings().data_dir / "investigations" / f"{inv}.json").read_text()
    assert token not in raw                                       # only the hash is stored
    ev = client.get(f"/v1/investigations/{inv}/events", headers={"X-Access-Token": token}).json()["events"]
    assert len(ev) == len([1 for e, _ in events if e == "step"])


def test_report_downloads():
    events = stream("Free gas cylinder for all families from today. Click http://ujjwala-free.top")
    inv, token = events[0][1]["id"], events[0][1]["access_token"]
    md = client.get(f"/v1/investigations/{inv}/report.md?token={token}")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert "# Satyapan verification report" in md.text and events[-1][1]["report"]["verdict"] in md.text
    js = client.get(f"/v1/investigations/{inv}/report.json", headers={"X-Access-Token": token})
    assert js.json()["investigation_id"] == inv
    assert client.get(f"/v1/investigations/{inv}/report.md").status_code == 404


def test_markdown_report_neutralises_markup():
    from satyapan.pipeline.report import markdown_report
    md = markdown_report({"investigation_id": "x", "verdict": "UNVERIFIED",
                          "claim": {"text": "<img src=x onerror=alert(1)> [click](http://evil.top)"}})
    import re
    assert not re.search(r"(?<!\\)<img", md) and not re.search(r"(?<!\\)\]\(http", md)   # only escaped forms remain
    assert "\\<img" in md


def test_status_reports_configuration_without_secrets():
    data = client.get("/v1/status").json()
    assert set(data["integrations"]) >= {"factcheck", "safe_browsing", "ai_chat", "ai_embeddings", "mongodb"}
    assert all(isinstance(v, bool) for v in data["integrations"].values())
    assert set(data["providers"]) == {"chat", "chat_fallback", "embedding"}
    assert "key" not in json.dumps(data).lower().replace("known", "")


def test_client_ip_ignores_spoofed_forwarded_for(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, trusted_proxy_hops=1))
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")], "client": ("10.0.0.1", 1)}
    assert api.client_ip(Request(scope)) == "203.0.113.9"
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, trusted_proxy_hops=0))
    assert api.client_ip(Request(scope)) == "10.0.0.1"


def test_cors_allows_only_configured_origins():
    ok = client.options("/v1/status", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    bad = client.options("/v1/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


# ---------------------------------------------------------------- MongoDB layout (mongomock)

@pytest.fixture
def mstore(tmp_path):
    from satyapan.db.mongo import MongoStore, ensure_indexes
    db = mongomock.MongoClient(tz_aware=True).satyapan_test
    ensure_indexes(db)
    return MongoStore(db, root=tmp_path)


def test_mongo_ttl_indexes_on_every_investigation_collection(mstore):
    from satyapan.db.mongo import TTL_COLLECTIONS
    for name in TTL_COLLECTIONS:
        info = mstore.db[name].index_information()
        ttl = [v for v in info.values() if v.get("expireAfterSeconds") == 0]
        assert ttl and ttl[0]["key"] == [("expires_at", 1)], name


def test_mongo_record_lifecycle_and_split_collections(mstore):
    rec = mstore.create("abc123", "tok-" + "x" * 30, {"input": {"text_chars": 10}})
    assert rec["status"] == "queued"
    raw = mstore.db.investigations.find_one({"_id": "abc123"})
    assert raw["access_token_hash"] != "tok-" + "x" * 30 and raw["expires_at"] > raw["created_at"]
    report = {"investigation_id": "abc123", "verdict": "UNVERIFIED", "verdict_reason": "insufficient",
              "claims": [{"id": "C1", "text": "t"}], "evidence": [{"id": "E1", "tool": "rdap"}],
              "media_assessment": {"M1": {"kind": "image", "tier": "unknown_provenance"}}, "reason": []}
    mstore.save("abc123", {"status": "done", "report": report})
    for name in ("extracted_claims", "evidence", "media_analysis"):
        docs = list(mstore.db[name].find({"investigation_id": "abc123"}))
        assert len(docs) == 1 and docs[0]["expires_at"]
    assert mstore.get_authorized("abc123", "nope") is None
    got = mstore.get_authorized("abc123", "tok-" + "x" * 30)
    assert got["status"] == "done" and got["report"]["verdict"] == "UNVERIFIED" and "access_token_hash" not in got
    mstore.add_event("abc123", {"seq": 1, "node": "decide", "phase": "start"})
    assert mstore.events("abc123")[0]["node"] == "decide"


def test_mongo_corpus_and_vector_cache(mstore, monkeypatch):
    pib = mstore.pib_store()
    n = pib.add([{"title": "Cabinet approves new national highway projects in four states",
                  "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100077", "fixture": True}])
    assert n == 1 and pib.add([{"title": "dup", "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100077"}]) == 0
    assert pib.by_prid(2100077)["title"].startswith("Cabinet")
    assert pib.search("national highway projects", 1)[0]["doc"]["link"].endswith("2100077")
    s = dataclasses.replace(get_settings(), hf_embedding_model="m1")
    import satyapan.db.mongo as mongo_mod
    monkeypatch.setattr(mongo_mod, "get_settings", lambda: s)
    mstore.save_vectors({"k1": np.array([0.6, 0.8], dtype=np.float32)})
    assert np.allclose(mstore.load_vectors("m1")["k1"], [0.6, 0.8]) and mstore.load_vectors("m2") == {}
