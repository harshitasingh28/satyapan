"""Request rate limiting and per-tool daily budgets that protect free-tier quotas."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path

try:
    import fcntl          # macOS and Linux: also serialise across uvicorn worker processes
except ImportError:       # pragma: no cover  (Windows)
    fcntl = None

_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """One lock per budget file for the whole process (each request builds its own DailyBudget)."""
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        return _FILE_LOCKS.setdefault(key, threading.Lock())

# Operator-chosen daily caps, set below each provider's free limit.
DEFAULT_DAILY_BUDGET = {
    "sightengine_genai": 80,       # free plan: 2,000 operations/month, max 500/day, ~5 ops per call
    "cloud_vision_web": 30,        # 1,000 free units/month
    "urlscan_scan": 100,
    "virustotal_url": 400,         # public API: 500/day, 4/minute
}


class TokenBucket:
    def __init__(self, per_minute: int) -> None:
        self.capacity = max(1, per_minute)
        self.rate = self.capacity / 60.0
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1, now)
            return True


class DailyBudget:
    def __init__(self, path: Path, limits: dict[str, int] | None = None) -> None:
        self.path = path
        self.limits = limits or DEFAULT_DAILY_BUDGET
        self._lock = _lock_for(path)

    def _load(self) -> dict:
        today = {"day": date.today().isoformat(), "used": {}}
        if not self.path.exists():
            return today
        try:
            data = json.loads(self.path.read_text())
        except (ValueError, OSError):
            # Corrupt file (for example written by an old version): keep it for inspection, start a
            # new count. Spending is capped again from here on.
            self.path.replace(self.path.with_suffix(".corrupt.json"))
            return today
        return data if data.get("day") == today["day"] and isinstance(data.get("used"), dict) else today

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.path)          # atomic: readers never see a half-written file

    def take(self, tool: str, amount: int = 1) -> bool:
        if tool not in self.limits:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.path.with_suffix(".lock"), "a") as lock_fh:
            if fcntl:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
            data = self._load()
            used = data["used"].get(tool, 0)
            if used + amount > self.limits[tool]:
                return False
            data["used"][tool] = used + amount
            self._save(data)
            return True
