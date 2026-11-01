"""Command-line investigation, handy for testing before any UI exists.

  python -m satyapan.cli --text "PM Kisan gives Rs 10,000, apply at pmkisan-gov.top"
  python -m satyapan.cli --file forward.jpg --consent-media
  python -m satyapan.cli --text "..." --json > report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from satyapan.pipeline.graph import Context, new_state, run, to_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="")
    ap.add_argument("--link", action="append", default=[])
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--consent-text", action="store_true", help="allow sending text to the configured LLM")
    ap.add_argument("--consent-links", action="store_true", help="allow urlscan sandbox scans")
    ap.add_argument("--consent-media", action="store_true", help="allow Cloud Vision / Sightengine uploads")
    ap.add_argument("--urlscan", action="store_true", help="wait for urlscan (30-150 s)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    ctx = Context.default()
    ctx.run_urlscan = args.urlscan
    state = new_state(text=args.text, links=args.link, media=[(Path(f), Path(f).name) for f in args.file],
                      consent={"third_party_text": args.consent_text, "third_party_links": args.consent_links,
                               "third_party_media": args.consent_media})
    report = to_report(run(state, ctx))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=1, default=str))
        return
    print(f"CLAIM     {report.claim.text}")
    print(f"VERDICT   {report.verdict}")
    print(f"STRENGTH  {report.strength_explanation}")
    for s in report.reason:
        print(f"  because {s.text}  [{', '.join(s.evidence_ids)}]")
    for mid, a in report.media_assessment.items():
        print(f"MEDIA {mid}  {a}")
    print("TOOLS")
    for t in report.tool_runs:
        print(f"  {t.status:<22} {t.tool:<20} {t.ms:>8.1f} ms  {t.detail[:60]}")
    print("LIMITATIONS")
    for lim in report.limitations:
        print(f"  - {lim}")


if __name__ == "__main__":
    main()
