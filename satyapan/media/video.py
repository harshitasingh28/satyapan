"""Video (module 6): keyframes with FFmpeg, then image provenance per frame.

This finds RECYCLED video (an old clip re-shared with a new claim) through its
frames. It does NOT detect face swaps, lip-sync edits or cloned voices.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import imagehash
from PIL import Image


def _ffmpeg(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, timeout=timeout, check=False)


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=15, check=False)
    data = json.loads(out.stdout or "{}")
    st = (data.get("streams") or [{}])[0]
    return {"duration_s": float(data.get("format", {}).get("duration") or 0), "width": st.get("width"),
            "height": st.get("height")}


def keyframes(path: Path, out_dir: Path, scene: float = 0.3, max_frames: int = 8, dedupe: int = 6) -> dict:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found (brew install ffmpeg)")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    info = probe(path)
    start = time.perf_counter()
    scale = "scale='min(1280,iw)':-2"
    _ffmpeg(["-i", str(path), "-frames:v", "1", str(out_dir / "f000_first.jpg")])
    res = _ffmpeg(["-i", str(path), "-vf", f"select='gt(scene,{scene})',{scale}", "-fps_mode", "vfr",
                   "-frames:v", str(max_frames), str(out_dir / "scene_%03d.jpg")])
    if res.returncode != 0 and "fps_mode" in res.stderr:
        _ffmpeg(["-i", str(path), "-vf", f"select='gt(scene,{scene})',{scale}", "-vsync", "vfr",
                 "-frames:v", str(max_frames), str(out_dir / "scene_%03d.jpg")])
    method = "scene"
    if len(list(out_dir.glob("scene_*.jpg"))) < 2 and info["duration_s"] > 0:
        rate = min(1.0, max_frames / info["duration_s"])
        _ffmpeg(["-i", str(path), "-vf", f"fps={rate:.4f},{scale}", "-frames:v", str(max_frames),
                 str(out_dir / "uniform_%03d.jpg")])
        method = "uniform_fallback"
    kept, hashes = [], []
    for frame in sorted(out_dir.glob("*.jpg")):
        with Image.open(frame) as im:
            h = imagehash.phash(im)
        if all(h - o > dedupe for o in hashes):
            kept.append(frame)
            hashes.append(h)
        else:
            frame.unlink()
    return {"frames": kept, "method": method, "extract_s": round(time.perf_counter() - start, 2), **info}
