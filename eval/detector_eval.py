"""AI-generated IMAGE detector benchmark, kept separate from claim verification.

Ground truth comes from construction: the team generates the AI images with named
generators and takes the real photos themselves. Each image is also forwarded for
real (send it to a teammate on WhatsApp and download it again), stored in forwarded_file.

Protocol
  1. Score the dev split. Choose the threshold that keeps FPR <= 10% on dev forwarded photos.
  2. Freeze it. Score the test split once with that threshold.
  3. Report AUC, TPR and FPR on original and forwarded test images.
The detector may enter verdicts only if test forwarded FPR <= 10% and TPR >= 50%.

Usage: python eval/detector_eval.py eval/detector_manifest.csv --detector sightengine
Sightengine needs keys and sends the (team-owned) images to Sightengine.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satyapan.errors import ToolError  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.media.remote import sightengine_genai  # noqa: E402
from satyapan.security.uploads import sanitized_image_copy  # noqa: E402


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    return round(sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)), 3)


def rates(pos, neg, t):
    return (round(sum(s >= t for s in pos) / len(pos), 3) if pos else None,
            round(sum(s >= t for s in neg) / len(neg), 3) if neg else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--detector", choices=("sightengine",), default="sightengine")
    args = ap.parse_args()
    rows = [r for r in csv.DictReader(open(args.manifest, encoding="utf-8")) if r["file"].strip()]
    client = ApiClient()
    scores: dict[tuple[str, str, str], list[float]] = {}
    for r in rows:
        for version in ("file", "forwarded_file"):
            if not r[version].strip():
                continue
            clean = sanitized_image_copy(ROOT / "data" / "detector_media" / r[version], ROOT / "data" / "work" / "det")
            try:
                s = sightengine_genai(client, clean)["score"]
            except ToolError as err:
                print(f"{r['sample_id']} {version}: {err.status.value} {err.message[:80]}")
                continue
            scores.setdefault((r["split"], version, r["label"]), []).append(float(s))
    dev_real = sorted(scores.get(("dev", "forwarded_file", "real"), []))
    if not dev_real:
        sys.exit("no dev forwarded real-photo scores, cannot choose a threshold")
    thr = dev_real[min(len(dev_real) - 1, int(0.9 * len(dev_real)))] + 1e-6   # ~10% FPR on dev forwarded
    out = {"threshold_from_dev": round(thr, 4)}
    for version in ("file", "forwarded_file"):
        pos, neg = scores.get(("test", version, "ai"), []), scores.get(("test", version, "real"), [])
        tpr, fpr = rates(pos, neg, thr)
        out[version] = {"n_ai": len(pos), "n_real": len(neg), "auc": auc(pos, neg), "tpr": tpr, "fpr": fpr}
    fwd = out["forwarded_file"]
    out["may_enter_verdicts"] = bool(fwd["fpr"] is not None and fwd["fpr"] <= 0.10 and (fwd["tpr"] or 0) >= 0.5)
    print(json.dumps(out, indent=1))
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "detector_eval.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
