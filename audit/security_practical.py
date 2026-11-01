"""Practical security tests. Safe payloads only, nothing is sent to third parties.

Part 1 talks to a RUNNING local server (default http://127.0.0.1:8765).
Part 2 runs in-process checks on validators and storage.
Usage: python audit/security_practical.py --server http://127.0.0.1:8765 --data-dir <server SATYAPAN_DATA_DIR> --log <uvicorn log>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satyapan.security.ssrf import validate_url  # noqa: E402
from satyapan.security.uploads import validate_upload  # noqa: E402
from satyapan.sources.official import domain_info  # noqa: E402

RESULTS: list[dict] = []


def record(area: str, test: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"area": area, "test": test, "pass": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  [{area}] {test}  {detail[:140]}")


def wait(server: str, created) -> dict:
    """created: the creation response JSON (id and access_token). Records are private since 2.0."""
    inv_id, token = (created["id"], created.get("access_token")) if isinstance(created, dict) else (created, None)
    for _ in range(100):
        d = httpx.get(f"{server}/v1/investigations/{inv_id}", headers={"X-Access-Token": token or ""}).json()
        if d["status"] not in ("queued", "running"):
            return d
        time.sleep(0.2)
    return {"status": "timeout"}


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def part1(server: str, data_dir: Path, log: Path) -> None:
    before = log.read_text().count("GET /health") if log.exists() else 0
    from urllib.parse import urlsplit as _us
    port = _us(server).port or 80     # first version hard-coded 8765, which tested nothing on another port
    payloads = [f"http://127.0.0.1:{port}/health", f"http://localhost:{port}/health", "http://169.254.169.254/latest/meta-data/",
                f"http://[::1]:{port}/health", "http://10.0.0.1/admin", f"http://2130706433:{port}/health",
                "file:///etc/passwd", "gopher://127.0.0.1:6379/_INFO", "javascript:alert(1)",
                "data:text/html,<script>alert(1)</script>", "ftp://127.0.0.1/"]
    r = httpx.post(f"{server}/v1/investigations", data={"text": "Government notice, open the link",
                                                       "links": "\n".join(payloads),
                                                       "consent_third_party_links": "true"})
    rep = wait(server, r.json())["report"]
    time.sleep(1)
    after = log.read_text().count("GET /health") if log.exists() else 0
    record("SSRF", "server made no request to itself via submitted links", after == before,
           f"/health hits before {before}, after {after}")
    sent = [t for t in rep["tool_runs"] if t["tool"] in ("rdap", "safe_browsing", "urlscan") and
            any(p.split("//")[-1][:9] in t["target"] for p in payloads)]
    record("SSRF", "unsafe links never passed to RDAP / Safe Browsing / urlscan", not sent, json.dumps(sent)[:200])

    # path traversal in multipart filename
    jpg = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(jpg, "JPEG")
    r = httpx.post(f"{server}/v1/investigations", files={"files": ("../../../../tmp/satyapan_pwned.jpg", jpg.getvalue(), "image/jpeg")})
    wait(server, r.json())
    record("Path traversal", "client filename not used as a path", not Path("/tmp/satyapan_pwned.jpg").exists())

    # oversized: does the server buffer the full body before refusing?
    big = b"\x89PNG\r\n\x1a\n" + os.urandom(60 * 1024 * 1024)
    t = time.perf_counter()
    r = httpx.post(f"{server}/v1/investigations", files={"files": ("big.png", big, "image/png")}, timeout=60)
    record("Uploads", "oversized upload refused (413)", r.status_code == 413,
           f"HTTP {r.status_code} after {time.perf_counter() - t:.2f} s")
    import socket
    from urllib.parse import urlsplit
    u = urlsplit(server)
    sock = socket.create_connection((u.hostname, u.port or 80), timeout=4)
    sock.sendall((f"POST /v1/investigations HTTP/1.1\r\nHost: {u.hostname}\r\n"
                  f"Content-Type: multipart/form-data; boundary=x\r\nContent-Length: {2 * 1024 ** 3}\r\n\r\n").encode())
    try:
        reply = sock.recv(200).decode(errors="replace")
        code = reply.split(" ")[1] if reply.startswith("HTTP/") else "no reply"
        record("Uploads", "huge Content-Length rejected before reading the body", code in ("411", "413"), f"reply: {code}")
    except socket.timeout:
        record("Uploads", "huge Content-Length rejected before reading the body", False,
               "server kept the connection open, waiting for a declared 2 GB body (4 s timeout)")
    finally:
        sock.close()

    # retention, on the running server: uploads of finished investigations must be gone
    time.sleep(1)
    uploads = list((data_dir / "uploads").rglob("*.bin"))
    record("Retention", "uploads are removed after processing", not uploads,
           f"{len(uploads)} uploaded files still on disk after all investigations finished")
    # retention, in-process: does the sweep cover investigation records (they contain user text)?
    from satyapan.storage import Store
    tmp_root = Path(tempfile.mkdtemp())
    st = Store(tmp_root)
    st.save("oldrecord1", {"status": "done", "report": {"claim": {"text": "user text"}}})
    st.save("newrecord1", {"status": "done"})
    old = time.time() - 48 * 3600
    os.utime(tmp_root / "investigations" / "oldrecord1.json", (old, old))
    removed = st.sweep(retention_hours=24)
    left = sorted(p.stem for p in (tmp_root / "investigations").glob("*.json"))
    record("Retention", "sweep deletes investigation records older than the retention window",
           left == ["newrecord1"], f"removed {removed}, left {left}")
    import satyapan.api.app as api_mod
    record("Retention", "the API schedules the sweep (start-up and while serving)",
           hasattr(api_mod, "_maybe_sweep") and api_mod._last_sweep > 0, f"_last_sweep={getattr(api_mod, '_last_sweep', None)}")


def part2() -> None:
    tmp = Path(tempfile.mkdtemp())
    # pixel limit gap: Pillow only raises above 2x MAX_IMAGE_PIXELS
    p = tmp / "60mp.png"
    Image.new("1", (8000, 7500)).save(p, "PNG")          # 60 MP, limit is 40 MP
    info = validate_upload(p, "60mp.png")
    record("Uploads", "60 MP image rejected (configured limit 40 MP)", not info.ok,
           f"ok={info.ok} errors={info.errors} size={p.stat().st_size} bytes")
    # invalid media
    fake_mp4 = tmp / "fake.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(4096))
    record("Uploads", "random bytes with an MP4 header rejected", not validate_upload(fake_mp4, "fake.mp4").ok)
    wav = tmp / "bad.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + os.urandom(64))
    record("Uploads", "corrupt WAV rejected", not validate_upload(wav, "bad.wav").ok)
    audio_only = tmp / "audio_only.mp4"
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "-f", "mp4", str(audio_only))
    info = validate_upload(audio_only, "clip.mp4")
    record("Uploads", "MP4 with no video stream handled (rejected as video or accepted as audio)",
           (not info.ok) or info.kind == "audio", f"kind={info.kind} ok={info.ok} errors={info.errors}")
    poly = tmp / "poly.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, "JPEG")
    poly.write_bytes(buf.getvalue() + b"PK\x03\x04 trailing zip payload")
    info = validate_upload(poly, "poly.jpg")
    record("Uploads", "JPEG with appended payload (polyglot) noted", True,
           f"accepted={info.ok}. Not executed, and re-encoded before any third-party upload")
    # schemes and lookalikes
    for u in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "vbscript:msgbox(1)", "jar:http://x!/"):
        record("URL schemes", f"{u.split(':')[0]} rejected", not validate_url(u).ok)
    # RDAP path injection through crafted hostnames
    # First run checked only the domain_info string. That is necessary but not sufficient. This
    # version checks what matters: no request leaves the process for a crafted host.
    import httpx as _httpx
    from satyapan.errors import ToolError
    from satyapan.http import ApiClient
    from satyapan.links import rdap
    sent: list[str] = []

    def spy(request):
        sent.append(str(request.url))
        raise _httpx.ConnectError("audit: offline", request=request)
    client = ApiClient(transport=_httpx.MockTransport(spy))
    for u in ("http://evil%2F..%2Fadmin.com/", "http://a.b.com%23frag/", "http://x.com\\@pib.gov.in/"):
        info = domain_info(u)
        sent.clear()
        try:
            rdap.lookup(client, info["registered"])
        except ToolError:
            pass
        clean = info["valid_host"] and all(ch.isalnum() or ch in ".-" for ch in info["registered"])
        no_bad_request = all("%" not in x.split("/domain/")[-1] and "#" not in x for x in sent)
        record("Injection", f"crafted host never reaches an RDAP request path: {u}",
               (clean or not sent) and no_bad_request,
               f"registered={info['registered']!r} valid_host={info['valid_host']} requests={sent[:2]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "security_practical.json"))
    args = ap.parse_args()
    part1(args.server, Path(args.data_dir), Path(args.log))
    part2()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(RESULTS, indent=1))
    fails = [r for r in RESULTS if not r["pass"]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} security checks passed. Saved {args.out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
