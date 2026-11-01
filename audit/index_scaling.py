"""How the known-media image index behaves as it grows (timing and recall).

The 22 held-out "known" images are indexed together with filler items (random crops of
other images, rotated and colour-shifted) to reach each index size. We query
transformed copies of the 22 known images and measure recall and query time.
ImageIndex.query verifies every item with ORB only while the index has <= 250 items.
Above that, ORB runs only on pHash candidates, which is expected to hurt crops and
screenshots. This script measures that instead of assuming it.
It also times audio fingerprinting of a 170 s clip.
Usage: python audit/index_scaling.py --heldout-dir DIR --dev-dir tests/media/images
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "audit"))
from image_eval import SETS, TRANSFORMS, load  # noqa: E402
from satyapan.media import image_index as ix  # noqa: E402

QUERY_TRANSFORMS = ["resize50", "centre_crop70", "offcentre_crop55_br", "screenshot_v2"]
SIZES = [22, 100, 250, 251, 400]


def fillers(sources: list[Path], n: int, seed: int = 7) -> list[Image.Image]:
    rnd = random.Random(seed)
    out = []
    while len(out) < n:
        im = load(rnd.choice(sources))
        w, h = im.size
        s = rnd.uniform(0.35, 0.7)
        x, y = rnd.randint(0, int(w * (1 - s))), rnd.randint(0, int(h * (1 - s)))
        c = im.crop((x, y, x + int(w * s), y + int(h * s))).rotate(rnd.choice([0, 90, 180, 270]), expand=True)
        c = ImageEnhance.Color(c).enhance(rnd.uniform(0.3, 1.7))
        out.append(c.resize((max(64, c.width), max(64, c.height))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout-dir", required=True)
    ap.add_argument("--dev-dir", required=True)
    ap.add_argument("--audio", default=str(ROOT / "tests" / "media" / "audio" / "music.ogg"))
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "index_scaling.json"))
    args = ap.parse_args()
    held = Path(args.heldout_dir)
    known = SETS["heldout"]["index"]
    filler_src = [p for p in Path(args.dev_dir).iterdir() if p.suffix.lower() in (".png", ".jpg")]
    pool = fillers(filler_src, max(SIZES) - len(known))
    queries = [(name, t, TRANSFORMS[t](load(held / name))) for name in known for t in QUERY_TRANSFORMS]
    rows = []
    for size in SIZES:
        index = ix.ImageIndex()
        t0 = time.perf_counter()
        for name in known:
            index.add(name, held / name)
        for i, im in enumerate(pool[: size - len(known)]):
            index.add(f"filler{i}", im)
        build = time.perf_counter() - t0
        per_t = {t: [0, 0] for t in QUERY_TRANSFORMS}
        lat = []
        for name, t, im in queries:
            s = time.perf_counter()
            hits = index.query(im)
            lat.append((time.perf_counter() - s) * 1000)
            per_t[t][1] += 1
            per_t[t][0] += bool(hits) and hits[0]["id"] == name
        row = {"index_items": size, "orb_on_every_item": size <= 250, "build_s": round(build, 1),
               "query_ms_p50": round(statistics.median(lat), 1), "query_ms_max": round(max(lat), 1),
               "recall": {t: round(a / b, 3) for t, (a, b) in per_t.items()}}
        rows.append(row)
        print(row)
    # audio fingerprint timing (170 s clip, under the 180 s limit)
    import subprocess
    import tempfile
    from satyapan.media.audio import AudioIndex
    clip = Path(tempfile.mkdtemp()) / "clip170.ogg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-stream_loop", "3", "-i", args.audio,
                    "-t", "170", "-vn", "-c:a", "libopus", "-b:a", "32k", str(clip)], check=True)   # -vn: drop cover art
    aidx = AudioIndex()
    s = time.perf_counter()
    hashes = aidx.add("clip", clip)
    add_s = time.perf_counter() - s
    s = time.perf_counter()
    res = aidx.query(clip)
    q_s = time.perf_counter() - s
    audio = {"clip_s": 170, "hashes": hashes, "index_add_s": round(add_s, 2), "query_s": round(q_s, 2),
             "self_match": bool(res and res[0]["match"])}
    print("audio:", audio)
    Path(args.out).write_text(json.dumps({"image": rows, "audio": audio}, indent=1))


if __name__ == "__main__":
    main()
