"""Citation validation (module 11).

Every statement in a report must:
  1. cite at least one evidence id that exists,
  2. cite only evidence whose stance fits the verdict it explains,
  3. mention no number or URL that is absent from the cited evidence,
  4. use no verdict word that disagrees with the verdict ("genuine", "safe" in a FAKE
     report, "fake", "scam" in a GENUINE report, either kind in an UNVERIFIED report)
     unless that exact word is in the cited evidence (a fact-check rating "False", say),
  5. stay close to the cited evidence: at least 60% of its content words must appear in it.
Rules 3 to 5 are what stop an LLM rewrite from adding figures, links, conclusions or
claims that were never retrieved. Deterministic template statements are copied from the
evidence, so they always pass. Rule 5 is lexical: an LLM rewrite into Hindi or Telugu of
English evidence fails it, and the report then falls back to the English templates.
"""
from __future__ import annotations

import json
import re
import string

from satyapan.models import Evidence, Statement

NUMBER_RE = re.compile(r"\d[\d,.]*\d|\d")
URL_RE = re.compile(r"https?://[^\s)\]]+")
POSITIVE_WORDS = {"genuine", "authentic", "legitimate", "legit", "real", "true", "correct", "accurate", "verified",
                  "safe", "official", "confirmed", "सही", "असली", "सच", "सत्य", "सुरक्षित", "నిజం", "నిజమైన", "సురక్షితం"}
NEGATIVE_WORDS = {"fake", "false", "hoax", "scam", "fraud", "fraudulent", "misleading", "phishing", "untrue", "bogus",
                  "फर्जी", "फ़र्ज़ी", "झूठ", "झूठा", "गलत", "धोखा", "फेक", "నకిలీ", "అబద్ధం", "మోసం"}
FORBIDDEN = {"FAKE": POSITIVE_WORDS, "GENUINE": NEGATIVE_WORDS}
STOPWORDS = {"this", "that", "with", "from", "have", "been", "were", "does", "they", "their", "there", "which",
             "what", "when", "will", "would", "should", "could", "about", "into", "your", "more", "also", "only",
             "than", "then", "them", "these", "those", "such", "very", "just", "over", "under", "after", "before",
             "because", "while", "where", "being", "other", "some", "here", "said", "says", "shows", "show"}
MIN_OVERLAP = 0.6
PUNCT = string.punctuation + "।॥“”‘’…"


def _evidence_text(e: Evidence) -> str:
    return " ".join([e.source_name or "", e.source_url or "", e.established, e.quote or "", json.dumps(e.data, default=str,
                                                                                      ensure_ascii=False)])


def _words(text: str) -> list[str]:
    return [w.strip(PUNCT) for w in URL_RE.sub(" ", text).lower().split() if w.strip(PUNCT)]


def verdict_word_problems(text: str, corpus_lower: str, verdict: str) -> list[str]:
    forbidden = FORBIDDEN.get(verdict, POSITIVE_WORDS | NEGATIVE_WORDS)
    return [w for w in _words(text) if w in forbidden and not re.search(rf"(?<!\w){re.escape(w)}(?!\w)", corpus_lower)]


def overlap(text: str, corpus_lower: str) -> float:
    content = [w for w in _words(text) if len(w) >= 4 and w not in STOPWORDS and not NUMBER_RE.fullmatch(w)]
    if not content:
        return 1.0
    return sum(w in corpus_lower for w in content) / len(content)


def validate(statements: list[Statement], evidence: list[Evidence], verdict: str) -> tuple[list[Statement], list[dict]]:
    by_id = {e.id: e for e in evidence}
    allowed = {"FAKE": {"contradicts"}, "GENUINE": {"supports"}}.get(verdict, {"contradicts", "supports", "neutral"})
    kept, problems = [], []
    for st in statements:
        cited = [by_id[i] for i in st.evidence_ids if i in by_id]
        missing = [i for i in st.evidence_ids if i not in by_id]
        if not cited:
            problems.append({"statement": st.text, "problem": "no valid citation", "missing": missing})
            continue
        if missing:
            problems.append({"statement": st.text, "problem": "unknown evidence ids", "missing": missing})
            continue
        if not any(e.stance in allowed for e in cited):
            problems.append({"statement": st.text, "problem": f"cited evidence does not support a {verdict} verdict"})
            continue
        corpus = " ".join(_evidence_text(e) for e in cited)
        digits_corpus = corpus.replace(",", "")
        bad_numbers = [n for n in NUMBER_RE.findall(st.text) if n.replace(",", "") not in digits_corpus]
        bad_urls = [u for u in URL_RE.findall(st.text) if u.rstrip(".,") not in corpus]
        if bad_numbers or bad_urls:
            problems.append({"statement": st.text, "problem": "content not found in cited evidence",
                             "numbers": bad_numbers, "urls": bad_urls})
            continue
        corpus_lower = corpus.lower()
        bad_words = verdict_word_problems(st.text, corpus_lower, verdict)
        if bad_words:
            problems.append({"statement": st.text, "problem": f"wording disagrees with the {verdict} verdict",
                             "words": bad_words})
            continue
        ratio = overlap(st.text, corpus_lower)
        if ratio < MIN_OVERLAP:
            problems.append({"statement": st.text, "problem": "statement is not grounded in the cited evidence",
                             "overlap": round(ratio, 2)})
            continue
        kept.append(st)
    return kept, problems
