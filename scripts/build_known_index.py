"""Build the known-debunk indexes from a hand-curated CSV.

Input data/known_debunks.csv (copy templates/known_debunks_template.csv). One row per debunk:
  id, claim_text, debunk_url, publisher, date, media_file (optional, under data/known_media/)
Sources: fact-check articles found via the Google Fact Check API or the fact-checkers'
own sites, and PIB debunks recorded by hand with a link. Do NOT bulk-download from
Telegram (its terms forbid AI use of platform data).
Only hashes, keypoint descriptors and fingerprints are stored, plus the link.

Usage: python scripts/build_known_index.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.media.audio import AudioIndex  # noqa: E402
from satyapan.media.image_index import ImageIndex  # noqa: E402
from satyapan.security.uploads import validate_upload  # noqa: E402


def main() -> None:
    d = get_settings().data_dir
    rows = list(csv.DictReader(open(d / "known_debunks.csv", encoding="utf-8")))
    images, audio, claims = ImageIndex(), AudioIndex(), []
    for r in rows:
        meta = {"source_url": r["debunk_url"], "publisher": r["publisher"], "date": r["date"]}
        if r["claim_text"].strip():
            claims.append({"text": r["claim_text"].strip(), "url": r["debunk_url"], **meta})
        if r.get("media_file", "").strip():
            path = d / "known_media" / r["media_file"]
            info = validate_upload(path, path.name)
            if not info.ok:
                print(f"{r['id']}: skipped media ({info.errors})")
            elif info.kind == "image":
                images.add(r["id"], path, **meta)
            elif info.kind == "audio":
                audio.add(r["id"], path, **meta)
            else:
                print(f"{r['id']}: video originals are indexed by their keyframes, extract them first")
    (d / "known_claims.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims),
                                          encoding="utf-8")
    images.save(d / "image_index")
    audio.save(d / "audio_index")        # before the audit fix the audio index was built and then lost
    print(f"{len(claims)} known claims, {len(images.items)} images, {len(audio.meta)} audio clips indexed")


if __name__ == "__main__":
    main()
