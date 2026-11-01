"""Live integration tests. Every result is what the external service actually returned.

Statuses
  LIVE_SUCCESS   a real response came back from the service with the documented fields
  AUTH_REQUIRED  no key configured (request NOT sent), or the service rejected the key
  RATE_LIMITED   HTTP 429
  BLOCKED        the network, a proxy, or our own allowlist stopped the request
  SERVICE_ERROR  5xx, timeout, or a response without the documented fields
  NOT_TESTED     deliberately not run (third-party upload without --allow-third-party, no billing, optional)

Usage (from the project root, with .env filled in):
  python -m integration.run_all                         keyless + key-based reads only
  python -m integration.run_all --allow-third-party     also sends PUBLIC test media/URLs to
                                                        urlscan, Sightengine, Cloud Vision, the LLM
Writes integration_results/<test>.json and integration_results/SUMMARY.md
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # also works as: python integration/run_all.py

from satyapan.config import get_settings  # noqa: E402
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.links import rdap, safebrowsing, urlscan
from satyapan.llm import llm_extract_claims
from satyapan.logging_setup import redact
from satyapan.media import remote
from satyapan.security.uploads import sanitized_image_copy
from satyapan.sources import factcheck, pib
from satyapan.sources.official import wikidata_official_sites

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "integration_results"
PUBLIC_IMAGE = ROOT / "tests" / "media" / "images" / "astronaut.png"     # NASA photo via scikit-image
PUBLIC_IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg"
SAFE_BROWSING_CONTROL = "http://testsafebrowsing.appspot.com/s/phishing.html"


def _fields(obj, depth=0):
    if isinstance(obj, dict):
        return sorted(obj.keys()) if depth else sorted(obj.keys())
    if isinstance(obj, (list, tuple)) and obj:
        return _fields(obj[0], depth + 1)
    return []


TESTS = []


def case(name: str, needs: str | None = None, third_party: bool = False):
    def wrap(fn):
        TESTS.append((name, needs, third_party, fn))
        return fn
    return wrap


@case("factcheck_search", needs="google_api_key")
def t_factcheck(client):
    res = factcheck.search(client, "free laptop scheme government students", page_size=5)
    return {"reviews": len(res["reviews"]), "fields": res["fields"],
            "sample": res["reviews"][0] if res["reviews"] else None}


@case("factcheck_image_search", needs="google_api_key")
def t_factcheck_image(client):
    res = factcheck.image_search(client, PUBLIC_IMAGE_URL)
    return {"reviews": len(res["reviews"]), "fields": res["fields"]}


@case("safe_browsing_v5", needs="google_api_key")
def t_sb5(client):
    hits, ms = safebrowsing.lookup_v5(client, [SAFE_BROWSING_CONTROL, "https://www.india.gov.in/"])
    return {"hits": hits, "control_flagged": SAFE_BROWSING_CONTROL in hits, "official_flagged": "https://www.india.gov.in/" in hits}


@case("safe_browsing_v4", needs="google_api_key")
def t_sb4(client):
    hits, ms = safebrowsing.lookup_v4(client, [SAFE_BROWSING_CONTROL, "https://www.india.gov.in/"])
    return {"hits": hits, "control_flagged": SAFE_BROWSING_CONTROL in hits}


@case("rdap_bootstrap")
def t_rdap_boot(client):
    server = rdap.server_for(client, "in")
    return {"in_server": server, "co_server": rdap.server_for(client, "co")}


@case("rdap_domain")
def t_rdap(client):
    return {d: rdap.lookup(client, d) for d in ("uidai.gov.in", "google.co.in", "example.com")}


@case("wikidata_sparql")
def t_wikidata(client):
    return wikidata_official_sites(client, "Unique Identification Authority of India")


@case("pib_rss")
def t_pib(client):
    out = {}
    for name in pib.FEEDS:
        try:
            items, ms = pib.fetch_feed(client, name)
            titles = " ".join(i["title"] for i in items)
            out[name] = {"items": len(items), "devanagari_share": round(pib.devanagari_share(titles), 2),
                         "has_dates": any(i["published"] for i in items), "ms": ms,
                         "sample_titles": [i["title"][:90] for i in items[:2]]}
        except ToolError as err:
            out[name] = {"error": err.status.value, "detail": redact(err.message)[:120]}
    if all("error" in v for v in out.values()):
        raise ToolError(ToolStatus[next(iter(out.values()))["error"]], "all PIB feeds failed")
    return out


@case("urlscan_quotas", needs="urlscan_api_key")
def t_urlscan_quotas(client):
    q = urlscan.quotas(client)
    return {"fields": sorted(q.keys()), "quotas": q}


@case("urlscan_scan", needs="urlscan_api_key", third_party=True)
def t_urlscan(client):
    sub = urlscan.submit(client, "https://example.com/")
    if sub["status"] != "submitted":
        return sub
    done = urlscan.wait(client, sub["uuid"])
    return {"submit_ms": sub["ms"], "status": done["status"], "elapsed_s": done.get("elapsed_s"),
            "summary": urlscan.summarize(done["result"]) if done["status"] == "done" else None}


@case("sightengine_genai", needs="sightengine_user", third_party=True)
def t_sightengine(client):
    clean = sanitized_image_copy(PUBLIC_IMAGE, ROOT / "integration_results" / "tmp")
    return remote.sightengine_genai(client, clean)


@case("cloud_vision_web", needs="vision", third_party=True)
def t_vision(client):
    clean = sanitized_image_copy(PUBLIC_IMAGE, ROOT / "integration_results" / "tmp")
    res = remote.web_detection(client, clean)
    return {"pages": len(res["pages"]), "full_matches": len(res["full_matches"]), "best_guess": res["best_guess"],
            "ms": res["ms"]}


@case("ai_claim_extraction_hi_te", needs="llm", third_party=True)
def t_ai_claims_multilingual(client):
    """Claim extraction on Hindi and Telugu messages. Kept claims are quoted from the message (checked in code)."""
    out = {}
    for lang, text in (("hi", "सरकार हर छात्र को मुफ्त लैपटॉप दे रही है। 30 नवंबर से पहले laptop-yojana.top पर पंजीकरण करें।"),
                       ("te", "ప్రభుత్వం ప్రతి విద్యార్థికి ఉచిత ల్యాప్‌టాప్ ఇస్తోంది. నవంబర్ 30 లోపు నమోదు చేసుకోండి.")):
        kept, rejected = llm_extract_claims(client, text)
        out[lang] = {"kept": [k.text for k in kept], "rejected": len(rejected)}
    if not any(v["kept"] for v in out.values()):
        raise ToolError(ToolStatus.SERVICE_ERROR, f"no grounded claim extracted: {json.dumps(out, ensure_ascii=False)[:200]}")
    return out


@case("ai_claim_extraction", needs="llm", third_party=True)
def t_llm(client):
    kept, rejected = llm_extract_claims(client, "Government will give every student a free laptop. "
                                                "Register at laptop-yojana.top before Friday.")
    return {"kept": [k.text for k in kept], "rejected": rejected}


@case("ai_chat_json", needs="llm", third_party=True)
def t_ai_chat(client):
    """One JSON call per configured chat model (primary and fallback, each on its own provider)."""
    import time

    from satyapan.llm import _chat_once
    s = get_settings()
    routes = [(s.llm_model, s.llm_base_url, s.llm_api_key)]
    if s.hf_chat_fallback_model:
        routes.append((s.hf_chat_fallback_model, s.llm_fallback_base_url or s.llm_base_url, s.llm_fallback_api_key))
    out = {}
    for model, base, key in routes:
        start = time.perf_counter()
        try:
            data = _chat_once(client, model, 'Return JSON only: {"ok": true, "language": "<language of the text>"}',
                              "सरकार ने नई योजना शुरू की", 200, True, base, key)
            out[model] = {"status": "LIVE_SUCCESS", "json_keys": sorted(data), "provider": base.split("/")[2],
                          "ms": round((time.perf_counter() - start) * 1000)}
        except ToolError as err:
            out[model] = {"status": err.status.value, "error": err.message[:160], "provider": base.split("/")[2]}
    if not any(v["status"] == "LIVE_SUCCESS" for v in out.values()):
        raise ToolError(ToolStatus.SERVICE_ERROR, json.dumps(out)[:300])
    return out


@case("ai_embeddings", needs="embeddings", third_party=True)
def t_ai_embeddings(client):
    """Embeddings from every configured provider: dimensions, and that a Hindi and an English
    sentence about the same scheme are closer than two unrelated sentences (sanity check only)."""
    import time

    import numpy as np

    from satyapan.hf import _call, prepare
    s = get_settings()
    texts = ["PM Kisan 21st instalment of Rs 2000 released to farmers",
             "पीएम किसान की 21वीं किस्त के 2000 रुपये किसानों को जारी",
             "Cabinet approves new national highway projects",
             "పీఎం కిసాన్ 21వ విడత కింద రైతులకు 2000 రూపాయలు విడుదల"]
    out = {}
    for provider in [p for p in (s.hf_embedding_provider, s.hf_embedding_fallback_provider) if p]:
        start = time.perf_counter()
        mat = _call(client, provider, s.hf_embedding_model, [prepare(s.hf_embedding_model, t, "passage") for t in texts])
        sims = mat @ mat.T
        out[provider] = {"dims": int(mat.shape[1]), "ms": round((time.perf_counter() - start) * 1000),
                         "cos_en_hi_same": round(float(sims[0, 1]), 3), "cos_en_unrelated": round(float(sims[0, 2]), 3),
                         "cos_en_te_same": round(float(sims[0, 3]), 3),
                         "same_closer_than_unrelated": bool(sims[0, 1] > sims[0, 2] and sims[0, 3] > sims[0, 2]),
                         "norm": round(float(np.linalg.norm(mat[0])), 3)}
        if "bge-m3" in s.hf_embedding_model and mat.shape[1] != 1024:
            raise ToolError(ToolStatus.SERVICE_ERROR, f"bge-m3 should return 1024 dimensions, got {mat.shape[1]}")
    return out


@case("cloudflare_token", needs="cloudflare")
def t_cloudflare_token(client):
    """Cloudflare's own token check, then the account ID the URLs use (no AI usage, no neurons)."""
    from satyapan import cloudflare
    s = get_settings()
    res = cloudflare.verify_token(client, s.llm_api_key or s.embedding_api_key)
    if res.get("status") != "active":
        raise ToolError(ToolStatus.AUTH_REQUIRED, f"token status {res.get('status')}")
    return {**res, "account_id_format_ok": bool(s.cloudflare_account_id)}


