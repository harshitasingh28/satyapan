"""Collect REAL fact-check records from the Google Fact Check Tools API for the evaluation set.

Every row keeps the API's own fields (claim text, publisher, URL, rating, review date, language)
so its label comes from the fact-checker, not from us. Output is a CANDIDATE list: a team member
must open each fact-check, confirm the label and copy the row into eval/manifest.csv with
collected_by and collected_on filled in. Nothing here is invented.
Usage: python scripts/collect_factchecks.py --query "PM Kisan" --language hi --out eval/candidates_hi.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.errors import ToolError  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.sources import factcheck  # noqa: E402

FIELDS = ["claim_text", "rating", "rating_class", "publisher", "site", "url", "review_date", "claim_date", "language",
          "query", "retrieved_on"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", required=True, help="repeatable")
    ap.add_argument("--language", default=None, help="en, hi or te")
    ap.add_argument("--max-age-days", type=int, default=730)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    client, rows, seen = ApiClient(), [], set()
    for q in args.query:
        try:
            res = factcheck.search(client, q, language=args.language, max_age_days=args.max_age_days, page_size=50)
        except ToolError as err:
            print(f"{q}: {err.status.value} {err.message[:160]}")
            continue
        for rv in res["reviews"]:
            if rv["url"] in seen:
                continue
            seen.add(rv["url"])
            rows.append({**{k: rv.get(k) for k in FIELDS if k in rv}, "query": q, "retrieved_on": date.today().isoformat()})
        print(f"{q}: {len(res['reviews'])} reviews")
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} candidate rows to {args.out}. Review each one before it enters eval/manifest.csv.")


if __name__ == "__main__":
    main()
