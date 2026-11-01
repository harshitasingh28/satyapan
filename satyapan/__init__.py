"""Satyapan: evidence-gated verification of government-related claims and media.

Design rule: code decides verdicts from retrieved evidence. Language models may
extract claims or rephrase explanations, but every statement must cite stored
evidence, and the citation validator removes anything it cannot trace.
"""

__version__ = "0.2.0"
