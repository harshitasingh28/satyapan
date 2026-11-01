# Test results

> **Audit update (31 Oct 2026).** An end-to-end audit found and fixed 23 bugs after this page was written. Where this page and `docs/FINAL_TEST_AUDIT.md` disagree, the audit is right.

**Environment:** our build workspace on 31 Oct 2026.
- Linux x86_64, 2 vCPU, Python 3.13, Tesseract 5.3.4, FFmpeg 6.1.
- Network blocked except PyPI and GitHub raw files.

Raw outputs are in `results/build_env/`. A MacBook Air will give different timings.

## 1. Local tests: 66 passed, 0 failed, 0 skipped

`python -m pytest`. Full list in `results/build_env/pytest_output.txt`.

| File | Tests | What they prove (all on real public media unless noted) |
|---|---|---|
| test_security.py | 30 | 18 unsafe URLs rejected, public URLs accepted, DNS-rebinding and redirect refusal (logic-tested with a fake resolver and transport), magic-byte sniffing, truncated JPEG and disguised script rejected, 81 MP decompression bomb rejected, EXIF/GPS stripped, key redaction, host allowlist, HTTP status mapping (mock transport), rate limit, daily budget |
| test_pipeline.py | 15 | Independence counting, 7 verdict-rule cases, the citation validator (drops invented numbers, links, ids and wrong-stance citations), full graph offline in four cases, conflict self-correction, LangGraph runner identical to the plain runner |
| test_media.py | 7 | Image index (resize+JPEG, off-centre crop, screenshot, rotation), index save and load, C2PA, video keyframes on a re-encoded cropped clip, audio fingerprints on LibriSpeech, voice authenticity UNVERIFIED, OCR on rendered Hindi and English |
| test_claims.py | 6 | URL, phone, amount and call-to-action extraction (Hindi, English, Telugu), language detection, LLM grounding rejects invented claims, BM25 keeps Hindi words whole |
| test_links.py | 4 | Official domains, allowlist, `pmkisan-gov.top`, `uidai.gov.in.verify-aadhaar.xyz`, typo lookalike, punycode Cyrillic homoglyph, shortener, private target |
| test_api.py | 4 | FastAPI end to end, empty input 400, bad file reported as INPUT_ERROR, unknown id and path tricks 404, rate limit 429 |

The four offline graph cases:
- an impersonating link gives FAKE,
- an official record with matching amounts gives GENUINE, and a different amount does not,
- no evidence gives UNVERIFIED,
- a cropped forward of a debunked image gives FAKE.

**Failure we kept:** the first run failed because a low-texture microscopy image cropped to its top-left 60% did not match. The unit test now uses a natural photo, and the benchmark below reports every image, including the misses.

## 2. Provenance benchmark (local, real sample photos)

`python eval/provenance_benchmark.py tests/media/images --holdout 5`. The index held 12 scikit-image sample photos, and 5 more were held out as negatives (15 negative queries).

| Variant | recall@1, pHash only | recall@1, pHash + ORB | Wrong ids returned |
|---|---|---|---|
| resize 50% + JPEG q35 | 92% | 92% | 0 |
| JPEG q15 | 92% | 100% | 0 |
| thumbnail 256 px | 92% | 92% | 0 |
| centre crop 80% | 92% | 100% | 0 |
| off-centre crop 60% | **0%** | 83% | 0 |
| screenshot frame (chat UI + caption) | **0%** | 83% | 0 |
| red caption banner | 83% | 100% | 0 |
| rotation 4° | 17% | 92% | 0 |
| grayscale | 100% | 100% | 0 |
| mirror (mirrored-query fallback) | 100% | 100% | 0 |

Held-out false matches: **0 of 15**. Indexing takes about 37 ms per image. Query time was p50 64 ms and p95 172 ms with 12 items.

**Every miss involves the same two low-texture images** (a motion-blurred clock and a microscopy slide).

**Honesty notes:**
- **The thresholds were tuned on this set.** The first run had 6 wrong ids and 1 held-out false match, all caused by degenerate ORB fits. We then added three sanity checks (determinant, anisotropy and spread), so these numbers are optimistic.
- Re-measure on a fresh held-out set of the team's real forwarded images before quoting them.
- This measures reuse matching only, not deepfake detection.

## 3. Other local measurements

| Check | Result |
|---|---|
| Audio fingerprint, 6 s excerpt of speech A at 16 kbps Opus | match A, offset 3.01 s (true 3.0), 192 aligned hits |
| Audio fingerprint, 5 s excerpt of speech B at 32 kbps MP3 | match B, offset 2.02 s (true 2.0), 118 hits |
| Audio fingerprint, unrelated music | no match (at most 2 hits, threshold 15) |
| Audio query time | about 0.1 s. Indexing two clips: 254 ms |
| OCR, rendered Hindi + English (Noto font) | exact text in 224 ms. **Rendered text, not a real screenshot** |
| OCR, rendered Telugu | exact text in 47 ms. Same caveat |
| C2PA inspect | about 4 ms. Signed fixture read, unsigned "none", re-encoded "none" |
| Video keyframes, 60 s 720p | 6 distinct frames in 1.5 s |
| ORB verification | about 4 ms per indexed image, which is why brute force is capped at 250 items |
| CLI, scam text, offline | FAKE from one strong local evidence item. Fact-check and Safe Browsing listed as unavailable |
| CLI, screenshot image, offline | OCR, then claim and URL, then impersonation, then FAKE, with all limitations listed |

## 4. External integrations: no live success, honestly

`python -m integration.run_all` was run twice.

**Run A, no keys** (`results/build_env/integration_no_keys/`)

| Status | Tests |
|---|---|
| AUTH_REQUIRED (request not sent) | factcheck_search, factcheck_image_search, safe_browsing_v5, safe_browsing_v4, urlscan_quotas |
| BLOCKED (sent, refused by the workspace proxy with 403, not the service) | rdap_bootstrap, rdap_domain, wikidata_sparql, pib_rss |
| NOT_TESTED (third-party upload not allowed in this run) | urlscan_scan, sightengine_genai, cloud_vision_web, llm_claim_extraction |

**Run B, placeholder keys with `--allow-third-party`** (`results/build_env/integration_placeholder_keys/`)

- Every key-based request was really sent: Fact Check (search and image), Safe Browsing v5 and v4, urlscan quotas and scan, and Sightengine.
- All were BLOCKED by the proxy. The recorded URLs show `key=REDACTED`.
- Cloud Vision and the LLM were not configured, so they show AUTH_REQUIRED with the request not sent.
- `genuine_external` is false everywhere.

**Separate probes (not counted as tests):** a summarising web fetcher returned these on 31 Oct 2026:
- RDAP data for `uidai.gov.in` and `google.co.in`,
- the PIB RSS feeds (20 items, no dates, and the documented English URL returned Hindi titles),
- the public t.me preview of the PIB channel.

These show the endpoints exist. They are not raw HTTP tests.

## 5. Not tested at all

- Every external API live.
- urlscan timing.
- Sightengine accuracy on our data.
- Cloud Vision provenance hit rate.
- LLM extraction quality.
- OCR on real WhatsApp screenshots.
- The guarded fetch over a real network.
- Deployment on Render or Cloud Run.
- The evaluation dataset, which does not exist yet.
- Voice-clone and video-deepfake detectors, which were not attempted by design.
