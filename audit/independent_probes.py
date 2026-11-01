"""The independent tester's three extra probes (X1 to X3), kept as a reproducible script.

They were found after the tester read the code, so they were not counted in its 25-case score.
Offline, mocked transport. Release records are FIXTURES for matching logic.
Usage: python audit/independent_probes.py [--root PATH_TO_CODE]   (default: this project)
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

PROBES = [
    ("X1", "release title, filler past 5,000 characters, then a scam link",
     "PM Kisan 21st instalment of Rs 2000 released to farmers. "
     + "Government of India scheme update for all citizens. " * 120
     + "Verify at https://pmkisan.gov.in.ekyc-verify.top/x",
     [{"fixture": True, "title": "PM Kisan 21st instalment of Rs 2000 released to farmers",
       "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100005", "summary": ""}], {"FAKE", "UNVERIFIED"}),
    ("X2", "Rs 5 crore in the message, Rs 5 lakh in the release",
     "Ayushman Bharat PM-JAY health cover of Rs 5 crore per family extended in 5 more states. https://pmjay.gov.in",
     [{"fixture": True, "title": "Ayushman Bharat PM-JAY health cover of Rs 5 lakh per family extended in 5 more states",
       "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100006", "summary": ""}], {"UNVERIFIED"}),
    ("X3", "unencoded open redirect on uidai.gov.in plus a matching release",
     "UIDAI extends free online Aadhaar document update facility till 14 December 2026. "
     "Update: https://uidai.gov.in/redirect?url=https://aadhaar-docs-update.top/login",
     [{"fixture": True, "title": "UIDAI extends free online Aadhaar document update facility till 14 December 2026",
       "link": "https://pib.gov.in/PressReleasePage.aspx?PRID=2100004", "summary": ""}], {"FAKE", "UNVERIFIED"}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    root = Path(ap.parse_args().root).resolve()
    os.environ["SATYAPAN_DATA_DIR"] = tempfile.mkdtemp()
    sys.path.insert(0, str(root))
    import httpx
    from satyapan.config import get_settings
    from satyapan.http import ApiClient
    from satyapan.pipeline.graph import Context, new_state, run, to_report
    from satyapan.sources.official import load_allowlist
    from satyapan.sources.pib import PibStore

    def refuse(request):
        raise httpx.ConnectError("offline", request=request)
    print(f"code under test: {root}")
    bad = 0
    for pid, desc, text, releases, ok in PROBES:
        tmp = Path(tempfile.mkdtemp())
        ctx = Context(client=ApiClient(transport=httpx.MockTransport(refuse)), settings=get_settings(),
                      pib=PibStore(tmp / "pib.jsonl"),
                      official_domains=load_allowlist(root / "templates" / "official_domains.txt"),
                      factcheckers=load_allowlist(root / "templates" / "factcheckers.txt"), work_dir=tmp / "w")
        ctx.pib.add(releases)
        rep = to_report(run(new_state(text=text), ctx))
        good = rep.verdict in ok
        bad += not good
        print(f"{'PASS' if good else 'FAIL'}  {pid} verdict={rep.verdict:<10} acceptable={sorted(ok)}  {desc}")
        for e in rep.evidence:
            print(f"        {e.tool} {e.stance}/{e.strength}: {e.established[:110]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
