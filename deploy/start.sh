#!/bin/sh
# Cloud Run start-up: the filesystem is temporary, so optional seed files (a known-media index built
# with scripts/build_known_index.py) are copied into the data folder, then the API starts.
set -e
mkdir -p "$SATYAPAN_DATA_DIR"
if [ -d /app/seed ] && [ "$(ls -A /app/seed | grep -v README.md)" ]; then
  cp -R -n /app/seed/. "$SATYAPAN_DATA_DIR"/ 2>/dev/null || true
fi
exec uvicorn satyapan.api.app:app --host 0.0.0.0 --port "${PORT:-8080}" --no-server-header --timeout-keep-alive 75
