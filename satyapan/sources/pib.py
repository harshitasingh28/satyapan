"""PIB press releases via PIB's own RSS feeds, stored locally and searched with BM25.

Feed list: https://www.pib.gov.in/ViewRss.aspx?reg=3&lang=1
Probed on 31 Oct 2026 through a summarising fetcher (not a raw HTTP test):
  * the documented English URL (Lang=1) returned HINDI titles,
  * the lowercase variant (lang=1&regid=3&reg=3) returned English titles,
  * items carry no pubDate, so we store the time we first saw each item.
The integration test checks the script of the titles to settle which URL is English.
Reuse (https://pib.gov.in/Content/102_2_Copyright-Policy.aspx): free, no prior approval,
reproduce accurately, never in a misleading context, acknowledge the source,
third-party material excluded. We store title, link and summary and always link back.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.sources.textindex import BM25

FEEDS = {
    "releases_en_documented": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "releases_en_variant": "https://www.pib.gov.in/RssMain.aspx?ModId=6&lang=1&regid=3&reg=3",
    "releases_hi": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3",
}
PRID_RE = re.compile(r"PRID=(\d+)", re.I)


def prid_of(link: str | None) -> int | None:
    m = PRID_RE.search(link or "")
    return int(m.group(1)) if m else None


def devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters) if letters else 0.0


def parse_feed(content: bytes, name: str) -> list[dict]:
    """RSS bytes to release records. Used for live fetches and for feeds saved from a browser."""
    feed = feedparser.parse(content)
    if not feed.entries:
        raise ToolError(ToolStatus.SERVICE_ERROR, "response had no RSS items")
    seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = []
    for e in feed.entries:
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        link = e.get("link") or ""
        prid = PRID_RE.search(link)
        title = (e.get("title") or "").strip()
        items.append({"title": title, "link": link, "prid": int(prid.group(1)) if prid else None,
                      "published": datetime(*parsed[:6], tzinfo=timezone.utc).isoformat() if parsed else None,
                      "first_seen": seen_at, "summary": (e.get("summary") or "")[:1000], "feed": name,
                      "language": "hi" if devanagari_share(title) > 0.5 else "en"})
    return items


def fetch_feed(client: ApiClient, name: str) -> tuple[list[dict], float]:
    try:
        resp, ms = client.request(f"pib_rss_{name}", "GET", FEEDS[name])
    except ToolError as err:
        if err.status == ToolStatus.AUTH_REQUIRED:
            # PIB needs no key. A 401 or 403 here means the server refused this client, which
            # is BLOCKED, not a missing credential. Observed on 31 Oct 2026 on a home network.
            raise ToolError(ToolStatus.BLOCKED, f"PIB refused the request (HTTP {err.http_status}). "
                            "No key is needed. Save the feed from a browser and run "
                            "scripts/ingest_pib.py --from-file", err.http_status) from err
        raise
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, f"HTTP {resp.status_code}", resp.status_code)
    return parse_feed(resp.content, name), ms


class PibStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._index: BM25 | None = None

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def add(self, items: list[dict]) -> int:
        seen = {d["link"] for d in self.load()}
        new = [i for i in items if i.get("link") and i["link"] not in seen]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for i in new:
                fh.write(json.dumps(i, ensure_ascii=False) + "\n")
        self._index = None
        return len(new)

    def set_published(self, prid: int, published: str, source: str = "page") -> bool:
        docs, hit = self.load(), False
        for d in docs:
            if (d.get("prid") or prid_of(d.get("link"))) == prid:
                d["published"], d["date_source"], hit = published, source, True
        if hit:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8")
            tmp.replace(self.path)
            self._index = None
        return hit

    def by_prid(self, prid: int) -> dict | None:
        for d in self.load():
            if (d.get("prid") or prid_of(d.get("link"))) == prid:
                return d
        return None

    def search(self, query: str, k: int = 5) -> list[dict]:
        if self._index is None:
            docs = [{**d, "text": f"{d['title']} {d.get('summary', '')}"} for d in self.load()]
            self._index = BM25(docs)
        return self._index.search(query, k)
