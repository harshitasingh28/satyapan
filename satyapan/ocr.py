"""OCR for screenshots, using the local Tesseract binary (no upload to anyone).

macOS: brew install tesseract tesseract-lang   (includes hin and tel)
Accuracy on real WhatsApp screenshots is unmeasured until the dataset run.

Safeguards added in the audit round:
  * Large images are downscaled before OCR (phone screenshots keep their full size).
  * Tesseract runs single-threaded (OMP_THREAD_LIMIT=1). With several jobs at once,
    its default multithreading oversubscribed the CPU and hit the timeout.
  * A line-level confidence gate: only text lines whose mean word confidence is at
    least GOOD_LINE_CONF are kept, and the result is discarded if fewer than
    MIN_GOOD_WORDS confident words remain. Junk from photo regions is dropped while a
    caption next to a photo survives. The values are a first guess, NOT tuned on any
    evaluation data. Real WhatsApp-screenshot accuracy is still unmeasured.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

MAX_OCR_SIDE = 2600        # px, long side. A 1080x2400 phone screenshot is not resized.
GOOD_LINE_CONF = 60.0
MIN_GOOD_WORDS = 3
GOOD_WORD_CONF = 60.0


@lru_cache(maxsize=1)
def available_languages() -> set[str]:
    if not shutil.which("tesseract"):
        return set()
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=False)
    lines = (out.stdout + out.stderr).splitlines()
    return {ln.strip() for ln in lines[1:] if ln.strip() and " " not in ln.strip()}


def _prepared_copy(path: Path) -> Path | None:
    """A downscaled PNG copy if the image is larger than MAX_OCR_SIDE, else None."""
    with Image.open(path) as im:
        if max(im.size) <= MAX_OCR_SIDE:
            return None
        im.draft("RGB", (MAX_OCR_SIDE, MAX_OCR_SIDE))   # JPEG: decode at reduced scale, saves memory
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE))
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="satyapan_ocr_")
        os.close(fd)
        im.save(tmp, "PNG")
        return Path(tmp)


def _parse_tsv(tsv: str) -> tuple[str, float, int]:
    """Rebuild text from Tesseract TSV, keeping confident lines only.

    Returns (kept text, mean confidence over all words, confident words in kept lines)."""
    lines: dict[tuple, list[tuple[str, float]]] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf >= 0:
            lines.setdefault((cols[2], cols[3], cols[4]), []).append((cols[11].strip(), conf))
    all_confs = [c for words in lines.values() for _, c in words]
    kept, good = [], 0
    for words in lines.values():
        if sum(c for _, c in words) / len(words) >= GOOD_LINE_CONF:
            kept.append(" ".join(w for w, _ in words))
            good += sum(1 for w, c in words if c >= GOOD_WORD_CONF and sum(ch.isalnum() for ch in w) >= 2)
    return "\n".join(kept), (sum(all_confs) / len(all_confs) if all_confs else 0.0), good


def ocr_image(path: Path, wanted: str = "eng+hin+tel", timeout: float = 30.0) -> dict:
    langs = [lang for lang in wanted.split("+") if lang in available_languages()]
    if not langs:
        return {"ok": False, "text": "", "langs": [], "ms": 0.0,
                "error": "tesseract or language data missing (brew install tesseract tesseract-lang)"}
    start = time.perf_counter()
    small = _prepared_copy(path)
    try:
        out = subprocess.run(["tesseract", str(small or path), "stdout", "-l", "+".join(langs), "--psm", "6", "-c", "tessedit_create_tsv=1"],
                             capture_output=True, text=True, timeout=timeout, check=False,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    finally:
        if small:
            small.unlink(missing_ok=True)
    ms = round((time.perf_counter() - start) * 1000, 1)
    if out.returncode != 0:
        return {"ok": False, "text": "", "langs": langs, "ms": ms, "error": out.stderr.strip()[:200]}
    text, mean_conf, good = _parse_tsv(out.stdout)
    low = good < MIN_GOOD_WORDS
    return {"ok": True, "text": "" if low else text.strip(), "langs": langs, "ms": ms, "error": None,
            "mean_conf": round(mean_conf, 1), "confident_words": good, "low_confidence": low,
            "downscaled": small is not None}
