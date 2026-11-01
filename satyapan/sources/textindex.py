"""Small BM25 index that tokenises Hindi and Telugu correctly.

Python's \\w splits Devanagari words at vowel signs (they are combining marks),
so tokens are split on whitespace and punctuation instead.
"""
from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[^\s.,;:!?\"'()\[\]{}<>|।॥\-–—/\\#*@_=+~`]+")
STOP = {"the", "a", "an", "of", "to", "in", "and", "for", "on", "is", "are", "be", "will", "with", "by",
        "this", "that", "from", "at", "as", "it", "its", "all", "has", "have", "was", "were",
        "का", "की", "के", "में", "है", "हैं", "को", "से", "और", "पर", "यह", "एक", "भी", "लिए"}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[dict], field: str = "text", k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1, self.b = k1, b
        self.toks = [tokenize(d.get(field, "")) for d in docs]
        self.avgdl = sum(map(len, self.toks)) / len(self.toks) if self.toks else 0.0
        df = Counter(t for toks in self.toks for t in set(toks))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(toks) for toks in self.toks]

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = tokenize(query)
        if not q or not self.docs:
            return []
        results = []
        for i, tf in enumerate(self.tf):
            dl = len(self.toks[i]) or 1
            score = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    score += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                overlap = len(set(q) & set(self.toks[i])) / len(set(q))
                results.append({"doc": self.docs[i], "bm25": round(score, 3), "query_overlap": round(overlap, 3)})
        return sorted(results, key=lambda r: -r["bm25"])[:k]
