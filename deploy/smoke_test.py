"""Smoke test a running Satyapan API (local or Cloud Run). Real requests, no mocks.

Checks: health, status, a streamed investigation whose events arrive one by one (different arrival
times, so the proxy is not buffering), private record access, report download, CORS, and that a
spoofed X-Forwarded-For header does not reset the rate limit (optional, sends many requests).
Usage: python deploy/smoke_test.py --api https://satyapan-api-xxxx.a.run.app --origin https://satyapan-web-xxxx.a.run.app
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

TEXT = "Government gives free laptops to all students. Register at http://free-laptop-yojana.top/apply"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--origin", default=None)
    ap.add_argument("--check-rate-limit", action="store_true")
    a = ap.parse_args()
    api, results = a.api.rstrip("/"), []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

    with httpx.Client(timeout=120) as c:
        check("health", c.get(f"{api}/health").json().get("ok") is True)
        st = c.get(f"{api}/v1/status").json()
        check("status", "integrations" in st, json.dumps(st["integrations"]))
        arrivals, events, start = [], [], time.perf_counter()
        with c.stream("POST", f"{api}/v1/investigations/stream",
                      data={"text": TEXT, "consent_third_party_text": "true", "consent_third_party_links": "true"}) as r:
            buf = ""
            for chunk in r.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
                    if lines:
                        ev = next(ln[7:] for ln in lines if ln.startswith("event: "))
                        events.append((ev, json.loads("".join(ln[6:] for ln in lines if ln.startswith("data: ")))))
                        arrivals.append(round(time.perf_counter() - start, 2))
        names = [e for e, _ in events]
        check("stream created...done", bool(names) and names[0] == "created" and names[-1] == "done", f"{len(names)} events")
        spread = (arrivals[-1] - arrivals[0]) if arrivals else 0
        check("events arrive incrementally (not buffered)", len(set(arrivals)) > 3 and spread > 0.2,
              f"first {arrivals[:1]} last {arrivals[-1:]} s")
        created, report = events[0][1], events[-1][1].get("report", {})
        print("      verdict:", report.get("verdict"), "| tools:", [(t["tool"], t["status"]) for t in report.get("tool_runs", [])])
        inv, tok = created["id"], created["access_token"]
        check("record needs the token", c.get(f"{api}/v1/investigations/{inv}").status_code == 404)
        check("record opens with the token", c.get(f"{api}/v1/investigations/{inv}",
                                                   headers={"X-Access-Token": tok}).json().get("status") == "done")
        md = c.get(f"{api}/v1/investigations/{inv}/report.md", headers={"X-Access-Token": tok})
        check("markdown report", md.status_code == 200 and "Satyapan verification report" in md.text)
        if a.origin:
            ok = c.options(f"{api}/v1/status", headers={"Origin": a.origin, "Access-Control-Request-Method": "GET"})
            bad = c.options(f"{api}/v1/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
            check("CORS allows the web app", ok.headers.get("access-control-allow-origin") == a.origin)
            check("CORS refuses other origins", "access-control-allow-origin" not in bad.headers)
        if a.check_rate_limit:
            codes = [c.post(f"{api}/v1/investigations", data={"text": "rate limit probe message"},
                            headers={"X-Forwarded-For": f"10.9.{i}.1"}).status_code for i in range(15)]
            check("spoofed X-Forwarded-For does not bypass the rate limit", 429 in codes, str(codes))
    print(f"{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
