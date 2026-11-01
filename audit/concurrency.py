"""Concurrency tests.

Part 1 (in-process): the per-tool daily budget under 8 threads, each with its own
DailyBudget object on one file (the app builds one per investigation).
Part 2 (running server): N simultaneous image investigations with consent on.
Records each job's final status and time, total time, and the server's peak RSS
(VmHWM from /proc, Linux only).
Usage: python audit/concurrency.py --server http://127.0.0.1:8765 --pid <uvicorn pid> --image big.jpg [--n 8]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def budget_race() -> dict:
    from satyapan.security.ratelimit import DailyBudget
    path = Path(tempfile.mkdtemp()) / "budget.json"
    granted, errors = [], []

    def worker():
        b = DailyBudget(path, {"tool": 20})
        for _ in range(5):
            try:
                granted.append(b.take("tool"))
            except Exception as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = json.loads(path.read_text())["used"]["tool"]
    res = {"attempts": 40, "limit": 20, "granted": sum(granted), "exceptions": errors, "file_count": final,
           "pass": sum(granted) == 20 and final == 20 and not errors}
    print(f"{'PASS' if res['pass'] else 'FAIL'}  budget race: granted {res['granted']}/40 (limit 20), "
          f"file says {final}, exceptions {errors}")
    return res


def peak_rss_mb(pid: int) -> float | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


def server_load(server: str, pid: int, image: Path, n: int) -> dict:
    data = image.read_bytes()
    results: list[dict] = [{} for _ in range(n)]
    t0 = time.perf_counter()

    def job(i: int) -> None:
        start = time.perf_counter()
        r = httpx.post(f"{server}/v1/investigations", files={"files": (f"img{i}.jpg", data, "image/jpeg")},
                       data={"consent_third_party_media": "true"}, timeout=60)
        if r.status_code != 202:
            results[i] = {"i": i, "http": r.status_code}
            return
        inv, token = r.json()["id"], r.json()["access_token"]
        seen = set()
        while True:
            d = httpx.get(f"{server}/v1/investigations/{inv}", headers={"X-Access-Token": token}, timeout=30).json()
            seen.add(d["status"])
            if d["status"] not in ("queued", "running"):
                break
            time.sleep(0.3)
        rep = d.get("report") or {}
        slow = sorted(((t["tool"], t["status"], t["ms"]) for t in rep.get("tool_runs", [])), key=lambda x: -x[2])[:2]
        results[i] = {"i": i, "http": 202, "status": d["status"], "error": d.get("error"), "states_seen": sorted(seen),
                      "s": round(time.perf_counter() - start, 1), "verdict": rep.get("verdict"), "slowest": slow,
                      "failed_tools": [t["tool"] for t in rep.get("tool_runs", [])
                                       if t["status"] in ("SERVICE_ERROR",) and t["tool"] in ("ocr_tesseract",)]}
    threads = [threading.Thread(target=job, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = round(time.perf_counter() - t0, 1)
    done = sum(r.get("status") == "done" for r in results)
    res = {"n": n, "total_s": total, "done": done, "server_peak_rss_mb": peak_rss_mb(pid), "jobs": results,
           "pass": done == n}
    print(f"{'PASS' if res['pass'] else 'FAIL'}  {n} concurrent investigations: {done}/{n} done, total {total} s, "
          f"server peak RSS {res['server_peak_rss_mb']} MB")
    for r in results:
        print("   ", r)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "concurrency.json"))
    args = ap.parse_args()
    out = {"budget_race": budget_race(), "server": server_load(args.server, args.pid, Path(args.image), args.n)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    sys.exit(0 if out["budget_race"]["pass"] and out["server"]["pass"] else 1)


if __name__ == "__main__":
    main()
