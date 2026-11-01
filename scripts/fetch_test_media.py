"""Download the public test media used by the local tests. Nothing here is evaluation data.

  C2PA fixtures      contentauth/c2pa-python tests/fixtures (C.jpg signed with a test cert, A.jpg none)
  Speech and music   librosa/data (LibriSpeech speech clips and a Kevin MacLeod track, see that repo
                     for per-file attribution)
  Photos             scikit-image's bundled sample images (pip install scikit-image), licences in
                     skimage/data/README.txt
  OCR                Tesseract hin/tel language data (tessdata_fast) and Noto Sans fonts (OFL)

Run from the project root: python scripts/fetch_test_media.py
"""
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "tests" / "media"
RAW = "https://raw.githubusercontent.com/"
FILES = {
    "c2pa/C.jpg": "contentauth/c2pa-python/main/tests/fixtures/C.jpg",
    "c2pa/A.jpg": "contentauth/c2pa-python/main/tests/fixtures/A.jpg",
    "audio/speech_a.ogg": "librosa/data/main/audio/198-209-0000.hq.ogg",
    "audio/speech_b.ogg": "librosa/data/main/audio/5703-47212-0000.ogg",
    "audio/music.ogg": "librosa/data/main/audio/Kevin_MacLeod_-_Vibe_Ace.hq.ogg",
    "tessdata/hin.traineddata": "tesseract-ocr/tessdata_fast/main/hin.traineddata",
    "tessdata/tel.traineddata": "tesseract-ocr/tessdata_fast/main/tel.traineddata",
    "tessdata/eng.traineddata": "tesseract-ocr/tessdata_fast/main/eng.traineddata",
    "fonts/NotoSansDevanagari.ttf": "google/fonts/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    "fonts/NotoSansTelugu.ttf": "google/fonts/main/ofl/notosanstelugu/NotoSansTelugu%5Bwdth%2Cwght%5D.ttf",
}
PHOTOS = ["astronaut.png", "camera.png", "chelsea.png", "coffee.png", "hubble_deep_field.jpg",
          "motorcycle_left.png", "rocket.jpg", "retina.jpg", "coins.png", "moon.png", "page.png",
          "brick.png", "grass.png", "gravel.png", "ihc.png", "immunohistochemistry.png", "cell.png", "clock_motion.png"]


def main() -> None:
    ok = True
    for rel, src in FILES.items():
        target = MEDIA / rel
        if target.exists() and target.stat().st_size > 100:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(RAW + src, target)
            print(f"downloaded {rel} ({target.stat().st_size} bytes)")
        except OSError as exc:
            ok = False
            print(f"FAILED {rel}: {exc}")
    try:
        import skimage
    except ImportError:
        print("scikit-image missing: pip install -r requirements-dev.txt")
        sys.exit(1)
    data = Path(skimage.__file__).parent / "data"
    (MEDIA / "images").mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in PHOTOS:
        if (data / name).exists():
            shutil.copy(data / name, MEDIA / "images" / name)
            copied += 1
    if (data / "README.txt").exists():
        shutil.copy(data / "README.txt", MEDIA / "images" / "LICENSES_scikit-image.txt")
    print(f"copied {copied} sample photos")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
