"""Run the pipeline over one split of eval/manifest.csv.

Dev split: run as often as you like and tune thresholds on it.
Test split: run ONCE, after thresholds are frozen. The script records the git
commit and a hash of the threshold constants so the result can be traced.

Usage
  python eval/run_eval.py --split dev
  python eval/run_eval.py --split test --frozen
Options: --consent-third-party (send media and links to the configured services)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satyapan.media import image_index  # noqa: E402
from satyapan.pipeline import graph  # noqa: E402
from satyapan.pipeline.graph import Context, new_state, run, to_report  # noqa: E402


def thresholds_fingerprint() -> str:
    values = {k: getattr(graph, k) for k in ("FC_MATCH", "FC_POSSIBLE", "KNOWN_MATCH")}
    values.update({k: getattr(image_index, k) for k in ("MIN_INLIERS", "MIN_INLIER_RATIO", "MIN_SPREAD", "MAX_ANISOTROPY")})
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("dev", "test"), default="dev")
    ap.add_argument("--frozen", action="store_true", help="required for the test split")
    ap.add_argument("--consent-third-party", action="store_true")
    ap.add_argument("--manifest", default=str(ROOT / "eval" / "manifest.csv"))
    args = ap.parse_args()
    if args.split == "test" and not args.frozen:
        sys.exit("Refusing to run the test split without --frozen. Tune on dev, freeze thresholds, then run test once.")
    rows = [r for r in csv.DictReader(open(args.manifest, encoding="utf-8"))
            if r["split"] == args.split and r["evidence_url"].strip()]
    if not rows:
        sys.exit("no filled rows for this split (python eval/validate_manifest.py first)")
    out_dir = ROOT / "results" / f"eval_{args.split}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    (out_dir / "reports").mkdir(parents=True)
    from satyapan.storage import open_store
    ctx = Context.default(store=open_store())
    consent = {k: args.consent_third_party for k in ("third_party_text", "third_party_links", "third_party_media")}
    preds = []
    for r in rows:
        media = [(ROOT / "data" / "eval_media" / r["input_file"], r["input_file"])] if r["input_file"].strip() else []
        start = time.perf_counter()
        state = run(new_state(text=r["claim_text"], links=r["links"].split(), media=media, consent=consent), ctx)
        report = to_report(state)
        total_ms = (time.perf_counter() - start) * 1000
        (out_dir / "reports" / f"{r['sample_id']}.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        assess = next(iter(report.media_assessment.values()), {})
        preds.append({"sample_id": r["sample_id"], "category": r["category"], "truth": r["ground_truth_claim"],
                      "expected": r["expected_verdict"], "language": r["language"], "input_type": r["input_type"],
                      "predicted": report.verdict, "provenance": assess.get("provenance", ""),
                      "synthetic_signal": assess.get("synthetic_signal", ""),
                      "tool_runs": json.dumps([[t.tool, t.status, t.ms] for t in report.tool_runs]),
                      "total_ms": round(total_ms, 1),
                      "fast_path_ms": round(total_ms - sum(t.ms for t in report.tool_runs if t.tool.startswith("urlscan")), 1)})
        print(f"{r['sample_id']:<14} truth={r['ground_truth_claim']:<10} predicted={report.verdict:<10} {total_ms:8.0f} ms")
    with (out_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(preds[0].keys()))
        w.writeheader()
        w.writerows(preds)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    (out_dir / "run_info.json").write_text(json.dumps({
        "split": args.split, "items": len(rows), "thresholds": thresholds_fingerprint(), "git_commit": commit or "not a git repo",
        "third_party_consent": args.consent_third_party, "finished": datetime.now(timezone.utc).isoformat()}, indent=1))
    print(f"\nwrote {out_dir}. Next: fill {out_dir}/provenance_review.csv, then python eval/metrics.py {out_dir}")
    with (out_dir / "provenance_review.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_id", "found_known_original", "reviewer", "notes"])
        for p in preds:
            if p["category"] in ("R", "V"):
                w.writerow([p["sample_id"], "", "", ""])


if __name__ == "__main__":
    main()
