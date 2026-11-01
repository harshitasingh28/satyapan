"""Create MongoDB indexes (including the TTL indexes) and print what exists. Safe to re-run.

Usage: python scripts/init_db.py          (needs MONGODB_URI in .env)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from satyapan.config import get_settings  # noqa: E402
from satyapan.db.mongo import MongoStore  # noqa: E402
from satyapan.logging_setup import redact  # noqa: E402


def main() -> None:
    s = get_settings()
    if not s.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set in .env")
    try:
        st = MongoStore.connect(s.mongodb_uri, s.mongodb_db)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"could not connect: {type(exc).__name__}: {redact(str(exc))[:200]}")
    print(f"connected to database {s.mongodb_db!r}, retention {s.retention_hours} h")
    for name in sorted(st.db.list_collection_names()):
        idx = st.db[name].index_information()
        ttl = [k for k, v in idx.items() if "expireAfterSeconds" in v]
        print(f"  {name:<22} {st.db[name].estimated_document_count():>6} docs  indexes {sorted(idx)}  TTL {ttl or '-'}")


if __name__ == "__main__":
    main()
