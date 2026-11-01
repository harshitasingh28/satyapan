"""Module 1: claim extraction.

Deterministic first. It finds URLs, Indian phone numbers, rupee amounts, calls to
action and government/scheme mentions in English, Hindi and Telugu, then picks
the most check-worthy sentence. An LLM can add structured extraction later
(satyapan/llm.py), but only claims it can quote from the source text survive.
"""
from __future__ import annotations

import re
import unicodedata

from satyapan.models import Claim

TLDS = r"(?:in|com|org|net|info|xyz|top|online|site|shop|co|live|club|link|cc|me|io|app|biz|vip|icu|buzz)"
URL_RE = re.compile(
    r"(?i)\b((?:https?://|www\.)[^\s<>\"'()।॥]+|(?:[a-z0-9-]+\.)+" + TLDS + r"(?:/[^\s<>\"'()।॥]*)?)(?![\w.])")
PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
AMOUNT_RE = re.compile(
    r"(?i)(?:₹|\brs\.?|\binr|rupees?|रुपये|रुपए|रु\.)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:lakh|crore|लाख|करोड़))?"
    r"|\d[\d,]*(?:\.\d+)?\s?(?:₹|rupees?|रुपये|रुपए|lakh|crore|लाख|करोड़|రూపాయలు)")
DATE_RE = re.compile(r"(?i)\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b")

GOV_ENTITIES = {
    "en": ["prime minister", "pradhan mantri", "pm modi", "pm kisan", "pm-kisan", "modi", "pmo",
           "government of india", "govt", "government",
           "ministry", "rbi", "reserve bank", "uidai", "aadhaar", "pib", "election commission",
           "income tax", "epfo", "railway", "irctc", "npci", "trai", "police", "cbi"],
    "hi": ["प्रधानमंत्री", "मोदी", "सरकार", "मंत्रालय", "आधार", "रिज़र्व बैंक", "रेलवे", "पुलिस", "चुनाव आयोग"],
    "te": ["ప్రధాని", "మోదీ", "ప్రభుత్వం", "మంత్రిత్వ", "ఆధార్", "రైల్వే", "పోలీస్"],
}
SCHEME_WORDS = {
    "en": ["yojana", "scheme", "subsidy", "free", "pension", "loan waiver", "ration", "laptop",
           "recharge", "scholarship", "allowance", "bonus", "lottery", "reward"],
    "hi": ["योजना", "मुफ्त", "मुफ़्त", "सब्सिडी", "पेंशन", "राशन", "लैपटॉप", "रिचार्ज", "छात्रवृत्ति", "इनाम"],
    "te": ["పథకం", "ఉచిత", "సబ్సిడీ", "పెన్షన్", "రేషన్", "బహుమతి"],
}
CTA_WORDS = {
    "en": ["click", "apply now", "register", "forward", "share", "last date", "limited time",
           "link below", "claim now", "download", "kyc", "otp", "hurry", "today only"],
    "hi": ["क्लिक", "शेयर", "फॉरवर्ड", "आवेदन", "रजिस्टर", "अंतिम तिथि", "लिंक", "जल्दी"],
    "te": ["క్లిక్", "షేర్", "దరఖాస్తు", "లింక్", "రిజిస్టర్"],
}
SENTENCE_SPLIT = re.compile(r"(?<=[.!?।॥])\s+|\n+")


def normalize(text: str) -> str:
    """NFC, drop emoji and pictographs (category So), collapse whitespace. URL characters survive."""
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "So")
    return re.sub(r"\s+", " ", text).strip()


def detect_language(text: str) -> str:
    deva = sum("ऀ" <= c <= "ॿ" for c in text)
    telu = sum("ఀ" <= c <= "౿" for c in text)
    latin = sum(c.isascii() and c.isalpha() for c in text)
    total = deva + telu + latin
    if total == 0:
        return "unknown"
    shares = {"hi": deva / total, "te": telu / total, "en": latin / total}
    best = max(shares, key=shares.get)
    return best if shares[best] >= 0.7 else "mixed"


