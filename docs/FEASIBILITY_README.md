# Satyapan: feasibility build for Forge T1-D

Satyapan checks a suspicious government-related message, link, screenshot, image, video or audio clip against reliable sources. It returns **GENUINE**, **FAKE** or **UNVERIFIED**, with cited evidence and stated limitations.

Code decides the verdict. Language models never supply evidence.

## Honest status (31 Oct 2026, after the end-to-end audit in docs/FINAL_TEST_AUDIT.md)

| Area | Status |
|---|---|
| Local tests | **95 passed, 0 failed, 0 skipped** (`python -m pytest`), including 29 regression tests for the 23 bugs the audit found and fixed |
| Image, video and audio reuse matching | Held-out image set (never tuned on): precision 0.945, recall 0.970. **But 42% false matches on different photos of the same scene**, and crops and screenshots stop matching above 250 indexed images (docs/FINAL_TEST_AUDIT.md, section E) |
| External APIs | **Not one live success yet.** Our build workspace blocks the internet. Run `python -m integration.run_all` on your MacBook |
| Deepfake detection | **Not claimed.** Reuse, credentials and calibrated signals only (docs/MEDIA_FORENSICS.md) |
| Evaluation dataset | Planned (100 items, 30 dev and 70 test) with validator, runner and metrics. **Not collected, so no accuracy is claimed** |
| Recommendation | **CONDITIONAL GO** (docs/FINAL_TEST_AUDIT.md, section M) |

## Setup on a MacBook Air

```bash
# 1. Prerequisite: Homebrew (https://brew.sh)
# 2. From the project folder:
bash scripts/setup_macos.sh            # installs python@3.12, ffmpeg, tesseract + Hindi/Telugu, venv, test media
source .venv/bin/activate
python -m pytest                       # expect 95 passed
bash scripts/run_local_tests.sh        # every local test, logs in results/audit/run_<time>/
bash scripts/run_integration_tests.sh  # LIVE API checks (needs .env keys)
```

Fill `.env`. Every key is optional, and missing keys show as AUTH_REQUIRED.
- Google API key for Fact Check Tools and Safe Browsing:

  ```bash
  gcloud services enable factchecktools.googleapis.com safebrowsing.googleapis.com apikeys.googleapis.com
  gcloud services api-keys create --display-name=satyapan --api-target=service=factchecktools.googleapis.com --api-target=service=safebrowsing.googleapis.com
  ```

- Free accounts at urlscan.io and sightengine.com.
- Cloud Vision needs a billing-enabled project.

## Run

```bash
python -m integration.run_all                      # live API tests, writes integration_results/SUMMARY.md
python -m integration.run_all --allow-third-party  # also sends PUBLIC test media/URLs to urlscan, Sightengine, Vision, LLM
python scripts/ingest_pib.py                       # pull PIB press releases into the local index (run hourly)
python scripts/build_known_index.py                # build known-debunk indexes from data/known_debunks.csv
python -m satyapan.cli --text "PM Kisan gives Rs 10,000, apply at pmkisan-gov.top"
python -m satyapan.cli --file forward.jpg --consent-media
uvicorn satyapan.api.app:app --reload              # API for the Next.js UI
python eval/provenance_benchmark.py tests/media/images --holdout 5
```

## Layout

| Path | Contents |
|---|---|
| `satyapan/claims.py`, `ocr.py`, `llm.py` | Claim extraction, Tesseract OCR, optional grounded LLM |
| `satyapan/sources/` | Fact Check Tools, PIB RSS and BM25 index, official domains and Wikidata |
| `satyapan/links/` | URL analysis, Safe Browsing v5/v4, RDAP, urlscan |
| `satyapan/media/` | Image index (pHash+ORB), C2PA, remote image services, video keyframes, audio fingerprints |
| `satyapan/pipeline/` | Evidence ranking, verdict rules, citation validator, report, state graph, LangGraph wiring |
| `satyapan/security/` | URL safety (SSRF), upload validation, rate limits and budgets |
| `satyapan/api/app.py`, `cli.py` | FastAPI backend, command line |
| `integration/run_all.py` | Live tests with LIVE_SUCCESS, AUTH_REQUIRED, RATE_LIMITED, BLOCKED, SERVICE_ERROR, NOT_TESTED |
| `eval/` | Dataset plan and templates, validator, runner, metrics, provenance and detector benchmarks |
| `results/build_env/` | Raw outputs from our build environment (pytest, benchmark, integration runs) |
| `docs/` | ARCHITECTURE, API_SOURCES, MEDIA_FORENSICS, SECURITY, EVALUATION, TEST_RESULTS, LIMITATIONS, ROADMAP, FINAL_REPORT |

## Rules the code enforces

- **The backend never fetches a user-submitted URL.** It calls allowlisted API hosts only.
- **Third-party uploads happen only with explicit consent,** and images are stripped of metadata first.
- **Missing C2PA is never evidence.** A hash match is reuse, not a deepfake. A detector score counts only after calibration.
- **Every report statement cites stored evidence.** Statements with invented numbers or links are dropped.
- **No Telegram scraping, myScheme scraping or YouTube downloading,** because of their terms.

## Licences of test media

`scripts/fetch_test_media.py` downloads these, and none are redistributed in this archive:
- C2PA fixtures from contentauth/c2pa-python
- LibriSpeech and Kevin MacLeod audio via librosa/data
- scikit-image sample photos
- Tesseract tessdata_fast
- Noto fonts under the OFL
