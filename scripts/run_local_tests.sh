#!/usr/bin/env bash
# Satyapan: every LOCAL test in one command. No API keys needed. Nothing is uploaded anywhere.
#
#   bash scripts/run_local_tests.sh            full run (about 6 to 10 minutes on a laptop)
#   bash scripts/run_local_tests.sh --quick    skip the slow index-scaling and performance steps
#
# What each step is (none of these is a LIVE API test, see scripts/run_integration_tests.sh):
#   unit          pytest: unit and component tests. Offline by design. Network calls fail fast
#                 and are recorded as BLOCKED or AUTH_REQUIRED (test_api tolerates both).
#   adversarial   attempts to force wrong verdicts, network forced off (mocked transport)
#   llm           prompt-injected LLM simulated by a LOCAL fake server (mocked LLM)
#   leakage       secrets echoed back by a LOCAL mock service
#   e2e           scenarios A to H through the real pipeline. External APIs are called if this
#                 machine has network and keys, otherwise recorded as BLOCKED or AUTH_REQUIRED
#   image_eval    reuse matching on dev (tuned) and held-out (never tuned) image sets
#   security      against a real uvicorn server on 127.0.0.1 (safe payloads, local only)
#   concurrency   budget race in-process, then 8 simultaneous image jobs on the local server
#   performance   wall time, CPU and peak memory per input type (this machine only)
#   scaling       recall and latency as the known-media index grows past 250 items
#   dataset       manifest validator on the template (reports how many rows are still empty)
# Logs: results/audit/run_<UTC time>/  (one log per step, env.txt, SUMMARY.txt)
set -u
cd "$(dirname "$0")/.."
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUN="results/audit/run_$TS"
mkdir -p "$RUN"
PY=${PYTHON:-python}
export SATYAPAN_RETRIES=0
[ -f tests/media/tessdata/eng.traineddata ] && export TESSDATA_PREFIX="$PWD/tests/media/tessdata"
CPUS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo "?")

{
  echo "run started $TS (UTC)"
  echo "host: $(uname -a)"
  echo "cpus: $CPUS"
  if [ "$(uname)" = "Darwin" ]; then echo "memory: $(( $(sysctl -n hw.memsize) / 1048576 )) MB"; \
  else echo "memory: $(awk '/MemTotal/ {print int($2/1024)" MB"}' /proc/meminfo)"; fi
  echo "python: $($PY --version 2>&1)"
  echo "tesseract: $(tesseract --version 2>&1 | head -1)"
  echo "tesseract langs: $(tesseract --list-langs 2>/dev/null | tail -n +2 | tr '\n' ' ')"
  echo "ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
  echo "keys configured (names only): $(grep -E '^(GOOGLE_API_KEY|URLSCAN_API_KEY|SIGHTENGINE_USER|LLM_BASE_URL)=.+' .env 2>/dev/null | cut -d= -f1 | tr '\n' ' ')"
  echo "--- pip freeze"; $PY -m pip freeze 2>/dev/null
} > "$RUN/env.txt"

declare -a NAMES CODES
step() {   # step <name> <command...>
  local name=$1; shift
  echo "=== $name: $*"
  { echo "### $(date -u +%FT%TZ) $name: $*"; "$@"; } > "$RUN/$name.log" 2>&1
  local code=$?
  NAMES+=("$name"); CODES+=("$code")
  echo "    exit $code, log $RUN/$name.log"
}

[ -d tests/media/images ] || step fetch_test_media $PY scripts/fetch_test_media.py
step fetch_heldout $PY scripts/fetch_heldout_images.py --out data/heldout

step unit         $PY -m pytest -o addopts="" -q -rA
step adversarial  $PY audit/adversarial_verdicts.py --out "$RUN/adversarial_verdicts.json"
step llm          $PY audit/llm_injection.py
step leakage      $PY audit/key_leakage.py
step e2e          $PY audit/e2e_scenarios.py --heldout-dir data/heldout --out "$RUN/e2e_scenarios.json"
step image_dev    $PY audit/image_eval.py --set dev --dir tests/media/images --out "$RUN/image_eval_dev.json"
step image_heldout $PY audit/image_eval.py --set heldout --dir data/heldout --out "$RUN/image_eval_heldout.json"

# a real server on a local port with its own empty data folder
PORT=${SATYAPAN_TEST_PORT:-8799}
SDATA=$(mktemp -d)
SATYAPAN_DATA_DIR="$SDATA" $PY -m uvicorn satyapan.api.app:app --host 127.0.0.1 --port "$PORT" > "$RUN/uvicorn.log" 2>&1 &
SPID=$!
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.5; done
step security     $PY audit/security_practical.py --server "http://127.0.0.1:$PORT" --data-dir "$SDATA" \
                  --log "$RUN/uvicorn.log" --out "$RUN/security_practical.json"
$PY -c "from PIL import Image; Image.open('data/heldout/building.jpg').convert('RGB').resize((4000, 3000)).save('$SDATA/big12mp.jpg', quality=85)"
sleep 61   # let the per-IP rate limit (10 POSTs/minute) refill after the security step
step concurrency  $PY audit/concurrency.py --server "http://127.0.0.1:$PORT" --pid "$SPID" \
                  --image "$SDATA/big12mp.jpg" --n 8 --out "$RUN/concurrency.json"
kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null

if [ $QUICK -eq 0 ]; then
  step performance $PY audit/performance.py --heldout-dir data/heldout --out "$RUN/performance.json"
  step scaling     $PY audit/index_scaling.py --heldout-dir data/heldout --dev-dir tests/media/images \
                   --out "$RUN/index_scaling.json"
fi
step dataset      $PY audit/dataset_audit.py --out "$RUN/dataset_validation.json"

{
  echo "Satyapan local test run $TS on $(uname -s) with $CPUS CPUs"
  for i in "${!NAMES[@]}"; do
    f="$RUN/${NAMES[$i]}.log"
    p=$(grep -cE '^(PASS|OK)\b' "$f" 2>/dev/null); x=$(grep -cE '^FAIL\b' "$f" 2>/dev/null)
    printf "%-14s exit %-3s PASS/OK lines %-4s FAIL lines %-4s %s\n" "${NAMES[$i]}" "${CODES[$i]}" "$p" "$x" \
      "$(grep -E 'passed|failed|scenarios correct|behaved correctly|checks passed|precision|concurrent investigations|files verified|rows, |^audio:' "$f" | tail -1 | cut -c1-110)"
  done
  echo "Expected while the dataset is empty: 'dataset' warns that all rows are empty templates."
  echo "Expected e2e FAIL lines: B2 (paraphrase, lexical limit) and, without network or keys, D4 (Safe Browsing)."
  echo "e2e therefore exits 1 on this kind of machine. Any OTHER failure is a regression."
} | tee "$RUN/SUMMARY.txt"
