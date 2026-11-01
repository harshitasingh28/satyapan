"""Grow data/official_domains.txt from Wikidata's official-website property (P856).

Input: one official body per line in data/official_bodies.txt (English Wikidata label).
Prints what Wikidata returned. Review the output before appending: Wikidata is
community-edited, so a human must confirm each domain against the body's own page.

Usage: python scripts/build_allowlist.py           (dry run)
       python scripts/build_allowlist.py --append  (append reviewed domains)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.errors import ToolError  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.sources.official import load_allowlist, wikidata_official_sites  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()
    d = get_settings().data_dir
    names = [ln.strip() for ln in (d / "official_bodies.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    allow, client, found = load_allowlist(d / "official_domains.txt"), ApiClient(), []
    for name in names:
        try:
            res = wikidata_official_sites(client, name)
        except ToolError as err:
            print(f"{name}: {err.status.value}")
            continue
        print(f"{name}: {res['registered'] or 'no P856'}  ({', '.join(res['items'][:2])})")
        found += [dom for dom in res["registered"] if dom not in allow]
    if args.append and found:
        with (d / "official_domains.txt").open("a", encoding="utf-8") as fh:
            for dom in sorted(set(found)):
                fh.write(f"{dom}\n")
        print(f"appended {len(set(found))} domains")


if __name__ == "__main__":
    main()
