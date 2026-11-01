"""Validate eval/manifest.csv against eval/plan.json before any evaluation run.

Checks: exact category counts per split, unique ids, allowed values, required fields,
expected verdict consistent with the plan, real http(s) evidence URLs, and LEAKAGE:
the same evidence URL, claim text or media file must not appear in both dev and test.
Near-duplicates are leakage too (added in the audit round): a resized, cropped or
screenshotted copy of a dev image in test, or a lightly reworded dev claim in test.
Near-duplicate checks over-report on purpose (the image matcher also fires on
different photos of the same scene). Review each pair by eye, then either move one
item or write leak-reviewed in its notes column.

Usage: python eval/validate_manifest.py eval/manifest.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
TEXT_NEAR_DUP = 90


def near_duplicates(rows: list[dict], media_root: Path | None = None) -> list[str]:
    """Cross-split near-duplicate media (same matcher as the product) and near-duplicate claim text."""
    sys.path.insert(0, str(ROOT))
    from satyapan.media.image_index import ImageIndex
    from satyapan.pipeline.graph import similarity
    media_root = media_root or ROOT / "data" / "eval_media"
    out = []
    live = [r for r in rows if "leak-reviewed" not in (r.get("notes") or "")]
    dev = [r for r in live if r["split"] == "dev"]
    test = [r for r in live if r["split"] == "test"]
    idx = ImageIndex()
    for r in dev:
        p = media_root / r["input_file"]
        if r["input_file"].strip() and p.suffix.lower() in IMAGE_SUFFIXES and p.exists():
            idx.add(r["sample_id"], p)
    if idx.items:
        for r in test:
            p = media_root / r["input_file"]
            if r["input_file"].strip() and p.suffix.lower() in IMAGE_SUFFIXES and p.exists():
                for hit in idx.query(p)[:1]:
                    out.append(f"LEAKAGE (possible near-duplicate image, review): test {r['sample_id']} "
                               f"matches dev {hit['id']} ({hit.get('method')})")
    for t in test:
        if not t["claim_text"].strip():
            continue
        for d in dev:
            if d["claim_text"].strip() and similarity(t["claim_text"], d["claim_text"]) >= TEXT_NEAR_DUP:
                out.append(f"LEAKAGE (near-duplicate claim text, review): test {t['sample_id']} ~ dev {d['sample_id']}")
                break
    return out


def main(path: str) -> int:
    plan = json.loads((ROOT / "eval" / "plan.json").read_text())
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    errors, warnings = [], []
    ids = Counter(r["sample_id"] for r in rows)
    errors += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    counts = Counter((r["category"], r["split"]) for r in rows)
    for cat, c in plan["categories"].items():
        for split in ("dev", "test"):
            if counts[(cat, split)] != c[split]:
                errors.append(f"{cat}/{split}: have {counts[(cat, split)]}, plan says {c[split]}")
    if len(rows) != plan["totals"]["all"]:
        errors.append(f"total rows {len(rows)}, plan says {plan['totals']['all']}")

    filled = 0
    for r in rows:
        sid, cat = r["sample_id"], r["category"]
        c = plan["categories"].get(cat)
        if not c:
            errors.append(f"{sid}: unknown category {cat}")
            continue
        if not r["evidence_url"].strip():
            continue                                  # unfilled template row, counted below
        filled += 1
        if r["ground_truth_claim"] != c["truth"] or r["expected_verdict"] != c["expected"]:
            errors.append(f"{sid}: truth/expected verdict must be {c['truth']}/{c['expected']} for {cat}")
        if r["input_type"] not in plan["input_types"]:
            errors.append(f"{sid}: input_type '{r['input_type']}' not in {plan['input_types']}")
        if r["media_status"] not in plan["media_status"]:
            errors.append(f"{sid}: media_status '{r['media_status']}' invalid")
        if r["language"] not in plan["languages"]:
            errors.append(f"{sid}: language '{r['language']}' invalid")
        for field in ("evidence_url",) + (("original_source",) if cat in plan["requires_original_source"] else ()):
            u = urlsplit(r[field].strip())
            if u.scheme not in ("http", "https") or not u.netloc:
                errors.append(f"{sid}: {field} must be a real http(s) URL")
        if cat in plan["requires_media"] and not r["input_file"].strip():
            errors.append(f"{sid}: category {cat} needs input_file")
        if r["input_file"].strip() and not (ROOT / "data" / "eval_media" / r["input_file"]).exists():
            errors.append(f"{sid}: file data/eval_media/{r['input_file']} not found")
        if not r["claim_text"].strip() and not r["input_file"].strip() and not r["links"].strip():
            errors.append(f"{sid}: no input at all")

    def leak(key_fn, label):
        seen: dict[str, str] = {}
        for r in rows:
            k = key_fn(r)
            if not k:
                continue
            if k in seen and seen[k] != r["split"]:
                errors.append(f"LEAKAGE: same {label} in dev and test ({r['sample_id']})")
            seen.setdefault(k, r["split"])

    leak(lambda r: r["evidence_url"].strip().lower(), "evidence URL")
    leak(lambda r: " ".join(r["claim_text"].lower().split()), "claim text")

    def file_hash(r):
        p = ROOT / "data" / "eval_media" / r["input_file"]
        return hashlib.sha256(p.read_bytes()).hexdigest() if r["input_file"] and p.exists() else ""
    leak(file_hash, "media file")
    errors.extend(near_duplicates(rows))

    if filled < len(rows):
        warnings.append(f"{len(rows) - filled} of {len(rows)} rows are still empty templates")
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("WARNING", w)
    print(f"{len(rows)} rows, {filled} filled, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "eval" / "manifest.csv")))
