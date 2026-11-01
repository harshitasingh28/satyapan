# Hackathon implementation roadmap

Stages, each with an exit check. Do not start a stage until the previous exit check passes.

## Stage 0: prove the external services (day 1)
1. Run `scripts/setup_macos.sh`, fill `.env`, then run `python -m pytest`. The exit check is all 66 tests passing on the MacBook.
2. Run `python -m integration.run_all`, then `python -m integration.run_all --allow-third-party`.
3. **Exit check:**
   - LIVE_SUCCESS for factcheck_search, safe_browsing_v5 (or v4), rdap_domain, wikidata_sparql and pib_rss.
   - Find out from `pib_rss` which feed URL gives English titles.
   - Record real latencies in `docs/TEST_RESULTS.md`.
4. **If Fact Check search is not LIVE_SUCCESS**, F1 recall rests on the hand-curated index only. Say so.

## Stage 1: data (days 1 to 3, in parallel with stage 2)
1. Run `python scripts/ingest_pib.py` hourly (cron or launchd).
2. Curate at least 60 known debunks with links into `data/known_debunks.csv`, at least 25 of them with media. Then run `python scripts/build_known_index.py`.
3. Fill the 30 **dev** rows of `eval/manifest.csv`, then run `eval/validate_manifest.py`.
4. Build the detector set: 20+20 dev and 40+40 test images, each with a real WhatsApp-forwarded copy.

## Stage 2: tune on dev (days 3 to 5)
1. Loop on `python eval/run_eval.py --split dev`, then `eval/metrics.py`, then error analysis.
2. Change only thresholds and rules, and note each change.
3. Run `python eval/detector_eval.py`. Set `AI_IMAGE_DETECTOR_CALIBRATED=1` **only** if it says `may_enter_verdicts: true`.
4. **Exit check:** zero dev G items called FAKE.

## Stage 3: freeze and test (day 5)
1. Fill the 70 **test** rows (a different person collects them, from stories not used in dev).
2. Run `python eval/run_eval.py --split test --frozen` once. Fill `provenance_review.csv`, then run `eval/metrics.py`.
3. Put the real numbers, with their confidence intervals, in the pitch.

## Stage 4: product (days 4 to 7)
1. **Next.js UI.** Build three screens:
   - a submission screen with consent checkboxes,
   - a live trace that polls `GET /v1/investigations/{id}` and shows each node and tool status,
   - a report screen showing the verdict, cited reasons, media assessment, limitations and "Advisory provided by Google" where relevant.
2. **Telugu, Hindi and English report text.** Use the templates. An LLM rewrite only goes through the citation validator.
3. **Optional LLM.** Use local Ollama for privacy, or Gemini with consent and no personal data.
4. **Deploy the backend container** (Cloud Run if a card is available, else Render). Run a smoke test with a real video and a screenshot.

## Stage 5: demo hardening (last 2 days)
1. Prepare 6 live inputs from the **test** set that judges can check: one per category G, F1, F2, R, V, U.
2. **Practise the failure path.** Turn off Wi-Fi mid-demo and show the verdict degrading to UNVERIFIED with listed limitations, not a crash.
3. Set `SATYAPAN_RETRIES=0` for the demo, and pre-warm the host.
4. **Say what it does not do.** "We do not detect cloned voices or face swaps. Here is the evidence that nobody reliably can at our scale."

## Cut first if time runs out
In this order:
1. urlscan
2. Cloud Vision
3. LLM rewrite
4. Telugu UI strings
5. the audio index

Keep:
- claims and OCR,
- the fact-check API,
- the PIB index,
- link analysis,
- the image index,
- C2PA,
- the verdict gate,
- citations.
