"""Metrics for one evaluation run directory (results/eval_<split>_<time>/).

Claim verdicts (from predictions.csv)
  FAKE class:    precision, recall, F1. Positive = ground truth FALSE.
  GENUINE class: precision, recall, F1. Positive = ground truth TRUE.
  False-positive rate   = TRUE items called FAKE / all TRUE items   (false accusation)
  False-negative rate   = FALSE items not called FAKE / all FALSE items (UNVERIFIED counts here)
  False reassurance     = FALSE items called GENUINE / all FALSE items
  UNVERIFIED rate       = overall and per category
Media provenance (R and V only, human-confirmed in provenance_review.csv)
  accuracy = items where the tools found the known original / all R and V items
Deepfake detection is NOT computed here. It lives in eval/detector_eval.py on a separate set.
Operations
  API failure rate per tool = failed runs / runs. Latency p50 and p95, end to end and fast path.
Every proportion carries a 95% Wilson interval.

Usage: python eval/metrics.py results/eval_test_20261101T120000
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

FAILED = {"AUTH_REQUIRED", "BLOCKED", "SERVICE_ERROR", "RATE_LIMITED"}


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n/a (n=0)"
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{p:.0%} ({k}/{n}, 95% CI {max(0, c - h):.0%} to {min(1, c + h):.0%})"


def prf(tp: int, fp: int, fn: int) -> tuple[str, str, str]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return wilson(tp, tp + fp), wilson(tp, tp + fn), f"{f1:.2f}"


def pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[max(0, math.ceil(q / 100 * len(s)) - 1)], 1)


def main(run_dir: str) -> None:
    d = Path(run_dir)
    preds = list(csv.DictReader(open(d / "predictions.csv", encoding="utf-8")))
    info = json.loads((d / "run_info.json").read_text())
    T = [p for p in preds if p["truth"] == "TRUE"]
    F = [p for p in preds if p["truth"] == "FALSE"]
    U = [p for p in preds if p["truth"] == "UNRESOLVED"]
    called_fake = [p for p in preds if p["predicted"] == "FAKE"]
    called_gen = [p for p in preds if p["predicted"] == "GENUINE"]
    tp_f = sum(p["truth"] == "FALSE" for p in called_fake)
    tp_g = sum(p["truth"] == "TRUE" for p in called_gen)
    fake_p, fake_r, fake_f1 = prf(tp_f, len(called_fake) - tp_f, len(F) - tp_f)
    gen_p, gen_r, gen_f1 = prf(tp_g, len(called_gen) - tp_g, len(T) - tp_g)
    lines = [f"# Metrics: {info['split']} split, {len(preds)} items", "",
             f"Thresholds fingerprint `{info['thresholds']}`, commit `{info['git_commit']}`, "
             f"third-party consent {info['third_party_consent']}.", "",
             "| truth \\ predicted | FAKE | GENUINE | UNVERIFIED |", "|---|---|---|---|"]
    for name, group in (("FALSE", F), ("TRUE", T), ("UNRESOLVED", U)):
        c = Counter(p["predicted"] for p in group)
        lines.append(f"| {name} ({len(group)}) | {c['FAKE']} | {c['GENUINE']} | {c['UNVERIFIED']} |")
    fp_true = sum(p["predicted"] == "FAKE" for p in T)
    lines += ["", "## Verdicts", "",
              f"- FAKE precision {fake_p}, recall {fake_r}, F1 {fake_f1}",
              f"- GENUINE precision {gen_p}, recall {gen_r}, F1 {gen_f1}",
              f"- False-positive rate (TRUE called FAKE): {wilson(fp_true, len(T))}",
              f"- False-negative rate (FALSE not called FAKE): {wilson(len(F) - tp_f, len(F))}",
              f"- False reassurance (FALSE called GENUINE): {wilson(sum(p['predicted'] == 'GENUINE' for p in F), len(F))}",
              f"- UNVERIFIED rate: {wilson(sum(p['predicted'] == 'UNVERIFIED' for p in preds), len(preds))}",
              f"- Unresolved items left UNVERIFIED: {wilson(sum(p['predicted'] == 'UNVERIFIED' for p in U), len(U))}"]
    if fp_true == 0 and len(T) >= 10:
        lines.append(f"- Zero false accusations in {len(T)} TRUE items only bounds the true rate below about "
                     f"{min(1, 3 / len(T)):.0%} (rule of three).")
    lines += ["", "## By category", ""]
    for cat in sorted({p["category"] for p in preds}):
        g = [p for p in preds if p["category"] == cat]
        c = Counter(p["predicted"] for p in g)
        lines.append(f"- {cat} ({len(g)}): FAKE {c['FAKE']}, GENUINE {c['GENUINE']}, UNVERIFIED {c['UNVERIFIED']}")

    review_path = d / "provenance_review.csv"
    review = {r["sample_id"]: r for r in csv.DictReader(open(review_path, encoding="utf-8"))} if review_path.exists() else {}
    rv = [p for p in preds if p["category"] in ("R", "V")]
    confirmed = sum(review.get(p["sample_id"], {}).get("found_known_original", "").upper() == "Y" for p in rv)
    reviewed = sum(bool(review.get(p["sample_id"], {}).get("found_known_original")) for p in rv)
    lines += ["", "## Media provenance (R and V, human-confirmed)", "",
              f"- Accuracy: {wilson(confirmed, len(rv))}. Reviewed {reviewed}/{len(rv)}.",
              "- This is reuse detection. It is not deepfake detection (see detector_eval.py)."]

    runs = defaultdict(lambda: [0, 0])
    tool_ms = defaultdict(list)
    for p in preds:
        for tool, status, ms in json.loads(p["tool_runs"]):
            runs[tool][0] += 1
            runs[tool][1] += status in FAILED
            if status in ("LIVE_SUCCESS", "LOCAL_SUCCESS"):
                tool_ms[tool].append(ms)
    total = [float(p["total_ms"]) for p in preds]
    fast = [float(p["fast_path_ms"]) for p in preds]
    lines += ["", "## Operations", "",
              f"- End-to-end latency p50 {pct(total, 50)} ms, p95 {pct(total, 95)} ms",
              f"- Fast path (without urlscan) p50 {pct(fast, 50)} ms, p95 {pct(fast, 95)} ms", "",
              "| Tool | Runs | Failure rate | p50 ms | p95 ms |", "|---|---|---|---|---|"]
    for tool, (n, failed) in sorted(runs.items()):
        lines.append(f"| {tool} | {n} | {wilson(failed, n)} | {pct(tool_ms[tool], 50)} | {pct(tool_ms[tool], 95)} |")
    out = d / "metrics.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 2.0 additions: accuracy against the plan's acceptable verdicts, per language and input type,
    # and the share of external tool calls that failed.
    plan = json.loads((Path(__file__).parent / "plan.json").read_text())["categories"]

    def ok(p):
        return p["predicted"] in plan.get(p["category"], {}).get("acceptable", [p.get("expected")])
    exact = sum(p["predicted"] == p.get("expected") for p in preds)
    lines += ["", "## Accuracy", "",
              f"- Exact match with the expected verdict: {wilson(exact, len(preds))}",
              f"- Acceptable verdict (plan.json, e.g. UNVERIFIED allowed for hard cases): "
              f"{wilson(sum(ok(p) for p in preds), len(preds))}"]
    for field, title in (("language", "By language"), ("input_type", "By input type")):
        groups = defaultdict(list)
        for p in preds:
            groups[p.get(field) or "unknown"].append(p)
        lines += ["", f"### {title}", ""] + [
            f"- {k} ({len(g)}): acceptable {wilson(sum(ok(p) for p in g), len(g))}, "
            f"exact {wilson(sum(p['predicted'] == p.get('expected') for p in g), len(g))}" for k, g in sorted(groups.items())]
    external = failed = 0
    for p in preds:
        for tool, status, _ms in json.loads(p["tool_runs"]):
            if status in ("LOCAL_SUCCESS", "SKIPPED_CONSENT", "SKIPPED_NOT_APPLICABLE", "NOT_TESTED", "INPUT_ERROR"):
                continue
            external += 1
            failed += status in ("AUTH_REQUIRED", "RATE_LIMITED", "BLOCKED", "SERVICE_ERROR")
    lines += ["", "## API reliability", "", f"- External tool calls that failed: {wilson(failed, external)}"]
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
