"""Offline link analysis: parsing, punycode and homoglyphs, lookalike scoring, shorteners."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

from rapidfuzz import fuzz

from satyapan.security.ssrf import normalise_url, validate_url
from satyapan.sources.official import OFFICIAL_SUFFIXES, domain_info

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "rb.gy", "is.gd", "ow.ly",
              "shorturl.at", "tiny.cc", "rebrand.ly", "t.ly", "s.id", "v.gd"}
SCHEME_TOKENS = ("yojana", "kisan", "pmkisan", "pmay", "sarkar", "scheme", "subsidy", "aadhaar", "aadhar",
                 "ration", "free", "lucky", "reward", "kyc", "refund", "gift")
# A small map of characters that look like Latin letters. Not exhaustive.
CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ԁ": "d",
    "ɡ": "g", "ո": "n", "ս": "u", "ν": "v", "ο": "o", "α": "a", "ρ": "p", "ι": "i", "κ": "k", "τ": "t",
    "0": "o", "1": "l",
})


def unicode_host(host: str) -> str:
    try:
        return host.encode("ascii").decode("idna") if "xn--" in host else host
    except UnicodeError:
        return host


def skeleton(label: str) -> str:
    return unicode_host(label).lower().translate(CONFUSABLES).replace("-", "")


GENERIC_LABELS = {"www", "india", "gov", "govt", "mail", "online", "portal"}
REDIRECT_KEYS = {"url", "u", "redirect", "redirect_url", "redirect_uri", "redirecturl", "next", "target", "dest",
                 "destination", "goto", "link", "out", "to", "return", "returnurl", "return_url", "continue", "r", "q"}
DOMAIN_LIKE = re.compile(r"(?i)^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,24}(/|$)")


def embedded_targets(url: str) -> list[str]:
    """Other URLs carried inside a link (open-redirect style): ?url=https://evil.top, /out/https://evil.top.

    Query values are percent-decoded. A value counts if it starts with http(s):// or www., or if
    its key is a typical redirect key and the value looks like a domain."""
    try:
        parts = urlsplit(normalise_url(url))
    except ValueError:
        return []
    out = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        v = value.strip()
        if re.match(r"(?i)^(https?://|www\.)", v) or (key.lower() in REDIRECT_KEYS and DOMAIN_LIKE.match(v)):
            out.append(v if "://" in v else "http://" + v)
    m = re.search(r"(?i)/(https?:/{1,2}[^\s]+)", parts.path)
    if m:
        out.append(re.sub(r"(?i)^(https?):/{1,2}", r"\1://", m.group(1)))
    return list(dict.fromkeys(out))


def _naive_host_info(original: str) -> dict | None:
    """The host as a backslash-unaware parser (and many readers) would see it."""
    try:
        host = urlsplit(original.strip()).hostname or ""
    except ValueError:
        return None
    return domain_info(host) if host else None


def official_labels(official_domains: set[str]) -> set[str]:
    """First labels of official domains (pmkisan, uidai, pib ...), used to spot them inside other hosts."""
    return {d.split(".")[0] for d in official_domains | {"india.gov.in", "pib.gov.in"}
            if len(d.split(".")[0]) >= 3 and d.split(".")[0] not in GENERIC_LABELS}


def analyse_url(url: str, official_domains: set[str]) -> dict:
    """Offline facts and flags for one link.

    Impersonation flags (used as STRONG evidence when a message invokes the government):
      official_name_inside_other_domain  uidai.gov.in.verify-kyc.top
      lookalike_of_official_domain       pmkisam.in, xn--pb-lmc.in (Cyrillic i)
      official_label_in_host             pmkisan-gov.top, pib-relief.top (an official name as a whole label part)
      official_name_in_userinfo          https://pib.gov.in@evil.top/ and http://x.com\\@pib.gov.in/
    Weaker signals (MODERATE at most): gov_token_outside_gov_in, official_label_fragment_in_host,
    punycode_host. Foreign government domains (state.gov, gov.uk) are flagged as such and are
    never treated as impersonation.
    """
    original = url
    url = normalise_url(url)
    check = validate_url(url, resolve=False)
    info = domain_info(url)
    host_u = unicode_host(info["host"])
    flags: list[str] = []
    if not check.ok:
        flags.append("unsafe_or_local_target")
    if not info["valid_host"]:
        flags.append("invalid_hostname")
    if url.lower().startswith("http://"):
        flags.append("not_https")
    if "xn--" in info["host"]:
        flags.append("punycode_host")
    if any(ord(c) > 127 for c in host_u):
        flags.append("non_ascii_host")
    if info["registered"] in SHORTENERS:
        flags.append("url_shortener")
    if "\\" in original:
        flags.append("backslash_in_url")
    stripped = original.strip()
    if any(unicodedata.category(ch) == "Cf" or "\uff00" <= ch <= "\uffef" or ch == "\u3002" for ch in stripped):
        flags.append("hidden_or_fullwidth_characters")
    targets = [t for t in embedded_targets(url) if domain_info(t)["registered"] != info["registered"]]
    if targets:
        flags.append("redirects_to_other_site")
    allowlisted = info["valid_host"] and info["registered"] in official_domains
    official = info["official_suffix"] or allowlisted
    foreign_gov = (not official) and ".gov." in f".{info['suffix']}."
    if foreign_gov:
        flags.append("foreign_government_domain")
    naive = _naive_host_info(original) if "\\" in original else None
    if info["userinfo"]:
        flags.append("userinfo_in_url")
    closest, similarity = None, 0.0
    if not official and info["valid_host"]:
        labels = official_labels(official_domains)
        label = skeleton(info["registered"].split(".")[0])
        for dom in official_domains | {"india.gov.in", "pib.gov.in"}:
            score = fuzz.ratio(label, skeleton(dom.split(".")[0]))
            if score > similarity:
                closest, similarity = dom, score
        name_part = info["host"][: -len(info["suffix"])] if info["suffix"] else info["host"]
        tokens = [t for t in re.split(r"[.\-_]+", name_part) if t]
        if "gov" in name_part and not foreign_gov:
            flags.append("gov_token_outside_gov_in")
        if any(dom in info["host"] and info["host"] != dom for dom in official_domains):
            flags.append("official_name_inside_other_domain")
        if similarity >= 85:
            flags.append("lookalike_of_official_domain")
        if any(t in labels for t in tokens):
            flags.append("official_label_in_host")
        elif any(lab in t for t in tokens for lab in labels if len(lab) >= 5):
            flags.append("official_label_fragment_in_host")
        if any(t in info["host"] for t in SCHEME_TOKENS):
            flags.append("scheme_or_reward_words")
        ui = info["userinfo"].lower()
        if ui and (any(d in ui for d in official_domains | OFFICIAL_SUFFIXES) or "gov" in ui):
            flags.append("official_name_in_userinfo")
        if naive and (naive["official_suffix"] or naive["registered"] in official_domains):
            flags.append("official_name_in_userinfo")   # x.com\@pib.gov.in reads as pib.gov.in, opens x.com
    return {"url": url, **info, "unicode_host": host_u, "official": official, "allowlisted": allowlisted,
            "closest_official": closest, "similarity": round(similarity, 1), "flags": list(dict.fromkeys(flags)),
            "embedded_targets": targets, "url_check": check.reason}
