"""Fill data/pib_releases.jsonl, the local index of official PIB press releases.

Three ways in:
  python scripts/ingest_pib.py
      fetch PIB's RSS feeds directly (run it on a schedule, e.g. hourly)
  python scripts/ingest_pib.py --from-file ~/Downloads/pib_en.xml
      PIB refused our client with HTTP 403 on 31 Oct 2026. Open the feed in a browser,
      save it (Cmd+S, format "Page Source"), and import the file. Same parser as the live path.
  python scripts/ingest_pib.py --add --title "..." --link "https://pib.gov.in/PressReleasePage.aspx?PRID=..."
      add one release by hand, copied from the release page. Only pib.gov.in links are accepted.
  python scripts/ingest_pib.py --set-date --prid 2100005 --published 2026-10-30
      record the publication date shown on the release page (the RSS feed has none). Needed for
      the outdated-news check: without a date Satyapan cannot tell old news from new.
  python scripts/ingest_pib.py --copy-local-to-mongo
      copy data/pib_releases.jsonl into MongoDB (source_documents) when MONGODB_URI is set.

Where releases go: MongoDB when MONGODB_URI is set, otherwise data/pib_releases.jsonl.

PIB's copyright policy allows reproduction with acknowledgement. We store title, link and
summary and always link back. Feeds saved by hand are only as fresh as the last save.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.errors import ToolError  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.sources.official import domain_info  # noqa: E402
from satyapan.sources.pib import FEEDS, PRID_RE, PibStore, devanagari_share, fetch_feed, parse_feed  # noqa: E402


def manual_item(title: str, link: str, summary: str, published: str | None) -> dict:
    info = domain_info(link)
    if not (info["valid_host"] and info["registered"] == "pib.gov.in" and link.startswith("https://")):
        raise SystemExit(f"refused: {link} is not an https link on pib.gov.in")
    prid = PRID_RE.search(link)
    return {"title": title.strip(), "link": link.strip(), "prid": int(prid.group(1)) if prid else None,
            "published": published, "first_seen": None, "summary": summary.strip()[:1000], "feed": "manual",
            "language": "hi" if devanagari_share(title) > 0.5 else "en"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-file", nargs="+", metavar="XML", help="RSS files saved from a browser")
    ap.add_argument("--add", action="store_true", help="add one release by hand")
    ap.add_argument("--title")
    ap.add_argument("--link")
    ap.add_argument("--summary", default="")
    ap.add_argument("--published", default=None, help="YYYY-MM-DD, as shown on the release page")
    ap.add_argument("--set-date", action="store_true", help="set the publication date of an existing release")
    ap.add_argument("--prid", type=int)
    ap.add_argument("--copy-local-to-mongo", action="store_true")
    args = ap.parse_args()
    from satyapan.storage import open_store
    backend = open_store()
    if backend.note:
        print(backend.note)
    store = backend.pib_store()
    if args.copy_local_to_mongo:
        if backend.kind != "mongo":
            raise SystemExit("MONGODB_URI is not set or MongoDB is unreachable")
        local = PibStore(get_settings().data_dir / "pib_releases.jsonl").load()
        print(f"copied {store.add(local)} of {len(local)} local releases to MongoDB")
    elif args.set_date:
        if not (args.prid and args.published):
            raise SystemExit("--set-date needs --prid and --published YYYY-MM-DD")
        print("updated" if store.set_published(args.prid, args.published) else "no release with that PRID")
    elif args.add:
        if not (args.title and args.link):
            raise SystemExit("--add needs --title and --link")
        print(f"added {store.add([manual_item(args.title, args.link, args.summary, args.published)])} release")
    elif args.from_file:
        for f in args.from_file:
            try:
                items = parse_feed(Path(f).expanduser().read_bytes(), f"file:{Path(f).name}")
            except ToolError as err:
                print(f"{f}: {err.message}. Is it the RSS XML, not an error page?")
                continue
            items = [i for i in items if domain_info(i["link"])["registered"] == "pib.gov.in"]
            langs = sorted({i["language"] for i in items})
            print(f"{f}: {len(items)} PIB items, languages {langs}, new {store.add(items)}")
    else:
        client = ApiClient()
        for name in FEEDS:
            try:
                items, ms = fetch_feed(client, name)
            except ToolError as err:
                print(f"{name}: {err.status.value} {err.message[:160]}")
                continue
            langs = {i["language"] for i in items}
            print(f"{name}: {len(items)} items in {ms:.0f} ms, languages {sorted(langs)}, new {store.add(items)}")
    print(f"store now holds {len(store.load())} releases ({backend.kind}: {store.path or 'source_documents'})")


if __name__ == "__main__":
    main()
