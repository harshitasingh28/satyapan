"""Import curated known debunks (claims a fact-checker rated false) from a CSV.

Columns: id,claim_text,debunk_url,publisher,date,language,rating
Every row must link to the published fact-check (https). Rows without a link are refused, so the
index only ever contains claims someone can check. Writes to MongoDB when configured, otherwise to
data/known_claims.jsonl.
Usage: python scripts/import_known_debunks.py my_debunks.csv
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.storage import open_store  # noqa: E402


def main(path: str) -> None:
    rows, refused = [], []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        url, text = (r.get("debunk_url") or "").strip(), (r.get("claim_text") or "").strip()
        if not url.startswith("https://") or len(text) < 10:
            refused.append(r.get("id") or text[:40])
            continue
        rows.append({"text": text, "url": url, "publisher": (r.get("publisher") or "").strip() or None,
                     "date": (r.get("date") or "").strip() or None, "language": (r.get("language") or "").strip() or None,
                     "rating": (r.get("rating") or "").strip() or None, "added_by": "import_known_debunks"})
    store = open_store()
    if store.kind == "mongo":
        new = store.add_known_claims(rows)
    else:
        target = get_settings().data_dir / "known_claims.jsonl"
        seen = {k.get("url") for k in store.known_claims()}
        fresh = [r for r in rows if r["url"] not in seen]
        with target.open("a", encoding="utf-8") as fh:
            for r in fresh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        new = len(fresh)
    print(f"{len(rows)} valid rows, {new} new, refused {len(refused)} without an https fact-check link: {refused[:10]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
