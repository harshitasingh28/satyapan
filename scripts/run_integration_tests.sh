#!/usr/bin/env bash
# Satyapan: LIVE integration tests against the real external APIs. Run on your own machine.
#
#   bash scripts/run_integration_tests.sh                 keyless and key-based READS only
#   bash scripts/run_integration_tests.sh --allow-third-party
#        also SENDS public test data (a public test image, Google's Safe Browsing test URL,
#        example.com) to urlscan.io, Sightengine, Cloud Vision and the LLM provider.
#
# Credentials go in .env (copy .env.example). Names only, never commit the values:
#   GOOGLE_API_KEY        Fact Check Tools API + Safe Browsing API enabled on the same Cloud project
#   URLSCAN_API_KEY       free urlscan.io account
#   SIGHTENGINE_USER / SIGHTENGINE_SECRET   free Sightengine account
#   GOOGLE_VISION_API_KEY (or VISION_USE_GCLOUD=1 + GOOGLE_CLOUD_PROJECT)  needs billing enabled
#   LLM_BASE_URL / LLM_API_KEY / LLM_MODEL  any OpenAI-compatible endpoint (optional)
# Keyless: RDAP (IANA bootstrap), Wikidata SPARQL, PIB RSS.
# Every result is labelled LIVE_SUCCESS, AUTH_REQUIRED, RATE_LIMITED, BLOCKED, SERVICE_ERROR or
# NOT_TESTED. Nothing is mocked here. Results: results/audit/integration_<UTC time>/
set -u
cd "$(dirname "$0")/.."
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="results/audit/integration_$TS"
mkdir -p "$OUT"
PY=${PYTHON:-python}
{
  echo "integration run $TS (UTC) on $(uname -a)"
  echo "python: $($PY --version 2>&1)"
  echo "keys configured (names only): $(grep -E '^[A-Z_]+=.+' .env 2>/dev/null | cut -d= -f1 | tr '\n' ' ')"
} > "$OUT/env.txt"
$PY -m integration.run_all "$@" --summary SUMMARY.md 2>&1 | tee "$OUT/run.log"
code=${PIPESTATUS[0]}
cp integration_results/*.json integration_results/SUMMARY.md "$OUT/" 2>/dev/null
echo "results copied to $OUT (exit $code)"
exit "$code"
