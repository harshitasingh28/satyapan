"""Dataset verification: is the evaluation data collected, consistent and leak-free?

Reports facts only. It never fills, generates or "completes" any dataset row.
Usage: python audit/dataset_audit.py [--claims eval/manifest.csv] [--detector eval/detector_manifest.csv]
       (defaults to the templates when the real manifests do not exist yet)
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", default=None)
    ap.add_argument("--detector", default=None)
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "dataset_validation.json"))
    a = ap.parse_args()
    claims = Path(a.claims) if a.claims else (ROOT / "eval" / "manifest.csv")
    if not claims.exists():
        claims = ROOT / "eval" / "manifest_template.csv"
    det = Path(a.detector) if a.detector else (ROOT / "eval" / "detector_manifest.csv")
    if not det.exists():
        det = ROOT / "eval" / "detector_manifest_template.csv"
    plan = json.loads((ROOT / "eval" / "plan.json").read_text())
    rows = list(csv.DictReader(open(claims, encoding="utf-8")))
    drows = list(csv.DictReader(open(det, encoding="utf-8")))
    filled = [r for r in rows if r["evidence_url"].strip()]
    dfilled = [r for r in drows if r["file"].strip()]
    test_truth = Counter(c["truth"] for k, c in plan["categories"].items() for _ in range(c["test"]))
    out = {
        "claim_manifest": str(claims.relative_to(ROOT)), "detector_manifest": str(det.relative_to(ROOT)),
        "claim_rows": len(rows), "claim_rows_filled": len(filled),
        "detector_rows": len(drows), "detector_rows_filled": len(dfilled),
        "plan_totals": plan["totals"],
        "plan_sum_dev": sum(c["dev"] for c in plan["categories"].values()),
        "plan_sum_test": sum(c["test"] for c in plan["categories"].values()),
        "plan_test_truth": dict(test_truth),
        "abstain_by_design": [k for k, c in plan["categories"].items() if c["truth"] == "FALSE" and c["expected"] == "UNVERIFIED"],
        "detector_split_label": {f"{s}/{lab}": n for (s, lab), n in Counter((r["split"], r["label"]) for r in drows).items()},
    }
    v = subprocess.run([sys.executable, str(ROOT / "eval" / "validate_manifest.py"), str(claims)],
                       capture_output=True, text=True)
    out["validator_exit"], out["validator_output"] = v.returncode, v.stdout.strip().splitlines()[-3:]
    # can the validator see near-duplicate leakage? (a resized copy of a dev image placed in test)
    from validate_manifest import near_duplicates
    tmp = Path(tempfile.mkdtemp())
    src = sorted((ROOT / "tests" / "media" / "images").glob("*.png"))[0]
    Image.open(src).convert("RGB").save(tmp / "dev.jpg", "JPEG")
    Image.open(src).convert("RGB").resize((256, 192)).save(tmp / "test.jpg", "JPEG", quality=60)
    probe = [{"sample_id": "D", "split": "dev", "input_file": "dev.jpg", "claim_text": "", "notes": ""},
             {"sample_id": "T", "split": "test", "input_file": "test.jpg", "claim_text": "", "notes": ""}]
    out["near_duplicate_probe"] = near_duplicates(probe, tmp)
    out["near_duplicate_leak_detected"] = bool(out["near_duplicate_probe"])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1))
    collected = len(filled) == len(rows) and len(dfilled) == len(drows)
    print(f"claim manifest {out['claim_manifest']}: {len(filled)}/{len(rows)} rows filled")
    print(f"detector manifest {out['detector_manifest']}: {len(dfilled)}/{len(drows)} rows filled, {out['detector_split_label']}")
    print(f"plan dev {out['plan_sum_dev']} test {out['plan_sum_test']} (declared {plan['totals']}), test truth {out['plan_test_truth']}")
    print(f"FALSE claims expected to abstain (UNVERIFIED) by design: {out['abstain_by_design']}")
    print("validator:", " | ".join(out["validator_output"]))
    print(f"{'PASS' if out['near_duplicate_leak_detected'] else 'FAIL'}  near-duplicate leak detected: {out['near_duplicate_probe']}")
    print("DATASET COLLECTED" if collected else "DATASET NOT COLLECTED: no accuracy figure can be reported")
    return 0 if out["near_duplicate_leak_detected"] else 1


if __name__ == "__main__":
    sys.exit(main())
