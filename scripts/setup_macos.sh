#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon or Intel). Run from the project root.
set -e
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew install python@3.12 ffmpeg tesseract tesseract-lang
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -r requirements-optional.txt
[ -f .env ] || cp .env.example .env
mkdir -p data
for f in official_domains.txt factcheckers.txt official_bodies.txt; do [ -f data/$f ] || cp templates/$f data/$f; done
[ -f data/known_debunks.csv ] || cp templates/known_debunks_template.csv data/known_debunks.csv
[ -f eval/manifest.csv ] || cp eval/manifest_template.csv eval/manifest.csv
[ -f eval/detector_manifest.csv ] || cp eval/detector_manifest_template.csv eval/detector_manifest.csv
python scripts/fetch_test_media.py
echo "Setup done. Next: source .venv/bin/activate && python -m pytest"
