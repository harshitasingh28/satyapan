"""Compare hosted chat models on the SAME labelled development pairs (no test-split data).

Input CSV (one row per labelled pair, labelled by a team member from the real sources):
  id,language,claim,candidate_type,candidate_text,expected_relation,expected_same_subject,source_url,labelled_by
  candidate_type: official_release | reviewed_claim
  expected_relation: supports | contradicts | insufficient,   expected_same_subject: true | false
Each model gets every pair through the real comparison code (satyapan/pipeline/compare.py), so its
quotes are checked exactly as in production. Reported per model: answers with verified quotes,
relation and same-subject accuracy, accuracy per language, latency p50 and p95, failures.
Pick the model from these numbers, then set HF_CHAT_MODEL. Cost comes from the HF billing page.
Usage: python eval/model_bakeoff.py --pairs eval/bakeoff_pairs.csv \
         --model "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra" --model "openai/gpt-oss-120b:groq" \
         --model "google/gemma-3-27b-it:deepinfra"
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import satyapan.llm as llm  # noqa: E402
from satyapan.config import get_settings  # noqa: E402
from satyapan.errors import ToolError  # noqa: E402
from satyapan.http import ApiClient  # noqa: E402
from satyapan.pipeline.compare import compare  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "bakeoff"))
    args = ap.parse_args()
    rows = list(csv.DictReader(open(args.pairs, encoding="utf-8")))
    if not rows:
        raise SystemExit("no labelled pairs")
    base = get_settings()
    if not base.llm_configured:
        raise SystemExit("HF_TOKEN must be set (the model list comes from --model)")
    results = {}
    for model in args.model:
        s = dataclasses.replace(base, llm_model=model, hf_chat_fallback_model="")
        llm.get_settings = lambda s=s: s          # this script only: route every call to this model
        client = ApiClient(s)
        per, lat, fails = [], [], 0
        for r in rows:
            start = time.perf_counter()
            try:
                out = compare(client, r["claim"], [{"id": "K1", "type": r["candidate_type"], "text": r["candidate_text"]}])
            except ToolError as err:
                fails += 1
                per.append({"id": r["id"], "language": r["language"], "error": err.status.value})
                continue
            lat.append((time.perf_counter() - start) * 1000)
            p = out["pairs"]["K1"]
            per.append({"id": r["id"], "language": r["language"], "verified": p["verified"],
                        "relation_ok": p["verified"] and p["relation"] == r["expected_relation"],
                        "same_ok": p["verified"] and str(p["same_subject"]).lower() == r["expected_same_subject"].lower(),
                        "relation": p["relation"], "problem": p["problem"]})
        answered = [x for x in per if "error" not in x]
        by_lang = defaultdict(list)
        for x in answered:
            by_lang[x["language"]].append(x["relation_ok"])
        results[model] = {
            "pairs": len(rows), "failures": fails,
            "verified_quotes": sum(x["verified"] for x in answered),
            "relation_correct": sum(x["relation_ok"] for x in answered),
            "same_subject_correct": sum(x["same_ok"] for x in answered),
            "relation_correct_by_language": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_lang.items())},
            "latency_ms_p50": round(statistics.median(lat)) if lat else None,
            "latency_ms_p95": round(sorted(lat)[max(0, int(len(lat) * .95) - 1)]) if lat else None,
            "rows": per}
        print(f"{model}: verified {results[model]['verified_quotes']}/{len(rows)}, relation correct "
              f"{results[model]['relation_correct']}/{len(rows)}, same subject {results[model]['same_subject_correct']}/"
              f"{len(rows)}, by language {results[model]['relation_correct_by_language']}, failures {fails}, "
              f"p50 {results[model]['latency_ms_p50']} ms, p95 {results[model]['latency_ms_p95']} ms")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"bakeoff_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps({"pairs_file": args.pairs, "results": results}, ensure_ascii=False, indent=1))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
