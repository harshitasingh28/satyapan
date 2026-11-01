"""Independent adversarial verdict harness (offline).

Runs every case in audit/independent_adversarial_cases.json through the real
pipeline with all network access refused, and records verdict, evidence and
any exception. Results go to results/audit/independent_adversarial.json.

Run from the project root:  python audit/independent_adversarial.py
"""
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["SATYAPAN_DATA_DIR"] = tempfile.mkdtemp(prefix="satyapan-indep-data-")

import httpx  # noqa: E402

from satyapan.config import get_settings  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.pipeline.graph import Context, new_state, run, to_report  # noqa: E402
from satyapan.sources.official import load_allowlist  # noqa: E402
from satyapan.sources.pib import PibStore  # noqa: E402

CASES = ROOT / "audit" / "independent_adversarial_cases.json"
OUT = ROOT / "results" / "audit" / "independent_adversarial.json"


def refuse(request):
    raise httpx.ConnectError("offline", request=request)


def make_ctx(known_claims=None, releases=None):
    client = ApiClient(transport=httpx.MockTransport(refuse))
    tmp = Path(tempfile.mkdtemp(prefix="satyapan-indep-case-"))
    ctx = Context(
        client=client,
        settings=get_settings(),
        pib=PibStore(tmp / "pib.jsonl"),
        known_claims=list(known_claims or []),
        official_domains=load_allowlist(Path("templates/official_domains.txt")),
        factcheckers=load_allowlist(Path("templates/factcheckers.txt")),
        work_dir=tmp / "w",
    )
    if releases:
        ctx.pib.add(releases)
    return ctx


def ev_dict(e):
    out = {}
    for k in ("tool", "stance", "strength", "established", "source", "independence_key"):
        if hasattr(e, k):
            v = getattr(e, k)
            out[k] = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
    return out


def case_text(case):
    text = case["text"]
    rep = case.get("prefix_repeat")
    if rep:
        text = rep["unit"] * int(rep["times"]) + text
    return text


def run_case(case):
    rec = {"id": case["id"], "acceptable": sorted(case["acceptable"]),
           "text_len": len(case_text(case))}
    try:
        ctx = make_ctx(case.get("known_claims"), case.get("pib_releases"))
        rep = to_report(run(new_state(text=case_text(case)), ctx))
        rec["verdict"] = str(getattr(rep.verdict, "value", rep.verdict))
        rec["evidence"] = [ev_dict(e) for e in rep.evidence]
        rec["tool_runs"] = [str(t) for t in (rep.tool_runs or [])]
        rec["exception"] = None
    except Exception as exc:  # crash counts as a failure
        rec["verdict"] = None
        rec["evidence"] = []
        rec["tool_runs"] = []
        rec["exception"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        rec["traceback"] = traceback.format_exc()
    rec["pass"] = rec["verdict"] in case["acceptable"]
    return rec


def sanity():
    """Fixture mechanism self-check (not a counted case): an exact release
    title with an official link should reach strong support."""
    title = "PM-KISAN 21st instalment of Rs 2,000 released to over 9 crore farmers"
    ctx = make_ctx(releases=[{"title": title,
                              "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100003",
                              "summary": ""}])
    rep = to_report(run(new_state(text=title + ". Details: https://pmkisan.gov.in"), ctx))
    v = str(getattr(rep.verdict, "value", rep.verdict))
    return {"control_exact_release": v,
            "evidence": [ev_dict(e) for e in rep.evidence]}


def main():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    results = [run_case(c) for c in cases]
    try:
        san = sanity()
    except Exception as exc:
        san = {"error": repr(exc)}
    passed = sum(r["pass"] for r in results)
    for r in results:
        tag = "PASS" if r["pass"] else "FAIL"
        extra = f" EXC={r['exception']}" if r["exception"] else ""
        print(f"{tag} {r['id']}: verdict={r['verdict']} acceptable={r['acceptable']}{extra}")
    print(f"SANITY control (exact release + official link): {san.get('control_exact_release', san)}")
    print(f"{passed}/{len(results)} passed")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"passed": passed, "total": len(results),
                               "sanity": san, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
