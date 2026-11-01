"""FastAPI backend (Satyapan 2.0).

POST /v1/investigations/stream   multipart in, server-sent events out: the pipeline runs INSIDE this
                                 request and every node is streamed as it starts and ends. Cloud Run
                                 only gives CPU during a request (request-based billing), so work that
                                 continued after a 202 reply would stall there.
POST /v1/investigations          the same form, 202 + background thread (local use, CLI, tests)
GET  /v1/investigations/{id}     record and report. Needs the X-Access-Token returned at creation
GET  /v1/investigations/{id}/events
GET  /v1/investigations/{id}/report.md | report.json    downloads (token in header or ?token=)
GET  /v1/status                  which integrations are configured (booleans only), models, limits
GET  /health

Records are private to whoever holds the token. Only its SHA-256 hash is stored. A wrong token
gives 404, so the API never confirms that an id exists.
At most SATYAPAN_MAX_CONCURRENT_JOBS investigations run at once per instance, the rest wait.
Request bodies must declare Content-Length and are refused before reading if too large.
Client IP for rate limiting: the TCP peer, or with SATYAPAN_TRUSTED_PROXY_HOPS=N the N-th address
from the right of X-Forwarded-For (Cloud Run: 1). Addresses further left are client-supplied and
ignored, so a spoofed header cannot dodge the limit.
Run: uvicorn satyapan.api.app:app
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from satyapan.config import get_settings
from satyapan.logging_setup import log, setup_logging
from satyapan.pipeline.graph import Context, new_state, run, to_report
from satyapan.pipeline.report import markdown_report
from satyapan.security.ratelimit import TokenBucket
from satyapan.storage import new_token, open_store

setup_logging()
logger = logging.getLogger("satyapan.api")
settings = get_settings()
store = open_store()
if store.note:
    logger.warning(store.note)
bucket = TokenBucket(settings.rate_limit_per_minute)
app = FastAPI(title="Satyapan", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Access-Token"])
CHUNK = 1024 * 1024
MAX_UPLOAD = max(settings.max_image_mb, settings.max_video_mb, settings.max_audio_mb) * 1024 * 1024
MAX_REQUEST = MAX_UPLOAD + 2 * 1024 * 1024      # all files together, plus form fields
JOBS = threading.BoundedSemaphore(settings.max_concurrent_jobs)
SWEEP_EVERY_S = 600
STALE_RUNNING_S = 900
KEEPALIVE_S = 10
_last_sweep = 0.0


def _maybe_sweep() -> None:
    global _last_sweep
    if time.time() - _last_sweep > SWEEP_EVERY_S:
        _last_sweep = time.time()
        removed = store.sweep()
        if removed:
            log(logger, "retention sweep", removed=removed)


_maybe_sweep()      # at start-up


def client_ip(request: Request) -> str:
    hops = settings.trusted_proxy_hops
    if hops > 0:
        chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method == "POST":
        # Refuse oversized or undeclared bodies BEFORE reading them. Without this, Starlette
        # buffers the whole multipart body (to memory or disk) before any size check runs.
        declared = request.headers.get("content-length")
        if declared is None:
            return JSONResponse({"error": "Content-Length required"}, status_code=411)
        if not declared.isdigit() or int(declared) > MAX_REQUEST:
            return JSONResponse({"error": f"request larger than {MAX_REQUEST // (1024 * 1024)} MB"}, status_code=413)
        if not bucket.allow(client_ip(request)):
            return JSONResponse({"error": "rate limit exceeded, try again in a minute"}, status_code=429)
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


_status_cache: dict = {"at": 0.0, "data": None}


def _host(url: str) -> str | None:
    from urllib.parse import urlsplit
    return urlsplit(url).hostname if url else None


@app.get("/v1/status")
def status() -> dict:
    if _status_cache["data"] and time.time() - _status_cache["at"] < 60:
        return _status_cache["data"]
    s = settings
    d = s.data_dir

    def count_index(folder: Path) -> int:
        try:
            meta = json.loads((folder / "index.json").read_text(encoding="utf-8"))
            return len(meta.get("ids", meta) if isinstance(meta, dict) else meta)
        except (OSError, ValueError):
            return 0
    try:
        pib_count = len(store.pib_store().load())
        known_count = len(store.known_claims())
    except Exception:  # noqa: BLE001
        pib_count = known_count = 0
    data = {
        "version": app.version,
        "store": store.kind,
        "store_note": store.note,
        "config_notes": [n for n in (s.cloudflare_note,) if n],
        "integrations": {
            "factcheck": bool(s.google_api_key), "safe_browsing": bool(s.google_api_key),
            "rdap": True, "wikidata": True, "ai_chat": s.llm_configured, "ai_embeddings": s.embeddings_configured,
            "mongodb": store.kind == "mongo", "urlscan": bool(s.urlscan_api_key),
            "cloud_vision": bool(s.google_vision_api_key or s.vision_use_gcloud),
            "sightengine": bool(s.sightengine_user and s.sightengine_secret),
        },
        "models": {"chat": s.llm_model or None, "chat_fallback": s.hf_chat_fallback_model or None,
                   "embedding": s.hf_embedding_model or None},
        # host names only, so users can see who receives their text (never keys)
        "providers": {"chat": _host(s.llm_base_url) if s.llm_configured else None,
                      "chat_fallback": _host(s.llm_fallback_base_url) if s.hf_chat_fallback_model else None,
                      "embedding": (_host(s.embedding_base_url) if s.hf_embedding_provider in ("openai", "cloudflare")
                                    else f"router.huggingface.co ({s.hf_embedding_provider})")
                      if s.embeddings_configured else None},
        "corpus": {"pib_releases": pib_count, "known_claims": known_count,
                   "known_images": count_index(d / "image_index"), "known_audio": count_index(d / "audio_index")},
        "limits": {"max_text_chars": s.max_text_chars, "max_links": 10, "max_files": 4,
                   "max_image_mb": s.max_image_mb, "max_video_mb": s.max_video_mb, "max_audio_mb": s.max_audio_mb,
                   "max_media_seconds": s.max_media_seconds},
        "retention_hours": s.retention_hours,
    }
    _status_cache.update(at=time.time(), data=data)
    return data


def _save_upload(upload: UploadFile, folder: Path) -> Path:
    target = folder / f"{uuid.uuid4().hex}.bin"   # never trust the client file name for paths
    size = 0
    with target.open("wb") as fh:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD:
                fh.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"{upload.filename}: file too large")
            fh.write(chunk)
    return target


def _prepare(text: str, links: str, files: list[UploadFile] | None, consent: dict) -> tuple[dict, str]:
    files = files or []
    if not text.strip() and not links.strip() and not files:
        raise HTTPException(400, "send text, links or at least one file")
    if len(files) > 4:
        raise HTTPException(400, "at most 4 files")
    state = new_state(text=text, links=[ln.strip() for ln in links.splitlines() if ln.strip()][:10], consent=consent)
    token = new_token()
    store.create(state["id"], token, {"input": {"text_chars": len(text), "links": len(state["user_links"]),
                                                "files": len(files)}})
    folder = store.upload_dir(state["id"])
    try:
        state["uploads"] = [(_save_upload(f, folder), f.filename or "upload") for f in files]
    except HTTPException:
        store.discard_files(state["id"])
        store.save(state["id"], {"status": "error", "error": "file too large"})
        raise
    return state, token


def _execute(state: dict, emit=None) -> dict | None:
    """Run one investigation under the job limit. Returns the report dict, or None on error."""
    with JOBS:
        try:
            store.save(state["id"], {"status": "running"})
            state = run(state, Context.default(store=store, emit=emit))
            report = to_report(state).to_dict()
            store.save(state["id"], {"status": "done", "report": report})
            log(logger, "investigation done", id=state["id"], verdict=state["verdict"]["label"])
            return report
        except Exception as exc:  # the API must report failure, not hang
            logger.exception("investigation failed")
            store.save(state["id"], {"status": "error", "error": type(exc).__name__})
            return None
        finally:
            store.discard_files(state["id"])     # uploads and frames are not kept after the report


def _consent(text: bool, links: bool, media: bool) -> dict:
    return {"third_party_text": text, "third_party_links": links, "third_party_media": media}


@app.post("/v1/investigations", status_code=202)
def create(text: str = Form(""), links: str = Form(""), files: list[UploadFile] | None = File(None),
           consent_third_party_text: bool = Form(False), consent_third_party_links: bool = Form(False),
           consent_third_party_media: bool = Form(False)) -> dict:
    state, token = _prepare(text, links, files, _consent(consent_third_party_text, consent_third_party_links,
                                                          consent_third_party_media))
    def emit(ev: dict) -> None:
        store.add_event(state["id"], ev)
    threading.Thread(target=_execute, args=(state, emit), daemon=True).start()
    _maybe_sweep()
    return {"id": state["id"], "status": "queued", "access_token": token}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.post("/v1/investigations/stream")
def create_stream(text: str = Form(""), links: str = Form(""), files: list[UploadFile] | None = File(None),
                  consent_third_party_text: bool = Form(False), consent_third_party_links: bool = Form(False),
                  consent_third_party_media: bool = Form(False)) -> StreamingResponse:
    state, token = _prepare(text, links, files, _consent(consent_third_party_text, consent_third_party_links,
                                                          consent_third_party_media))
    inv_id = state["id"]
    expires = (datetime.now(timezone.utc) + timedelta(hours=settings.retention_hours)).isoformat(timespec="seconds")
    q: queue.Queue = queue.Queue()

    def emit(ev: dict) -> None:
        store.add_event(inv_id, ev)
        q.put(("step", ev))

    def worker() -> None:
        if not JOBS.acquire(blocking=False):
            q.put(("queued", {"id": inv_id, "message": "Other investigations are running. Yours starts next."}))
        else:
            JOBS.release()
        report = _execute(state, emit)
        if report is None:
            q.put(("error", {"id": inv_id, "status": "error", "message": "The investigation failed. Please retry."}))
        else:
            q.put(("done", {"id": inv_id, "status": "done", "report": report}))
        q.put(None)

    def stream():
        yield _sse("created", {"id": inv_id, "access_token": token, "status": "queued", "expires_at": expires})
        threading.Thread(target=worker, daemon=True).start()
        while True:
            try:
                item = q.get(timeout=KEEPALIVE_S)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield _sse(*item)
        _maybe_sweep()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def _authorized(investigation_id: str, token: str | None) -> dict:
    rec = store.get_authorized(investigation_id, token)
    if rec is None:
        raise HTTPException(404, "not found")
    if rec.get("status") == "running":
        updated = rec.get("updated_at") or rec.get("created_at")
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(updated))).total_seconds()
        except ValueError:
            age = 0
        if age > STALE_RUNNING_S:
            rec["status"] = "interrupted"
    return rec


@app.get("/v1/investigations/{investigation_id}")
def get(investigation_id: str, x_access_token: str | None = Header(None)) -> dict:
    rec = _authorized(investigation_id, x_access_token)
    return {k: rec.get(k) for k in ("id", "status", "created_at", "expires_at", "report", "error") if k in rec}


@app.get("/v1/investigations/{investigation_id}/events")
def events(investigation_id: str, x_access_token: str | None = Header(None)) -> dict:
    _authorized(investigation_id, x_access_token)
    return {"events": store.events(investigation_id)}


def _report_or_404(investigation_id: str, header_token: str | None, query_token: str | None) -> dict:
    rec = _authorized(investigation_id, header_token or query_token)
    if not rec.get("report"):
        raise HTTPException(404, "report not ready")
    return rec["report"]


@app.get("/v1/investigations/{investigation_id}/report.md")
def report_md(investigation_id: str, x_access_token: str | None = Header(None),
              token: str | None = Query(None)) -> PlainTextResponse:
    rep = _report_or_404(investigation_id, x_access_token, token)
    return PlainTextResponse(markdown_report(rep), media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="satyapan-{investigation_id}.md"', "Cache-Control": "no-store"})


@app.get("/v1/investigations/{investigation_id}/report.json")
def report_json(investigation_id: str, x_access_token: str | None = Header(None),
                token: str | None = Query(None)) -> JSONResponse:
    rep = _report_or_404(investigation_id, x_access_token, token)
    return JSONResponse(rep, headers={"Content-Disposition": f'attachment; filename="satyapan-{investigation_id}.json"',
                                      "Cache-Control": "no-store"})