@case("mongodb", needs="mongodb")
def t_mongodb(client):
    """Connect, create indexes, write and read a test record in a separate test database, check TTL."""
    from satyapan.db.mongo import MongoStore
    s = get_settings()
    st = MongoStore.connect(s.mongodb_uri, s.mongodb_db + "_integration_test")
    st.create("integrationcheck", "integration-token-" + "x" * 20)
    st.save("integrationcheck", {"status": "done"})
    ok = st.get_authorized("integrationcheck", "integration-token-" + "x" * 20) is not None
    ttl = {n: any(v.get("expireAfterSeconds") == 0 for v in st.db[n].index_information().values())
           for n in ("investigations", "evidence", "workflow_events")}
    st.db.investigations.delete_one({"_id": "integrationcheck"})
    return {"read_back": ok, "ttl_indexes": ttl, "database": s.mongodb_db + "_integration_test"}


def configured(needs: str | None) -> bool:
    s = get_settings()
    return {None: True, "google_api_key": bool(s.google_api_key), "urlscan_api_key": bool(s.urlscan_api_key),
            "sightengine_user": bool(s.sightengine_user and s.sightengine_secret),
            "vision": bool(s.google_vision_api_key or (s.vision_use_gcloud and s.google_cloud_project)),
            "llm": s.llm_configured, "embeddings": s.embeddings_configured, "mongodb": bool(s.mongodb_uri),
            "cloudflare": bool(s.cloudflare_account_id)}[needs]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-third-party", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--summary", default="SUMMARY.md", help="summary file name inside integration_results/")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, needs, third_party, fn in TESTS:
        if args.only and args.only != name:
            continue
        client = ApiClient()
        record = {"test": name, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "host": platform.node(), "status": None, "request_sent": False, "genuine_external": False}
        start = time.perf_counter()
        if third_party and not args.allow_third_party:
            record.update(status=ToolStatus.NOT_TESTED.value, reason="sends data to a third party: rerun with --allow-third-party")
        elif not configured(needs):
            record.update(status=ToolStatus.AUTH_REQUIRED.value, reason=f"{needs} not configured in .env, request not sent")
        else:
            try:
                result = fn(client)
                record.update(status=ToolStatus.LIVE_SUCCESS.value, result=result)
            except ToolError as err:
                record.update(status=err.status.value, error=redact(err.message)[:300], http_status=err.http_status)
            except Exception as exc:   # record unexpected failures rather than hiding them
                record.update(status=ToolStatus.SERVICE_ERROR.value, error=f"{type(exc).__name__}: {exc}"[:300])
        record["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)
        record["calls"] = [c.__dict__ for c in client.calls]
        record["request_sent"] = bool(client.calls)
        record["genuine_external"] = record["status"] == "LIVE_SUCCESS" and any(c.reached_service for c in client.calls)
        client.close()
        (OUT / f"{name}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        rows.append(record)
        detail = record.get("error") or record.get("reason") or ""
        print(f"{record['status']:<14} {name:<24} {record['elapsed_ms']:>8} ms  {detail[:90]}")

    lines = ["# Integration results", "", f"Run at {rows[0]['run_at'] if rows else '-'} on host `{platform.node()}`.", "",
             "| Test | Status | Request sent | Real response | HTTP | Latency ms | Detail |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        http = ", ".join(str(c["http_status"]) for c in r["calls"] if c["http_status"]) or "-"
        detail = (r.get("error") or r.get("reason") or "ok").replace("|", "/")[:80]
        lines.append(f"| {r['test']} | {r['status']} | {r['request_sent']} | {r['genuine_external']} | {http} | "
                     f"{r['elapsed_ms']} | {detail} |")
    if args.only:
        return
    (OUT / args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT / args.summary}")


if __name__ == "__main__":
    main()
