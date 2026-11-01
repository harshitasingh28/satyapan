"""Audio (module 7).

What we can do honestly
  * Probe and decode audio safely (FFmpeg, timeouts, duration limit).
  * Fingerprint audio to find RECYCLED clips (an old speech re-shared with a new
    claim). Landmark hashing over spectrogram peaks, the same family as Shazam.
What we cannot do reliably
  * Detect cloned or synthetic voices. Published detectors degrade sharply on
    real-world audio (see docs/MEDIA_FORENSICS.md). Unless an operator plugs in
    a detector AND it passes our calibration test, voice authenticity is
    reported as UNVERIFIED with that limitation stated.
"""
from __future__ import annotations

import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import ndimage, signal

SR = 8000
NFFT = 1024
HOP = 256
FAN_OUT = 10
DT_MAX = 64            # frames (~2 s at 8 kHz / 256 hop)
PEAK_NEIGHBOURHOOD = (15, 15)
MIN_ALIGNED = 15       # aligned hash hits needed to call a match


def decode(path: Path, max_seconds: int = 180, timeout: float = 60) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", str(max_seconds),
                          "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True,
                         timeout=timeout, check=False)
    if out.returncode != 0:
        raise ValueError(f"ffmpeg could not decode audio: {out.stderr.decode()[:160]}")
    return np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def peaks(samples: np.ndarray) -> list[tuple[int, int]]:
    _, _, z = signal.stft(samples, fs=SR, nperseg=NFFT, noverlap=NFFT - HOP)
    spec = 20 * np.log10(np.abs(z) + 1e-10)
    local_max = ndimage.maximum_filter(spec, size=PEAK_NEIGHBOURHOOD) == spec
    floor = np.percentile(spec, 90)
    fs, ts = np.nonzero(local_max & (spec > floor))
    order = np.argsort(ts)
    return list(zip(ts[order].tolist(), fs[order].tolist()))


def fingerprint(samples: np.ndarray) -> list[tuple[int, int]]:
    """Return (hash, anchor_time) pairs."""
    pk = peaks(samples)
    out = []
    for i, (t1, f1) in enumerate(pk):
        for t2, f2 in pk[i + 1:i + 1 + FAN_OUT]:
            dt = t2 - t1
            if 0 < dt <= DT_MAX:
                out.append(((f1 << 20) | (f2 << 8) | dt, t1))
    return out


class AudioIndex:
    def __init__(self) -> None:
        self.table: dict[int, list[tuple[str, int]]] = defaultdict(list)
        self.meta: dict[str, dict] = {}

    def add(self, item_id: str, path: Path, **meta) -> int:
        fp = fingerprint(decode(path))
        for h, t in fp:
            self.table[h].append((item_id, t))
        self.meta[item_id] = {**meta, "hashes": len(fp)}
        return len(fp)

    def query(self, path: Path) -> list[dict]:
        fp = fingerprint(decode(path))
        votes: dict[str, Counter] = defaultdict(Counter)
        for h, tq in fp:
            for item_id, tdb in self.table.get(h, []):
                votes[item_id][tdb - tq] += 1
        results = []
        for item_id, offsets in votes.items():
            offset, aligned = offsets.most_common(1)[0]
            results.append({"id": item_id, "aligned_hits": aligned, "offset_s": round(offset * HOP / SR, 2),
                            "query_hashes": len(fp), "match": aligned >= MIN_ALIGNED, "meta": self.meta[item_id]})
        return sorted(results, key=lambda r: -r["aligned_hits"])

    def save(self, folder: Path) -> None:
        """Store fingerprints only (hashes and anchor times), never the audio itself."""
        import json
        folder.mkdir(parents=True, exist_ok=True)
        ids = list(self.meta)
        pos = {item_id: i for i, item_id in enumerate(ids)}
        rows = [(h, pos[item_id], t) for h, entries in self.table.items() for item_id, t in entries]
        arr = np.array(rows, dtype=np.int64).reshape(-1, 3)
        np.savez_compressed(folder / "fingerprints.npz", rows=arr)
        (folder / "index.json").write_text(json.dumps({"ids": ids, "meta": self.meta, "sr": SR, "hop": HOP,
                                                       "min_aligned": MIN_ALIGNED}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    @classmethod
    def load(cls, folder: Path) -> "AudioIndex":
        import json
        info = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        if info.get("sr") != SR or info.get("hop") != HOP:
            raise ValueError("audio index was built with different fingerprint settings, rebuild it")
        idx = cls()
        idx.meta = info["meta"]
        ids = info["ids"]
        with np.load(folder / "fingerprints.npz") as data:
            for h, i, t in data["rows"].tolist():
                idx.table[h].append((ids[i], t))
        return idx


def voice_authenticity(path: Path) -> dict:
    """Default: UNVERIFIED. An optional detector runs only if configured AND calibrated."""
    model = os.getenv("AUDIO_DETECTOR_MODEL", "").strip()
    calibrated = os.getenv("AUDIO_DETECTOR_CALIBRATED", "0") == "1"
    if not model:
        return {"status": "UNVERIFIED", "score": None,
                "limitation": "No voice-clone detector is configured. Published detectors generalise poorly "
                              "to real-world audio, so Satyapan does not judge whether a voice is synthetic."}
    try:
        from transformers import pipeline  # optional dependency
    except ImportError:
        return {"status": "UNVERIFIED", "score": None, "limitation": "transformers not installed"}
    clf = pipeline("audio-classification", model=model)
    labels = clf(str(path))
    return {"status": "SIGNAL_ONLY" if not calibrated else "CALIBRATED_SIGNAL", "raw": labels,
            "limitation": "Detector output is a signal. It is not used in the verdict unless calibration passed."}
