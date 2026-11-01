"""Independent image REUSE-matching evaluation with frozen thresholds.

This measures reuse matching only (is this a copy of an indexed image?).
It does NOT measure manipulation detection or AI-generation detection.

Sets
  dev       scikit-image sample photos (tests/media/images). The shipped thresholds
            were tuned on these, so dev numbers are optimistic by construction.
  heldout   OpenCV sample images (scripts in docs/FINAL_TEST_AUDIT.md). Never used for tuning.
Per set: an index of "known" originals, positive queries (transformed copies of indexed
images) and negative queries (images NOT in the index, including different photos of the
same scene or category, plus transformed copies of those).

Scoring
  positive query: TP if top-1 is the true source, FN if nothing matched,
                  WRONG if a different indexed image is returned (counted as FN and FP)
  negative query: TN if nothing matched, FP if anything matched
Usage: python audit/image_eval.py --set heldout --dir /path/to/opencv_images
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from satyapan.media import image_index as ix  # noqa: E402

SETS = {
    "heldout": {
        "index": ["building.jpg", "butterfly.jpg", "fruits.jpg", "HappyFish.jpg", "home.jpg", "lena.jpg", "messi5.jpg",
                  "orange.jpg", "apple.jpg", "baboon.jpg", "smarties.png", "starry_night.jpg", "stuff.jpg", "sudoku.png",
                  "board.jpg", "aero1.jpg", "graf1.png", "left01.jpg", "Blender_Suzanne1.jpg", "licenseplate_motion.jpg",
                  "cards.png", "box_in_scene.png"],
        # different photos of the same scene or category as an indexed image: the hard negatives
        "hard_negatives": ["aero3.jpg", "graf3.png", "left02.jpg", "left03.jpg", "left04.jpg", "left05.jpg", "left06.jpg",
                           "left07.jpg", "Blender_Suzanne2.jpg"],
        "easy_negatives": ["WindowsLogo.jpg", "notes.png", "digits.png", "pic1.png", "pic3.png", "pic5.png",
                           "ellipses.jpg", "detect_blob.png"],
        "natural_positives": {"lena_tmpl.jpg": "lena.jpg"},   # a real crop shipped with OpenCV
        "excluded": "basketball1/2 and rubberwhale1/2 are consecutive video frames (label ambiguous), "
                    "box.png is a different photo of an object inside box_in_scene, synthetic masks and gradients",
    },
    "dev": {
        "index": ["astronaut.png", "camera.png", "chelsea.png", "coffee.png", "hubble_deep_field.jpg", "motorcycle_left.png",
                  "rocket.jpg", "retina.jpg", "coins.png", "moon.png", "page.png", "brick.png"],
        "hard_negatives": [],
        "easy_negatives": ["grass.png", "gravel.png", "ihc.png", "cell.png", "clock_motion.png"],
        "natural_positives": {},
        "excluded": "",
    },
}


def jpeg(im, q):
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue())).convert("RGB")


def screenshot_v2(im):
    """A different template from the dev benchmark: white app bar, side margins, two text lines below."""
    w, h = im.size
    c = Image.new("RGB", (w + 120, h + 420), (250, 250, 250))
    c.paste(im, (60, 200))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, w + 120, 110], fill=(255, 255, 255))
    d.rectangle([0, 110, w + 120, 116], fill=(220, 220, 220))
    d.text((70, h + 240), "Breaking news shared by 10,000 people", fill=(20, 20, 20))
    d.text((70, h + 290), "Forward to all groups now!!", fill=(200, 0, 0))
    return jpeg(c, 75)


def watermark(im):
    c = im.convert("RGBA")
    layer = Image.new("RGBA", c.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    step = max(60, c.width // 6)
    for y in range(0, c.height, step):
        for x in range(0, c.width, step * 2):
            d.text((x, y), "SHARE NOW", fill=(255, 255, 255, 110))
    return Image.alpha_composite(c, layer).convert("RGB")


TRANSFORMS = {
    "original": lambda im: im,
    "resize50": lambda im: im.resize((max(1, im.width // 2), max(1, im.height // 2))),
    "jpeg30": lambda im: jpeg(im, 30),
    "centre_crop70": lambda im: im.crop((int(im.width * .15), int(im.height * .15), int(im.width * .85), int(im.height * .85))),
    "offcentre_crop55_br": lambda im: im.crop((int(im.width * .45), int(im.height * .45), im.width, im.height)),
    "screenshot_v2": screenshot_v2,
    "watermark_tiled": watermark,
    "blur2.5": lambda im: im.filter(ImageFilter.GaussianBlur(2.5)),
    "rotate7": lambda im: im.rotate(7, expand=True, fillcolor=(0, 0, 0)),
    "rotate15": lambda im: im.rotate(15, expand=True, fillcolor=(0, 0, 0)),
    "combo_screenshot_resize60_jpeg50": lambda im: jpeg(screenshot_v2(im).resize(
        (int((im.width + 120) * .6), int((im.height + 420) * .6))), 50),
    "mirror": ImageOps.mirror,
}
NEG_TRANSFORMS = ["original", "resize50", "jpeg30", "screenshot_v2"]


def load(p: Path) -> Image.Image:
    with Image.open(p) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=SETS, required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--evidence-tiers", action="store_true",
                    help="2.0: count a hit only when its tier can be evidence (exact or modified duplicate). "
                         "Similar-scene hits are shown to users but never counted against a message.")
    args = ap.parse_args()
    cfg, folder = SETS[args.set], Path(args.dir)
    thresholds = {k: getattr(ix, k) for k in ("MIN_INLIERS", "MIN_INLIER_RATIO", "MIN_SPREAD", "MAX_ANISOTROPY", "CROP_SCALES")}
    index = ix.ImageIndex()
    t0 = time.perf_counter()
    for name in cfg["index"]:
        index.add(name, folder / name)
    index_s = time.perf_counter() - t0

    per_t = defaultdict(lambda: {"TP": 0, "FN": 0, "WRONG": 0})
    neg = defaultdict(lambda: {"TN": 0, "FP": 0})
    misses, fps, lat = [], [], []

    def q(im):
        s = time.perf_counter()
        hits = index.query(im)
        lat.append((time.perf_counter() - s) * 1000)
        if args.evidence_tiers:
            hits = [h for h in hits if h.get("tier") in ("exact_duplicate", "modified_duplicate")]
        return hits

    for name in cfg["index"]:
        base = load(folder / name)
        for tname, fn in TRANSFORMS.items():
            hits = q(fn(base))
            top = hits[0]["id"] if hits else None
            if top == name:
                per_t[tname]["TP"] += 1
            elif top is None:
                per_t[tname]["FN"] += 1
                misses.append((name, tname, None))
            else:
                per_t[tname]["WRONG"] += 1
                misses.append((name, tname, top))
    for qname, src in cfg["natural_positives"].items():
        hits = q(load(folder / qname))
        top = hits[0]["id"] if hits else None
        key = "natural_crop"
        per_t[key]["TP" if top == src else ("FN" if top is None else "WRONG")] += 1
        if top != src:
            misses.append((qname, key, top))
    for group in ("hard_negatives", "easy_negatives"):
        for name in cfg[group]:
            base = load(folder / name)
            for tname in NEG_TRANSFORMS:
                hits = q(TRANSFORMS[tname](base))
                if hits:
                    neg[group]["FP"] += 1
                    fps.append((name, tname, hits[0]["id"], hits[0].get("method"), hits[0].get("orb", {}).get("inliers")))
                else:
                    neg[group]["TN"] += 1

    TP = sum(v["TP"] for v in per_t.values())
    FN = sum(v["FN"] + v["WRONG"] for v in per_t.values())
    WRONG = sum(v["WRONG"] for v in per_t.values())
    FPn = sum(v["FP"] for v in neg.values())
    TN = sum(v["TN"] for v in neg.values())
    FP = FPn + WRONG
    precision = TP / (TP + FP) if TP + FP else 0.0
    recall = TP / (TP + FN) if TP + FN else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = FPn / (FPn + TN) if FPn + TN else 0.0
    lat.sort()
    thresholds["DUPLICATE_SIM_SHARE"] = getattr(ix, "DUPLICATE_SIM_SHARE", None)
    out = {"set": args.set, "evidence_tiers_only": args.evidence_tiers, "thresholds_frozen": thresholds, "indexed": len(cfg["index"]),
           "positive_queries": TP + FN, "negative_queries": FPn + TN,
           "TP": TP, "FN": FN, "wrong_attributions": WRONG, "FP_on_negatives": FPn, "FP_total": FP, "TN": TN,
           "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3), "fpr": round(fpr, 3),
           "per_transform_recall": {k: round(v["TP"] / max(1, sum(v.values())), 3) for k, v in per_t.items()},
           "per_transform_counts": dict(per_t), "negatives": dict(neg),
           "false_positives": fps, "misses": misses, "excluded": cfg["excluded"],
           "index_build_s": round(index_s, 2), "query_ms_p50": round(lat[len(lat) // 2], 1),
           "query_ms_p95": round(lat[max(0, int(len(lat) * .95) - 1)], 1)}
    path = Path(args.out or ROOT / "results" / "audit" / f"image_eval_{args.set}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print(f"[{args.set}] indexed {out['indexed']}, positives {out['positive_queries']}, negatives {out['negative_queries']}")
    print(f"TP {TP}  FN {FN} (of which wrong attribution {WRONG})  FP on negatives {FPn}  TN {TN}")
    print(f"precision {precision:.3f}  recall {recall:.3f}  F1 {f1:.3f}  FPR {fpr:.3f}")
    for k, v in out["per_transform_recall"].items():
        print(f"   {k:<34} recall {v:.0%}  {dict(per_t[k])}")
    print("false positives:", fps)
    print(f"query p50 {out['query_ms_p50']} ms, p95 {out['query_ms_p95']} ms, index build {out['index_build_s']} s")


if __name__ == "__main__":
    main()
