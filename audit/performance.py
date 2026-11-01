"""Performance and resource measurements (in-process). Network is whatever the machine has.

Each case runs the full pipeline in a fresh subprocess so peak memory is per case.
Measures wall time, CPU time and peak RSS. External calls are recorded with their
status: a BLOCKED call costs its timeout, not a real API latency.
Usage: python audit/performance.py --heldout-dir /path/to/images
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r"""
import json, os, resource, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
t0 = time.perf_counter(); c0 = time.process_time()
from satyapan.pipeline.graph import Context, new_state, run, to_report
ctx = Context.default()
kind, arg = sys.argv[2], sys.argv[3]
t1 = time.perf_counter()
if kind == "text":
    st = new_state(text=arg)
else:
    st = new_state(media=[(Path(arg), Path(arg).name)])
st = run(st, ctx)
rep = to_report(st)
t2 = time.perf_counter()
print(json.dumps({"import_and_context_s": round(t1 - t0, 3), "pipeline_s": round(t2 - t1, 3),
                  "cpu_s": round(time.process_time() - c0, 3),
                  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1),
                  "verdict": rep.verdict,
                  "tools": [(t.tool, t.status, t.ms) for t in rep.tool_runs]}))
"""


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_inputs(heldout: Path, work: Path) -> list[tuple[str, str, str]]:
    from PIL import Image
    base = Image.open(heldout / "building.jpg").convert("RGB")
    cases = [("text", "text_scam", "PM Kisan Yojana gives Rs 10,000. Apply now at http://pmkisan-gov.top/register")]
    for name, size in (("image_1mp", (1200, 900)), ("image_12mp", (4000, 3000)), ("image_39mp", (7200, 5400))):
        p = work / f"{name}.jpg"
        base.resize(size).save(p, "JPEG", quality=85)
        cases.append(("file", name, str(p)))
    for name, secs, scale in (("video_60s_720p", 60, "1280:720"), ("video_180s_1080p", 180, "1920:1080")):
        p = work / f"{name}.mp4"
        ff("-f", "lavfi", "-i", f"testsrc2=size={scale.replace(':', 'x')}:rate=25:duration={secs}", "-f", "lavfi",
           "-i", f"sine=frequency=300:duration={secs}", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1500k",
           "-c:a", "aac", "-shortest", str(p))
        cases.append(("file", name, str(p)))
    p = work / "audio_180s.ogg"
    src = ROOT / "tests" / "media" / "audio" / "music.ogg"
    ff("-stream_loop", "3", "-i", str(src), "-t", "180", "-vn", "-c:a", "libopus", "-b:a", "32k", str(p))   # -vn: drop cover art
    cases.append(("file", "audio_180s", str(p)))
    return cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout-dir", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "audit" / "performance.json"))
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="satyapan_perf_"))
    data = Path(tempfile.mkdtemp(prefix="satyapan_perf_data_"))
    env = {**os.environ, "SATYAPAN_DATA_DIR": str(data), "SATYAPAN_RETRIES": "0"}
    if (ROOT / "tests" / "media" / "tessdata").exists():
        env["TESSDATA_PREFIX"] = str(ROOT / "tests" / "media" / "tessdata")
    cases = make_inputs(Path(args.heldout_dir), work)
    out = {"machine": {"platform": platform.platform(), "cpu_count": os.cpu_count(), "python": platform.python_version()},
           "cases": []}
    for kind, name, arg in cases:
        size_mb = round(Path(arg).stat().st_size / 1e6, 2) if kind == "file" else None
        r = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), kind, arg], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            out["cases"].append({"case": name, "error": r.stderr[-400:]})
            print(name, "ERROR", r.stderr[-200:])
            continue
        res = json.loads(r.stdout.strip().splitlines()[-1])
        res.update(case=name, file_mb=size_mb)
        out["cases"].append(res)
        slow = sorted(res["tools"], key=lambda t: -t[2])[:3]
        print(f"{name:<18} file {size_mb} MB  pipeline {res['pipeline_s']} s  cpu {res['cpu_s']} s  "
              f"peak RSS {res['peak_rss_mb']} MB  verdict {res['verdict']}  slowest {slow}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("saved", args.out)


if __name__ == "__main__":
    main()
