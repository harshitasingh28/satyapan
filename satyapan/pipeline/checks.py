"""Deterministic checks used by the evidence gate. No model calls.

* PIB release identity: a pib.gov.in link with PRID=<n> names one specific release. If that
  release is in the index it must be the release that matched the claim (probe P3: a real title
  pasted with the link of a different real release was GENUINE).
* Outdated context: a message that presents news as new ("today", "breaking", "आज", "ఈరోజు")
  while the matched release was published long ago (probe P5) cannot be GENUINE.
* Fact compatibility: every amount, date and standalone number in the claim must appear in the
  evidence text. Used before any AI-assisted match may count.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from satyapan.claims import URL_RE, date_values, number_values
from satyapan.sources.pib import prid_of

OUTDATED_DAYS = 30

RECENCY = {
    "en": [r"\btoday\b", r"\btonight\b", r"\bbreaking\b", r"\bjust (?:now|in|announced)\b", r"\bfrom tomorrow\b",
           r"\bthis (?:morning|evening)\b", r"\bnew(?:ly)? announced\b", r"\blatest\b", r"\burgent\b"],
    "hi": ["आज", "अभी", "ब्रेकिंग", "ताज़ा", "ताजा", "कल से", "तत्काल"],
    "te": ["ఈరోజు", "నేడు", "ఇప్పుడే", "బ్రేకింగ్", "తాజా", "రేపటి నుంచి", "రేపటి నుండి"],
}
_RECENCY_RE = [re.compile(p, re.I) for p in RECENCY["en"]] + [re.compile(re.escape(p)) for p in RECENCY["hi"] + RECENCY["te"]]


def recency_phrases(text: str) -> list[str]:
    found = []
    for rx in _RECENCY_RE:
        m = rx.search(text or "")
        if m:
            found.append(m.group(0))
    return found


def parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    for fmt in (None, "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00")) if fmt is None else datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def outdated(message: str, published, now: datetime | None = None, days: int = OUTDATED_DAYS) -> dict:
    """{'flag': bool, 'phrases': [...], 'age_days': int | None, 'published': str | None}"""
    phrases = recency_phrases(message)
    pub = parse_date(published)
    age = None
    if pub is not None:
        age = ((now or datetime.now(timezone.utc)) - pub).days
    return {"flag": bool(phrases) and age is not None and age > days, "phrases": phrases, "age_days": age,
            "published": pub.isoformat(timespec="seconds") if pub else None, "date_known": pub is not None}


def message_prids(links: list[str]) -> list[int]:
    out = []
    for u in links:
        host = (re.sub(r"^https?://", "", u.lower()).split("/")[0])
        if host.endswith("pib.gov.in"):
            p = prid_of(u)
            if p is not None and p not in out:
                out.append(p)
    return out


def prid_check(links: list[str], matched_link: str | None, store) -> dict:
    """{'status': 'none' | 'matches' | 'mismatch' | 'unknown', 'prids': [...], 'linked_title': str | None}

    none      the message has no PIB release link
    matches   the linked release is the matched release
    mismatch  the link names a DIFFERENT release that we hold (P3)
    unknown   the linked release is not in our index, so the link could not be checked
    """
    prids = message_prids(links)
    if not prids:
        return {"status": "none", "prids": [], "linked_title": None}
    matched = prid_of(matched_link)
    if matched is not None and matched in prids and len(prids) == 1:
        return {"status": "matches", "prids": prids, "linked_title": None}
    for p in prids:
        doc = store.by_prid(p) if store is not None else None
        if doc is not None and p != matched:
            return {"status": "mismatch", "prids": prids, "linked_title": doc.get("title", "")[:160]}
    return {"status": "unknown", "prids": prids, "linked_title": None}


def facts_compatible(claim_text: str, evidence_text: str) -> dict:
    """Every number (amounts with lakh and crore applied) and every date in the claim must also
    appear in the evidence. URLs are ignored, so PRID digits do not count as claimed numbers."""
    claim_wo_urls = URL_RE.sub(" ", claim_text or "")
    ev = URL_RE.sub(" ", evidence_text or "")
    missing_numbers = sorted(number_values(claim_wo_urls) - number_values(ev))
    missing_dates = sorted(date_values(claim_wo_urls) - date_values(ev))
    return {"ok": not missing_numbers and not missing_dates,
            "missing_numbers": [f"{n:.0f}" if float(n).is_integer() else str(n) for n in missing_numbers[:5]],
            "missing_dates": [f"{d}/{m}" for d, m in missing_dates[:5]]}


def facts_conflict(claim_text: str, other_text: str) -> dict:
    """Looser than facts_compatible, for matching a message to a reviewed claim: a conflict only
    when both texts state numbers (or dates) and they share none."""
    a, b = URL_RE.sub(" ", claim_text or ""), URL_RE.sub(" ", other_text or "")
    na, nb = number_values(a), number_values(b)
    da, db = date_values(a), date_values(b)
    num_conflict = bool(na and nb and not (na & nb))
    date_conflict = bool(da and db and not (da & db))
    return {"conflict": num_conflict or date_conflict, "numbers_conflict": num_conflict, "dates_conflict": date_conflict}
