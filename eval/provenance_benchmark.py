"""Local provenance benchmark: does the image index find the original after common edits?

This measures RECYCLED-MEDIA MATCHING only. It says nothing about deepfake detection.

Design
  * Index the first N images (default: all but 5). Hold out 5 as negatives.
  * For every indexed image, create transformed copies (resize+JPEG, crops, screenshot
    frame, rotation, caption banner, mirror, grayscale, tiny thumbnail).
  * Query each copy. Score recall@1 for pHash-only and pHash+ORB, false matches, latency.
  * Query every held-out image. Any match is a false positive.

Usage: python eval/provenance_benchmark.py tests/media/images --holdout 5
Real WhatsApp forwards should be added as a further variant set before trusting the numbers.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from satyapan.media.image_index import ImageIndex  # noqa: E402


def jpeg(im: Image.Image, q: int) -> Image.Image:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def screenshot(im: Image.Image) -> Image.Image:
    w, h = im.size
    c = Image.new("RGB", (w + 80, h + 320), (236, 229, 221))
    c.paste(im, (40, 160))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, w + 80, 70], fill=(7, 94, 84))
    d.text((50, h + 190), "Forwarded many times", fill=(0, 0, 0))
    return jpeg(c, 70)


def banner(im: Image.Image) -> Image.Image:
    c = im.copy()
    d = ImageDraw.Draw(c)
    d.rectangle([0, int(im.height * 0.8), im.width, im.height], fill=(200, 0, 0))
    d.text((20, int(im.height * 0.85)), "BREAKING: SHARE NOW", fill=(255, 255, 255))
    return c


VARIANTS = {
    "resize50_jpeg35": lambda im: jpeg(im.resize((im.width // 2, im.height // 2)), 35),
    "jpeg15": lambda im: jpeg(im, 15),
    "thumbnail256": lambda im: jpeg(im.copy().resize((256, int(256 * im.height / im.width))), 60),
    "centre_crop80": lambda im: im.crop((int(im.width * .1), int(im.height * .1), int(im.width * .9), int(im.height * .9))),
    "offcentre_crop60": lambda im: im.crop((0, 0, int(im.width * .6), int(im.height * .6))),
    "screenshot_frame": screenshot,
    "caption_banner": banner,
    "rotate4": lambda im: im.rotate(4, expand=True, fillcolor=(255, 255, 255)),
    "grayscale": lambda im: ImageOps.grayscale(im).convert("RGB"),
    "mirror": ImageOps.mirror,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--holdout", type=int, default=5)
    ap.add_argument("--out", default="results/provenance_benchmark.json")
    args = ap.parse_args()
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    indexed, held = files[:-args.holdout], files[-args.holdout:]
    idx = ImageIndex()
    t0 = time.perf_counter()
    for p in indexed:
        idx.add(p.stem, p)
    index_ms = (time.perf_counter() - t0) * 1000 / len(indexed)

    per_variant, latencies, failures = {}, [], []
    for name, fn in VARIANTS.items():
        phash_ok = full_ok = wrong = 0
        for p in indexed:
            q = fn(Image.open(p).convert("RGB"))
            t = time.perf_counter()
            hits = idx.query(q)
            latencies.append((time.perf_counter() - t) * 1000)
            top = hits[0] if hits else None
            if top and top["id"] == p.stem:
                full_ok += 1
                phash_ok += int("phash" in top.get("method", ""))
            else:
                failures.append({"variant": name, "image": p.name, "got": top["id"] if top else None})
            wrong += int(any(h["id"] != p.stem for h in hits))
        n = len(indexed)
        per_variant[name] = {"n": n, "recall_at_1_phash_only": round(phash_ok / n, 3),
                             "recall_at_1_phash_plus_orb": round(full_ok / n, 3), "queries_with_wrong_ids": wrong}
    fp = []
    for p in held:
        hits = idx.query(Image.open(p).convert("RGB"))
        fp += [{"heldout": p.name, "matched": h["id"]} for h in hits]
        for name in ("resize50_jpeg35", "screenshot_frame"):
            fp += [{"heldout": f"{p.name}:{name}", "matched": h["id"]}
                   for h in idx.query(VARIANTS[name](Image.open(p).convert("RGB")))]
    latencies.sort()
    out = {"indexed": len(indexed), "heldout_images": len(held), "heldout_queries": len(held) * 3,
           "variants": per_variant, "heldout_false_matches": fp,
           "index_ms_per_image": round(index_ms, 1),
           "query_ms_p50": round(latencies[len(latencies) // 2], 1),
           "query_ms_p95": round(latencies[int(len(latencies) * 0.95) - 1], 1), "failures": failures}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"indexed {len(indexed)}, held out {len(held)} ({len(held) * 3} negative queries)")
    print(f"{'variant':<20}{'pHash only':>12}{'pHash+ORB':>12}{'wrong ids':>11}")
    for name, v in per_variant.items():
        print(f"{name:<20}{v['recall_at_1_phash_only']:>12.0%}{v['recall_at_1_phash_plus_orb']:>12.0%}{v['queries_with_wrong_ids']:>11}")
    print(f"held-out false matches: {len(fp)}  index {out['index_ms_per_image']} ms/img  "
          f"query p50 {out['query_ms_p50']} ms p95 {out['query_ms_p95']} ms")
    for f in failures:
        print("  miss:", f)


if __name__ == "__main__":
    main()