MULTIPLIERS = {"lakh": 1e5, "लाख": 1e5, "crore": 1e7, "करोड़": 1e7}
NUMBER_RE = re.compile(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?(?![\d])\s?(lakh|crore|लाख|करोड़)?", re.I)


def amount_value(amount: str) -> float | None:
    """'Rs 2,000' -> 2000.0, '2 lakh' -> 200000.0. None if no number."""
    m = NUMBER_RE.search(amount)
    if not m:
        return None
    digits = re.match(r"\d[\d,]*(?:\.\d+)?", m.group(0)).group(0).replace(",", "")
    return float(digits) * MULTIPLIERS.get((m.group(1) or "").lower(), 1)


def number_values(text: str) -> set[float]:
    """Every whole number in a text, with lakh/crore applied. Used to compare amounts exactly."""
    out = set()
    for m in NUMBER_RE.finditer(text):
        digits = re.match(r"\d[\d,]*(?:\.\d+)?", m.group(0)).group(0).replace(",", "")
        out.add(float(digits) * MULTIPLIERS.get((m.group(1) or "").lower(), 1))
    return out


MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                          "nov", "dec"))}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_FORMS = [
    (re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON), lambda m: (int(m[1]), MONTHS[m[2].lower()])),
    (re.compile(r"(?i)\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b"), lambda m: (int(m[2]), MONTHS[m[1].lower()])),
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}\b"), lambda m: (int(m[1]), int(m[2]))),   # Indian D/M/Y
]


def date_values(text: str) -> set[tuple[int, int]]:
    """(day, month) pairs for English and numeric dates. Hindi and Telugu month names are NOT parsed."""
    out = set()
    for pattern, conv in DATE_FORMS:
        for m in pattern.finditer(text):
            day, month = conv(m)
            if 1 <= day <= 31 and 1 <= month <= 12:
                out.add((day, month))
    return out


def _find(words: dict[str, list[str]], text: str) -> list[str]:
    low = text.lower()
    return sorted({w for lang in words.values() for w in lang if w in low})


def extract_urls(text: str) -> list[str]:
    urls = []
    for m in URL_RE.findall(text):
        url = m.rstrip(".,;:!?)]}'\"।॥…。，、！？")
        if not url.lower().startswith(("http://", "https://")):
            url = "http://" + url
        urls.append(url)
    return list(dict.fromkeys(urls))


def score_sentence(sentence: str) -> tuple[float, dict]:
    feats = {
        "entities": _find(GOV_ENTITIES, sentence),
        "schemes": _find(SCHEME_WORDS, sentence),
        "ctas": _find(CTA_WORDS, sentence),
        "amounts": AMOUNT_RE.findall(sentence),
        "urls": extract_urls(sentence),
        "phones": PHONE_RE.findall(sentence),
        "dates": DATE_RE.findall(sentence),
    }
    score = (2.0 * bool(feats["entities"]) + 1.5 * bool(feats["schemes"]) + 1.0 * bool(feats["amounts"])
             + 1.0 * bool(feats["ctas"]) + 0.5 * bool(feats["urls"] or feats["phones"])
             + 0.5 * bool(feats["dates"]))
    if len(sentence.split()) < 4:
        score -= 1.0
    return score, feats


def extract_claims(text: str, source: str = "user_text", max_claims: int = 3) -> list[Claim]:
    text = normalize(text)
    if not text:
        return []
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]
    scored = []
    for s in sentences:
        score, feats = score_sentence(s)
        scored.append((score, s, feats))
    # The whole message is also a candidate: forwards often spread one claim over several lines.
    whole_score, whole_feats = score_sentence(text)
    if len(sentences) > 1:
        scored.append((whole_score - 0.25, text, whole_feats))
    scored.sort(key=lambda x: -x[0])
    claims, seen = [], set()
    for score, sentence, feats in scored:
        clean = re.sub(r"\s+", " ", URL_RE.sub("", sentence)).strip(" -:|")
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        claims.append(Claim(
            id=f"C{len(claims) + 1}", text=clean, source=source, language=detect_language(clean),
            entities=feats["entities"] + feats["schemes"], amounts=feats["amounts"],
            urls=extract_urls(text) if not claims else feats["urls"],
            phones=PHONE_RE.findall(text) if not claims else feats["phones"],
            calls_to_action=feats["ctas"], checkworthiness=round(score, 2)))
        if len(claims) >= max_claims:
            break
    return claims
