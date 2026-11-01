# Satyapan: complete end-to-end testing and independent verification

Audit round of 30 to 31 Oct 2026 (UTC). The goal was to break Satyapan, not to praise it.
Every number below comes from a log or JSON file in `results/audit/` or `audit_logs/`.
The reference run for "after" figures is `results/audit/run_20261030T222654Z/`, made with
`bash scripts/run_local_tests.sh` on the final code (its `SUMMARY.txt` lists every step). Its
security step was rerun once after a bug in the audit script was fixed (section H). An
independent fact-checking agent compared this report with the raw files, and the 12 problems
it found were corrected before delivery.
Where something could not be run, it says NOT_TESTED or BLOCKED and gives the reason.

**Verdict of this audit: CONDITIONAL GO** (section M). 23 bugs were found and fixed. 7 of
them produced a false accusation or a false reassurance in a test (K1, K2, K3, K18, K21, K22, K23),
2 more hid real evidence (K6, K20), and 1 made every concurrent investigation fail (K9). An independent tester who never saw the
code still found 6 failures on first contact, which is the best measure of how much is still
unknown. No external API has been verified live, the dataset does not exist yet, and image
reuse matching gives false matches on different photos of the same scene.

Contents: A Environment, B Test suite audit, C Live APIs, D End-to-end scenarios,
E Image matching, F Deepfake and synthetic media, G Verdict engine, H Security,
I Performance, J Dataset and leakage, K Critical bugs and fixes, L Remaining blockers,
M Final recommendation. Appendices: exact commands, files changed.

---

## A. Environment

| Item | Value |
|---|---|
| Source | `satyapan-feasibility.zip`, SHA-256 `157e30f7ee9cdce1f06c45f08ea91ed867e7f461acc1297cbb16cf58daff4ed5`, extracted fresh |
| Machine | Cloud workspace: Ubuntu 24.04.5 LTS, Linux 6.18 x86_64, **2 vCPU, 8 GB RAM**. Not a MacBook |
| Python | 3.12.3 in a new venv (`python3.12 -m venv .venv`) |
| Install | the steps of `scripts/setup_macos.sh` without Homebrew: `pip install -r requirements.txt -r requirements-dev.txt`, then `python scripts/fetch_test_media.py`. `pip check`: no broken requirements |
| Native tools | Tesseract 5.3.4 (eng, hin, tel), FFmpeg 6.1.1 |
| Network | Outbound traffic goes through an egress proxy that allows PyPI and GitHub raw files only. **Every API host is refused with HTTP 403 by the proxy.** No live API test was possible here |
| Exact versions | `audit_logs/requirements.lock.txt` (72 packages, `pip freeze`) |

**Finding A1: requirements are not pinned.** A fresh install on 30 Oct 2026 pulled
pillow 13.0.0, numpy 2.5.4, starlette 1.10.0, fastapi 0.162.0, opencv-python-headless
5.0.0.93 and c2pa-python 0.38.1. Everything passed with these versions, but a team
member installing next week can get different ones. Use the lock file for the demo
machine: `pip install -r audit_logs/requirements.lock.txt`.

**Clean-room check of the delivered ZIP:** extracted into an empty folder, new venv,
`pip install -r audit_logs/requirements.lock.txt`, `python scripts/fetch_test_media.py`, then
95 of 95 tests, 16 of 16 adversarial cases and 25 of 25 independent cases passed
(`audit_logs/37_clean_room_zip_check.log`).

Logs: `audit_logs/00_environment.log`, `audit_logs/01_setup.log`, and `env.txt` in every
`results/audit/run_*` folder (OS, CPUs, memory, Python, Tesseract languages, FFmpeg,
`pip freeze`, and the NAMES of configured keys, never their values).

---

## B. Test suite audit

### B1. The 66 tests exist and run

`python -m pytest -o addopts="" -q` on the untouched code: **66 collected, 66 passed,
0 skipped, 0 failed, in 10.0 s** (`audit_logs/02_pytest_baseline_full.log`).
Nothing was skipped because the test media and Tesseract language data were fetched first.
Without them, media tests SKIP with a reason (`tests/conftest.py`, `need()`), they never pass silently.

### B2. What the 66 tests really are

| Observation | Detail | Risk |
|---|---|---|
| 66 tests, **41 distinct functions** | `test_rejects_unsafe_urls` is 18 parametrised cases, `test_verdict_rules` 7, `test_status_mapping` 3 | The count overstates coverage |
| Graph tests use a **mocked offline transport** | Every external call fails on purpose. Correct for degradation tests, labelled in the docstring | They cannot show that live evidence is parsed correctly |
| Status mapping and `guarded_fetch` tests are **mocked** | Fake responses and a fake resolver | Logic only. The live DNS-rebinding path is untested |
| Decompression-bomb test uses an **81 MP** image | Pillow raises only above 2x the 40 MP limit | It hid the 40 to 80 MP gap (bug K10) |
| `test_api` makes **real network calls** (RDAP) and accepts `FAKE` or `UNVERIFIED` | Result depends on the network of the machine | Not deterministic, weak assertion |
| No contract tests for the response parsers | factcheck, safebrowsing, rdap, urlscan, sightengine, vision | A changed API field would only show up live |
| Missing areas | retention, the 413 path, concurrency, audio-index persistence, key redaction in stored reports | Every one of these hid a real bug (section K) |
| No test is labelled LIVE | Correct. Live checks live only in `integration/run_all.py` | None |

### B3. After this round

`tests/test_audit_regressions.py` adds **29 tests**, one or more per bug in section K.
Full suite after the fixes: **95 collected, 95 passed** (70 distinct functions). To prove
that the new tests detect the bugs rather than pass trivially, they were also run against
the ORIGINAL code: 28 of 29 fail there, as they should
(`audit_logs/27_regression_tests_before_after.log`). The one that passes on both versions,
`test_k4_rating_words_from_the_evidence_are_allowed`, is a guard against over-correction.
`test_k9_ocr_keeps_a_caption_next_to_a_photo` guards the new OCR gate itself (the original
code had no gate).

---

## C. Live APIs

**No external API was tested live from this workspace.** Two real runs of
`python -m integration.run_all` were made (`audit_logs/15_integration_baseline.log`,
`results/audit/integration/`):

* Run A, no keys: key-based tests were not sent (AUTH_REQUIRED). Keyless requests were
  sent and refused by the workspace proxy (BLOCKED, HTTP 403 from the proxy, not from the service).
* Run B, placeholder keys and `--allow-third-party`: every request was sent and refused
  by the proxy (BLOCKED). The services never saw them.

The latencies in those logs (about 2.5 s, 7.5 s for the three PIB feeds) are the
proxy's refusal time. **They are not API latencies and must not be quoted as such.**

| API | Endpoint used by the code | Auth | Status here | What the live test checks (on your Mac) |
|---|---|---|---|---|
| Fact Check Tools, claims | `GET factchecktools.googleapis.com/v1alpha1/claims:search` | API key | AUTH_REQUIRED, then BLOCKED | a known false claim returns `claims[].claimReview[]` with publisher, URL, rating, date |
| Fact Check Tools, image | `GET .../v1alpha1/claims:imageSearch` | API key | AUTH_REQUIRED, then BLOCKED | a public image URL returns `results[]` |
| Safe Browsing v5 | `GET safebrowsing.googleapis.com/v5/urls:search?urls=...` | API key | AUTH_REQUIRED, then BLOCKED | Google's test URL `testsafebrowsing.appspot.com/s/phishing.html` is listed, `india.gov.in` is not |
| Safe Browsing v4 (fallback) | `POST .../v4/threatMatches:find` | API key | AUTH_REQUIRED, then BLOCKED | same pair of URLs |
| RDAP, including `.in` | IANA bootstrap `data.iana.org/rdap/dns.json`, then the registry | none | BLOCKED | bootstrap loads, `uidai.gov.in` returns a registration date from the `.in` registry |
| Wikidata SPARQL | `GET query.wikidata.org/sparql` | none (User-Agent) | BLOCKED | an official body returns its P856 website |
| PIB RSS | three feed variants (English documented, English variant, Hindi) | none | BLOCKED | items parse, and the test reports the SCRIPT of the titles and whether `pubDate` exists, because an earlier probe saw Hindi titles on the English URL and no dates |
| urlscan.io | `GET /user/quotas/`, `POST /api/v1/scan` (unlisted), poll result | API-Key header | AUTH_REQUIRED / NOT_TESTED, then BLOCKED | quota read, then a consented scan of `https://example.com` |
| Sightengine `genai` | `POST api.sightengine.com/1.0/check.json` | user + secret | NOT_TESTED, then BLOCKED | a public test image returns `type.ai_generated` |
| Cloud Vision Web Detection | `POST vision.googleapis.com/v1/images:annotate` | billing account | NOT_TESTED (run A, third-party upload not allowed), AUTH_REQUIRED (run B, not configured) | matching pages for a public image. **Cloud Vision OCR is not implemented.** OCR is local Tesseract |
| C2PA (local library) | c2pa-python 0.38.1 | none | **LOCAL_SUCCESS** | valid file (C.jpg, `Valid`, test signer), missing (A.jpg, `none`), modified (C.jpg with 20 bytes of image data changed, `Invalid`, codes `assertion.dataHash.mismatch`) |

The Safe Browsing reference was re-checked during the audit. Both
`v5/urls:search` and `v5alpha1/urls:search` are documented, the URL parameter is
repeated (`urls`), at most 50 URLs per call, the API is for non-commercial use, and
`urls.search` sends raw URLs to Google (`hashes.search` sends 4-byte hash prefixes).
If v5 returns an error, the code falls back to v4.

Free tiers, quotas and terms are in `docs/API_SOURCES.md` with their source pages.
**Cost:** everything used in the demo is free except Cloud Vision, which needs billing
(first 1,000 units a month free, per its pricing page). Daily budgets cap Sightengine
(80 calls), Vision (30) and urlscan (100) below their free limits.

**Exact command to run on the MacBook** (needs `.env` with the keys named in the script header):

```bash
bash scripts/run_integration_tests.sh                       # reads only
bash scripts/run_integration_tests.sh --allow-third-party   # also sends PUBLIC test data
```

Results land in `results/audit/integration_<UTC time>/` with one JSON per API (status,
HTTP code, latency, response field names, redacted error) and a `SUMMARY.md`.
Rate-limit and auth-error behaviour can only be observed there: the code maps 401 and 403
to AUTH_REQUIRED, 429 after retries to RATE_LIMITED, 5xx and timeouts to SERVICE_ERROR.

---

## D. End-to-end scenarios A to H

`audit/e2e_scenarios.py` runs the real pipeline (`Context.default()`, the same code path
as the API) on 15 inputs. The known-debunk index is built with the real
`scripts/build_known_index.py`. Fixtures:

* B: one REAL debunk, "The government has launched a scheme offering free laptops and is
  accepting applications for it", PIB Fact Check as reported by All India Radio,
  https://newsonair.gov.in/government-denies-launching-any-free-laptop-scheme-or-application-process/
* A: one REAL PIB release, "Government Ensures Continuity of Telecom Connectivity amid
  Cyclone Arnab", https://pib.gov.in/PressReleaseIframePage.aspx?PRID=2330702
* E, G, H: public test media registered as debunked items. These are **fixtures for the
  matching logic, not real debunks.**

No keys were configured in these runs. Key-based APIs (Fact Check, Safe Browsing) were therefore
NOT called and are recorded as AUTH_REQUIRED. Keyless RDAP was called and refused by the proxy (BLOCKED).

| ID | Input | Ground truth | Before | After | Correct | Evidence that decided it, or why it failed |
|---|---|---|---|---|---|---|
| A1 | official release title plus the official PIB link | TRUE | GENUINE | GENUINE | yes | PIB release index (strong support), official link (weak support) |
| A2 | paraphrased forward of the same release | TRUE | UNVERIFIED | UNVERIFIED | yes (abstains) | overlap below 70%, nothing else |
| B1 | the debunk wording | FALSE | FAKE | FAKE | yes | known-debunk index (strong) |
| B2 | "Free laptop yojana launched by government, applications open now, apply today" | FALSE | UNVERIFIED | UNVERIFIED | **no** | lexical similarity below 85. Paraphrase matching is a known limit, and live Fact Check search was unavailable |
| C1 | ATM closing rumour, no fact-check exists | UNRESOLVED | UNVERIFIED | UNVERIFIED | yes | nothing found, correctly no verdict |
| D1 | `https://pmkisan-gov.in.kyc-verify.top/...` | FALSE | FAKE | FAKE | yes | official name inside another domain (strong) |
| D2 | `https://xn--uida-o9d.in/` (homoglyph of uidai) | FALSE | FAKE | FAKE | yes | lookalike via homoglyph skeleton (strong) |
| D3 | `bit.ly` link, government relief claim | UNKNOWN | UNVERIFIED | UNVERIFIED | yes | redirect target unknown without urlscan |
| D4 | Google's Safe Browsing phishing test URL | MALICIOUS | UNVERIFIED | UNVERIFIED | **no** | needs Safe Browsing, BLOCKED here. Expected to pass live, NOT verified |
| E1 | screenshot of an indexed debunked image | REUSED | FAKE | FAKE | yes | known-media match, ORB (strong) |
| E2 | off-centre 60% crop of it | REUSED | FAKE | FAKE | yes | known-media match, ORB (strong) |
| F1 | copy-move splice of an image NOT in the index | MANIPULATED | UNVERIFIED | UNVERIFIED | yes (abstains) | no manipulation detector exists. Correctly no claim |
| F2 | C2PA-signed file changed after signing | MANIPULATED | UNVERIFIED, credentials reported as neutral | UNVERIFIED, credentials reported as **failing validation** (moderate) | **fixed** (K5) | `assertion.dataHash.mismatch` |
| G1 | slideshow video with the debunked image as one scene | REUSED | FAKE | FAKE | yes | keyframe matched the index (pHash and ORB) |
| H1 | 16 kbps Opus excerpt of indexed debunked audio | REUSED | UNVERIFIED | FAKE | **fixed** (K6) | audio index was never saved before the fix |

**Result: 11 of 15 before, 13 of 15 after.** The two failures left are a lexical limit (B2)
and a missing live API (D4). Full records with every tool call:
`results/audit/e2e_scenarios_BASELINE.json`, `results/audit/e2e_scenarios_AFTER.json`, and the
latest `results/audit/run_*/e2e_scenarios.json`.

---

## E. Image matching (reuse only)

This section measures **reuse matching**: is this image a copy of an image in our index of
debunked media. It says nothing about manipulation or AI generation (section F).

**Method.** `audit/image_eval.py`, thresholds frozen and written into each result file
(MIN_INLIERS 25, MIN_INLIER_RATIO 0.30, MIN_SPREAD 0.10, MAX_ANISOTROPY 3, crop scales 1.0, 0.9, 0.8).

* **Dev set:** 12 scikit-image photos plus 5 negatives. The shipped thresholds were tuned on
  these, so dev numbers are optimistic by construction.
* **Held-out set:** 51 OpenCV sample images at tag 4.10.0, fetched with SHA-256 checks by
  `scripts/fetch_heldout_images.py`. **Never used to tune anything.** 22 images are indexed.
  Negatives: 9 HARD (different photos of an indexed scene or object: aero3, graf3, left02 to
  left07, Blender_Suzanne2) and 8 easy, each queried as original, resized, JPEG 30 and screenshot.
  Excluded with reasons in the file: consecutive video frames (label ambiguous), box.png.
* Transforms per indexed image: original, resize 50%, JPEG quality 30, centre crop 70%,
  off-centre crop 55% (bottom right), screenshot with app bar, margins and text, tiled
  watermark, Gaussian blur 2.5, rotation 7 and 15 degrees, screenshot plus resize plus
  JPEG 50, mirror. Plus one natural crop shipped with OpenCV (lena_tmpl).
* Scoring: TP top-1 is the true source, FN nothing matched, WRONG another indexed image
  (counted as FN and FP), FP any match on a negative, TN no match.

| Set | Positives | Negatives | TP | FN | Wrong | FP | TN | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Dev (tuned) | 144 | 20 | 140 | 4 | 0 | 0 | 20 | 1.000 | 0.972 | 0.986 | 0.000 |
| **Held-out** | 265 | 68 | 257 | 8 | 0 | 15 | 53 | **0.945** | **0.970** | 0.957 | **0.221** |

Held-out, 95% Wilson intervals: recall 0.942 to 0.985, precision 0.911 to 0.966,
FPR 0.138 to 0.333. The positives are 12 transforms of 22 images, not independent samples,
so the true uncertainty is wider than these intervals.

| Held-out negatives | FP | TN | FPR |
|---|---|---|---|
| Hard (same scene or object, different photo) | 15 | 21 | **0.417** (Wilson 0.271 to 0.578) |
| Easy (unrelated images) | 0 | 32 | 0.000 (upper bound 0.094 by the rule of three) |

Per-transform recall on held-out: 100% for original, resize, JPEG 30, centre crop,
screenshot, watermark, blur, both rotations and mirror. **Off-centre 55% crop 72.7%**
(16 of 22), screenshot plus resize plus JPEG 90.9%, natural crop 1 of 1.
Query time with 22 items: p50 95.6 ms, p95 282.3 ms (reference run).

**What the false positives are.** 8 by ORB (graf3 matched graf1, the same graffiti wall from
another angle, Blender_Suzanne2 matched Suzanne1) and 7 by pHash at distance 0 (left04, 05
and 07 matched left01: different photos of the same chessboard). **The matcher detects "same
scene", not "same photograph".** For Satyapan that matters: a known-media match is STRONG
evidence, so a new, genuine photo of a place that appeared in an old debunk can be labelled
FAKE. This is a blocker (L3). It was not fixed in this round, because fixing it needs a dev
set with hard negatives and then a fresh held-out set. Tuning on these held-out images would
have made the held-out numbers meaningless.

**Index size cliff** (`audit/index_scaling.py`, reference run `scaling.log`, an earlier run in `audit_logs/26_index_scaling.log` agrees). The code
verifies every indexed image with ORB only while the index has at most 250 items. Above that,
ORB runs only on pHash candidates:

| Index items | ORB on every item | Query p50 | Resize 50% | Centre crop 70% | Off-centre crop 55% | Screenshot |
|---|---|---|---|---|---|---|
| 22 | yes | 74 ms | 100% | 100% | 72.7% | 100% |
| 100 | yes | 235 ms | 100% | 100% | 72.7% | 100% |
| 250 | yes | 584 ms | 100% | 100% | 72.7% | 100% |
| **251** | **no** | 58 ms | 100% | **27.3%** | **0%** | **0%** |
| 400 | no | 83 ms | 100% | 27.3% | 0% | 0% |

With more than 250 debunked images in the index, screenshots and crops of them are no longer
found. Keep the demo index under 250 images, or raise `orb_all_below` and accept about 2.3 ms
per item per query on this machine (L4).

---

## F. Deepfake and synthetic-media capabilities

| Capability | What exists | Tested how | Claimable at the demo? |
|---|---|---|---|
| Image reuse (old image, new claim) | pHash, dHash, ORB plus RANSAC against the debunk index | Section E | Yes, as "reuse of a known debunked image", with the same-scene caveat |
| Video reuse | FFmpeg keyframes, each frame through the image index | G1 | Yes, same caveat. Only reused frames, not edits |
| Audio reuse | Landmark fingerprints | H1 (16 kbps Opus excerpt matched). 170 s clip: index 0.8 to 1.1 s, query 0.8 to 1.1 s over two runs | Yes, as reuse of known audio |
| Image manipulation (splice, copy-move, inpainting) | **Nothing** | F1 abstains correctly | **No** |
| C2PA Content Credentials | Signer, validation state, AI declaration, and now validation failures | Valid, missing and modified files | Yes. Missing credentials prove nothing (messaging apps strip them) |
| AI-generated image detection | Sightengine `genai`, off without consent, evidence only if `AI_IMAGE_DETECTOR_CALIBRATED=1` | NOT_TESTED (blocked). Never calibrated | **No.** The score is now hidden until calibration (K17) |
| Voice cloning | Always UNVERIFIED with a stated limitation | Unit test | **No** |
| Video deepfakes (face swap, lip sync) | **Nothing** | n/a | **No** |

**Reuse matching is not deepfake detection** and the report text never calls it that.
Rename the T1-D pitch line accordingly: "provenance and reuse audit", not "deepfake detector".

---

## G. Verdict engine

### G1. Properties checked

| Property | How it was checked | Result |
|---|---|---|
| Every reason statement cites evidence ids that exist | citation validator, unit tests, LLM attack | Holds |
| Citations are real sources | statements are built from retrieved evidence, URLs not in the evidence are removed | Holds. Fixture sources are labelled FIXTURE |
| Reliability ranking | strong 3, moderate 2, weak 1, items sharing an independence key count once | Holds after K2. Before it, every suspicious link counted as a separate source |
| Conflicting evidence gives UNVERIFIED | unit test of `resolve_conflict` | Holds |
| One weak source cannot make FAKE | FAKE needs a score of at least 3 | Holds. Before K2, two moderate lexical items on two news links reached 4 and gave FAKE |
| Missing evidence gives UNVERIFIED | ADV08, ADV09, C1 | Holds |
| An API failure creates no evidence | every offline run checks that no evidence comes from an external tool | Holds in all 16 adversarial runs and all e2e runs |
| The LLM cannot invent sources, numbers or conclusions | local fake LLM (`audit/llm_injection.py`) | Before: a statement saying "This message is genuine and safe to share" survived. After K4: removed |
| No uncalibrated probability shown | read every place a score reaches the report | Before: the raw Sightengine score was shown in the evidence text and media assessment. After K17: hidden until calibrated. Verdict strength is only "high" or "medium", never a percentage |

### G2. Adversarial verdict attacks

`audit/adversarial_verdicts.py`, network forced off, so only local evidence counts.

| ID | Attack | Before | After |
|---|---|---|---|
| ADV01 | genuine MyGov message (`mygov.in`) | **FAKE** (false accusation) | UNVERIFIED |
| ADV02 | genuine news forward, two news links, "share" | **FAKE** | UNVERIFIED |
| ADV03 | a correct debunk being shared | UNVERIFIED | UNVERIFIED |
| ADV04 | US government site `travel.state.gov` | **FAKE** | UNVERIFIED |
| ADV05 | Rs 200 against an official Rs 2000 release | **GENUINE** (false reassurance) | UNVERIFIED |
| ADV06 | prompt injection in the message, no LLM | FAKE | FAKE |
| ADV07 | `https://pib.gov.in@evil-relief.top/` | UNVERIFIED | FAKE |
| ADV08 | shortener only | UNVERIFIED | UNVERIFIED |
| ADV09 | local rumour, no evidence | UNVERIFIED | UNVERIFIED |
| ADV10 | official message with official link only | UNVERIFIED | UNVERIFIED |
| ADV11 | homoglyph of pib, Cyrillic i (`xn--pb-hoc.in`) | see note | FAKE |
| ADV12 | Hindi paraphrase of an official release | GENUINE | GENUINE |
| ADV13 | punycode that is NOT a close lookalike (`xn--pb-lmc.in`, "pрb") | (new) | UNVERIFIED |
| ADV14 | backslash trick `http://x.com\@pib.gov.in/` | (new) | FAKE |
| ADV15 | generic "gov" name `pm-relief-gov.top` | (new) | UNVERIFIED |
| ADV16 | UK government site `gov.uk` | (new) | UNVERIFIED |

Before: **8 of 12** behaved acceptably (3 false accusations, 1 false reassurance). After:
**16 of 16.** Note on ADV11: the first run used `xn--pb-lmc.in`, which decodes to "pрb"
(Cyrillic er), not the Cyrillic i the case described. That was an error in the audit
script, found while fixing. It was corrected and the old input kept as ADV13.

**Honest caveat.** The fixes were developed against ADV01 to ADV12, so 16 of 16 is a
regression result, not an accuracy estimate. An independent tester that never saw these
cases or the code wrote its own attacks (G3).

**Trade-off accepted.** `pm-relief-gov.top` (ADV15) was FAKE before because any "gov" in a
non-gov.in name counted as strong impersonation. That same rule accused mygov.in and
state.gov. Now a generic "gov" is moderate, so this scam is UNVERIFIED offline and needs a
second signal (a domain under 90 days old or unregistered from RDAP, a Safe Browsing hit) to
become FAKE. A wrong FAKE on a genuine government message is the worse failure for a
verification tool, so this is the right trade.

### G3. Independent adversarial check

To avoid grading our own fixes, a separate agent wrote 25 new attack cases **before reading
any code**, from the written policy only (`docs/ARCHITECTURE.md`, `docs/LIMITATIONS.md`), and ran
them offline (`audit/independent_adversarial.py`, cases in `audit/independent_adversarial_cases.json`).
It was told not to change its acceptable verdicts after seeing results.

**Result on the code as fixed up to K17: 19 of 25.** That is the honest, unanchored figure.
Failures:

| Case | Input | Verdict | Acceptable | Severity | Root cause |
|---|---|---|---|---|---|
| I06 | genuine Hindi PM-KISAN message ending `https://pmkisan.gov.in।` | **FAKE** | UNVERIFIED | **false accusation** | the danda (।) became part of the host, so the official site looked like a lookalike. A common way to write Hindi, and present in the ORIGINAL code too |
| I21 | release says 15 December, message says 15 November | **GENUINE** | UNVERIFIED | **false reassurance** | dates were never compared |
| I24 | `https://uidai.gov.in/redirect?url=https%3A%2F%2Faadhaar-docs-update.top%2Flogin` plus a matching release | **GENUINE** | FAKE or UNVERIFIED | **false reassurance** | only the host was checked, not where the link sends people |
| I10 | zero-width space inside `pmkisan.gov.in.benefit-claim.top` | UNVERIFIED | FAKE | missed scam | browsers drop U+200B, our checks did not |
| I11 | full-width dots `uidai．gov．in．kyc-update．top` | UNVERIFIED | FAKE | missed scam | browsers map them to ".", our checks did not |
| I16 | 60,000-character forward with the scam link at the end | UNVERIFIED | FAKE | missed scam | text was cut at 5,000 characters BEFORE links were read |

After reading the code the tester tried three extra probes, not counted in its score. They are
kept as `audit/independent_probes.py` and were rerun on the ORIGINAL and the FIXED code
(`audit_logs/35_independent_probes_before_after.log`):

| Probe | Input | Original code | Fixed code |
|---|---|---|---|
| X1 | release title, filler past 5,000 characters, then a scam link | UNVERIFIED (the scam link was silently dropped) | FAKE |
| X2 | "Rs 5 crore" in the message, "Rs 5 lakh" in the release | **GENUINE** ("Rs 5 crore" was read as Rs 5) | UNVERIFIED |
| X3 | unencoded `?url=https://aadhaar-docs-update.top/login` on uidai.gov.in plus a matching release | **GENUINE** | UNVERIFIED |

The tester reported GENUINE for X1 on the intermediate code (fixed up to K17). That run was not
saved, so it is not counted here.

These findings became fixes K18 to K23. After them: **25 of 25**
(`audit_logs/31_independent_adversarial_before.log`, `audit_logs/32_independent_adversarial_after.log`).
The 25 cases are now development cases too, so 25 of 25 is a regression result. **The next
unanchored estimate needs another fresh set.** What held up in the independent run: foreign
gov.au links, licindia.in, sbi.co.in, onlinesbi.sbi, eciresults.nic.in, ports, trailing periods,
all-caps URLs, WhatsApp bold and emoji, a Cyrillic "о" in "gоv" in Telugu, IP-literal hosts,
official names only in the path, prompt injection, an added Rs 10,000, and a genuine warning
that quotes a known debunk.

### G4. LLM attack (`audit/llm_injection.py`, mocked LLM on 127.0.0.1)

The fake model proposes an invented claim, then rewrites the report with an invented
URL, an invented number, a statement contradicting the verdict and one valid statement.

| Check | Before | After |
|---|---|---|
| invented claim rejected (not quoted in the message) | pass | pass |
| invented URL dropped | pass | pass |
| invented number dropped | pass | pass |
| verdict-contradicting statement dropped | **fail** | pass |
| verdict decided by code | pass (checked against a fixed FAKE) | pass (checked against the same message with the LLM off, a stricter check) |

By design the LLM never adds evidence and runs after the verdict for the report text. It CAN
still influence the verdict in one way: claims it proposes (only if quoted word for word from the
message) may become the claim that gets checked. One fake-model scenario is not proof of more.

A real LLM provider was **NOT_TESTED** (no key, and the network is blocked).

---

## H. Security

All payloads were safe and local. Nothing was sent to a third party.
`audit/security_practical.py` (against a real uvicorn server), `audit/key_leakage.py`,
`audit/concurrency.py`, `tests/test_security.py`.

| Area | Test | Before | After |
|---|---|---|---|
| SSRF | 11 links to localhost, 127.0.0.1, `[::1]`, 169.254.169.254, 10.0.0.1, `2130706433`, file, gopher, javascript, data, ftp: did the server request itself? | pass (no request) | pass |
| SSRF | were unsafe links passed to RDAP, Safe Browsing or urlscan? | pass | pass |
| Private redirects, DNS rebinding | `guarded_fetch` (off by default) with a fake resolver and transport | pass (logic only) | pass (logic only). Live path NOT_TESTED |
| URL schemes | javascript, data, file, vbscript, jar | pass | pass |
| Punycode and homoglyphs | D2, ADV11, ADV13 | pass | pass |
| Parser differential | `http://x.com\@pib.gov.in/` | **fail**: parsed as pib.gov.in, so treated as OFFICIAL (the first audit check wrongly showed this as a pass) | pass: parsed as x.com, like a browser, flagged as impersonation |
| Crafted hosts | `evil%2F..%2Fadmin.com`, `a.b.com%23frag` reach the RDAP request path? | **fail** (`domain/%2fadmin.com` would be requested) | pass: invalid host, never sent, RDAP refuses it too |
| Oversized upload | 60 MB file | 413, but only after the whole body was read | 413 before reading (0.12 s) |
| Declared 2 GB body | raw socket, `Content-Length: 2147483648` | **fail**: connection held open waiting | pass: 413 at once |
| Missing Content-Length | chunked body | accepted (evidence: regression test K10 fails on the original code) | 411 |
| Decompression bomb | 60 MP PNG (limit 40 MP) | **fail**: accepted | pass |
| MIME spoofing, invalid media | script named `.jpg`, random bytes with an MP4 header, corrupt WAV, MP4 without video | pass | pass |
| Polyglot | JPEG with a ZIP appended | accepted, never executed, re-encoded before any upload | same (noted, not a failure) |
| Path traversal | client file name `../../../../tmp/satyapan_pwned.jpg`, ids `..%2F..%2Fetc%2Fpasswd`, `abc;rm` | pass | pass |
| Prompt injection | message text and fake LLM | pass for the verdict, fail for the report text | pass |
| Key leakage | a mock service echoes the key in its error body | **fail**: key stored in the report (`tool_runs.detail`) | pass: report, call records and logs clean |
| Unsafe logging | JSON logs with redaction, no message text logged | pass | pass |
| Retention | uploads after processing, records after 24 h, sweep scheduled? | **fail** (never deleted) | pass |
| Rate limiting | 12 rapid POSTs, 30 GETs | pass (10 then 429, GETs free) | pass |
| Rate limiting, spoofed `X-Forwarded-For` | 12 POSTs with a different fake XFF each (`audit_logs/33_xff_behaviour.log`) | **the first audit wrongly reported "spoofing ignored"** | From 127.0.0.1: all 12 accepted, the limit is bypassed, because uvicorn trusts XFF from loopback by default. From a non-loopback address: 10 accepted, then 429 |
| Rate limiting behind a proxy | which client address the limit uses | n/a | Proxy on the same host: correct client IP by default. Proxy on another host: start uvicorn with `--forwarded-allow-ips=<proxy IP>`, otherwise all users share one bucket. Never expose the app on a host where untrusted local processes run |
| Budget race | 8 threads, 40 attempts, limit 20 | **fail** (JSONDecodeError) | pass: exactly 20 |

The SSRF self-request payloads in the first audit script were hard-coded to port 8765. The
reference run's server used port 8799, so that one check proved nothing there. The script now
uses the server's real port and the security step was rerun (`results/audit/run_20261030T222654Z/security_portfix.log`,
21 of 21). The earlier runs on port 8765 (`audit_logs/08_security_baseline.log`,
`audit_logs/21_security_after.log`) were valid.

Security script totals: before 14 of 20 reported as passing, and one of those 14 was the
parser-differential bug passing a flawed check, so really 13 of 20. After: **21 of 21**.

**Not done, residual risk:** no authentication on the API (anyone who can reach it can submit
work, limited only by the rate limit), slow-body attacks within the 52 MB limit (uvicorn has no
body-read timeout, so put a reverse proxy with `client_body_timeout` in front), no antivirus
scanning, media parsers (FFmpeg, Pillow, Tesseract) are an attack surface, TLS is the
deployment's job. "The app starts" was never taken as evidence of security.

---

## I. Performance

All figures from this 2 vCPU x86 Linux workspace. **A MacBook will differ. No MacBook figure
is claimed.** External API latency is NOT measured (every call was refused by the proxy in
about 0.3 s per attempt with retries off). Each case runs in a fresh process.
`audit/performance.py`. Before: `audit_logs/12_performance_baseline.log`. After: the reference run's `performance.log`.

| Input | File | Before: time, peak memory | After: time, peak memory | Main cost |
|---|---|---|---|---|
| Text with a scam link | none | 0.31 s, 187 MB | 0.36 s, 188 MB | URL rules, RDAP refusal |
| Image 1 MP | 0.17 MB | 1.13 s, 187 MB | 1.11 s, 188 MB | Tesseract |
| Image 12 MP | 0.9 MB | 5.48 s, 223 MB | 4.27 s, 330 MB | Tesseract |
| Image 39 MP | 2.1 MB | 11.34 s, 327 MB | **4.38 s**, 327 MB | Tesseract, now on a downscaled copy |
| Video 60 s 720p | 11.8 MB | 4.65 s, 189 MB | 4.50 s, 189 MB | FFmpeg keyframes |
| Video 180 s 1080p | 35.5 MB | 19.6 s, 211 MB | 19.6 s, 211 MB | FFmpeg keyframes |
| Audio 180 s | 0.87 MB | **rejected** (ffprobe: 180.0065 s > 180 s limit, `audit_logs/34_audio_duration.log`) | 0.05 s (no audio index in this run) | validation only |
| Audio fingerprint, 170 s | n/a | n/a | index 1.10 s, query 1.12 s (0.77 and 0.79 s in a quieter run) | STFT peaks |

Peak memory counts the Python process only (Tesseract and FFmpeg run as child processes).
After the fix, the 12 MP image is decoded in Python for the downscale check, which is why its
peak rose while its time fell.

**Limits.** Images 10 MB and 40 MP, video 50 MB, audio 10 MB, 180 s (0.5 s tolerance), 4 files,
52 MB per request.

**Concurrency, 8 simultaneous 12 MP image investigations with consent on** (`audit/concurrency.py`):

| | Before | After |
|---|---|---|
| Finished | **0 of 8**: every job ended with `error: TimeoutExpired` after about 31.9 s | **8 of 8 done** |
| Why | 8 Tesseract processes, each multithreaded, on 2 CPUs. The OCR timeout raised `subprocess.TimeoutExpired`, which `_run` did not catch, so the whole investigation failed | Jobs queue (`SATYAPAN_MAX_CONCURRENT_JOBS`, default half the CPUs, here 1), Tesseract runs single-threaded, and a timeout is now a recorded tool failure |
| Time | n/a | single job 4.6 s, 8 jobs 44.4 s in total (the last waits for 7 others) |
| Server peak memory | 607 MB | 819 MB with default glibc (873 MB in an earlier run), **407 MB with `MALLOC_ARENA_MAX=2`** |

The memory growth came from glibc allocating a separate memory arena per worker thread.
`MALLOC_ARENA_MAX=2` is a Linux deployment setting. macOS uses a different allocator, not measured.

---

## J. Dataset and leakage

**The dataset has not been collected.** The claim manifest template has **0 of 100 rows filled**
and the detector manifest **0 of 120**. No accuracy, precision or recall figure for the
product exists, and none is claimed. The numbers in sections D, E and G are tests of
mechanisms on public images and hand-written messages, not accuracy on real forwards.

What was verified (`audit_logs/13_dataset_audit_baseline.log`):

* The plan is internally consistent: dev 30 and test 70 rows. Test-split ground truth: 21 TRUE,
  46 FALSE, 3 UNRESOLVED.
* Category M (FALSE claims where the expected verdict is UNVERIFIED) is a deliberate design
  choice, to measure safe abstention. Report it separately so it is not counted as an error.
* The detector plan has 20 AI and 20 real images in dev, 40 and 40 in test.
* Test-split thresholds are locked behind `--frozen` in `eval/run_eval.py`.

**Leakage finding K14.** The validator only caught exact duplicates (same SHA-256). A resized
copy of a dev image placed in test was NOT detected. Fixed: the validator now also runs the
product's own image matcher across splits and fuzzy-matches claim text (similarity 90 or more).
It over-reports on purpose (it inherits the matcher's same-scene false positives), so each
flagged pair is reviewed by eye and either moved or marked `leak-reviewed` in its notes.

---

## K. Critical bugs and fixes

Every product change was made after the baseline measurement, is listed here, and has a
regression test that fails on the original code (B3). K1 to K17 were found by our own attacks,
K18 to K23 by the independent tester (G3). Severity: **Critical** gives a wrong
verdict or loses the whole investigation, **High** is a security or data-handling defect,
**Medium** degrades results.

| ID | Severity | Bug (evidence before) | Fix | Files | Evidence after |
|---|---|---|---|---|---|
| K1 | Critical | Any "gov" in a non-gov.in host was STRONG impersonation: mygov.in and travel.state.gov messages became FAKE (ADV01, ADV04). Punycode alone was strong too | Strong only for signals that imitate a specific official site (official domain inside the host, lookalike, official label such as `pmkisan` as a whole part, official name in userinfo or behind a backslash). Generic "gov", fragments and non-lookalike punycode are moderate. Foreign government suffixes are never impersonation. `mygov.in` added to the allowlist with its source | `links/urlinfo.py`, `pipeline/graph.py`, `templates/official_domains.txt` | ADV01, ADV04, ADV16 UNVERIFIED. D1, D2, ADV11, ADV14 FAKE |
| K2 | Critical | "share" counted as a call to action through a link, and each link was a separate source: two news links gave FAKE (ADV02) | Only link actions count (click, register, apply, KYC, OTP), and only as weak. All lexical link rules share one independence key | `pipeline/graph.py` | ADV02 UNVERIFIED, test K2 |
| K3 | Critical | Amounts matched as substrings: Rs 200 was "consistent" with Rs 2000, giving GENUINE (ADV05) | Numbers compared as values, with lakh and crore applied | `claims.py`, `pipeline/graph.py` | ADV05 UNVERIFIED, Rs 2,000 still matches 2000 |
| K4 | Critical | An LLM rewrite saying "This message is genuine and safe to share" passed the citation check | New rules: no verdict word that disagrees with the verdict unless it is in the cited evidence, and at least 60% of content words must appear in the cited evidence | `pipeline/citations.py` | LLM attack 5 of 5 |
| K5 | High | C2PA credentials that FAIL validation (file changed after signing) were reported as neutral | Reported as moderate contradicting evidence, media assessment `CREDENTIALS_INVALID` | `pipeline/graph.py` | F2 |
| K6 | Critical | The audio index was built and never saved, and never loaded: audio reuse could never be found in the product | `AudioIndex.save` and `load` (fingerprints only), saved by `build_known_index.py`, loaded by `Context.default` | `media/audio.py`, `scripts/build_known_index.py`, `pipeline/graph.py` | H1 FAKE |
| K7 | High | An API key echoed by a service was stored in the report via `tool_runs.detail` | Every `ToolError` message is redacted on creation, `_run` redacts details, `redact()` also removes the literal value of every configured secret, the integration harness redacts errors | `errors.py`, `logging_setup.py`, `pipeline/graph.py`, `integration/run_all.py` | key leakage test clean, and the same test fails on the original code |
| K8 | High | `DailyBudget` raced: concurrent investigations raised JSONDecodeError, and the budget call sat outside the error handler | Process-wide lock per file, `fcntl` file lock, atomic write, corrupt file moved aside, budget never spent on an unconfigured tool, budget errors skip the tool | `security/ratelimit.py`, `pipeline/graph.py`, `media/remote.py` | 20 of 40 granted, no exceptions |
| K9 | Critical | Under load, `subprocess.TimeoutExpired` from Tesseract escaped `_run` and failed the whole investigation (0 of 8 finished). OCR on photos produced junk claims | `_run` catches every exception as a tool failure. Investigations queue. Tesseract single-threaded on a downscaled copy (JPEG draft decode). Line-level confidence gate | `pipeline/graph.py`, `api/app.py`, `config.py`, `ocr.py` | 8 of 8 done. Photos give no OCR text, captions next to photos survive |
| K10 | High | Images of 40 to 80 MP were accepted (Pillow only raises above 2x). Bodies were fully read before any size check. A declared 2 GB body held the connection | Explicit pixel check from the header. Middleware refuses a missing (411) or too large (413) Content-Length before reading | `security/uploads.py`, `api/app.py` | security checks pass |
| K11 | High | Retention was never enforced, and the sweep did not cover investigation records (user text) | Uploads and work files deleted when an investigation ends. Sweep covers records, runs at start-up and at most every 10 minutes. Records written atomically | `storage.py`, `api/app.py` | security checks pass |
| K12 | High | Crafted host names reached the RDAP request path. The backslash parser differential made `x.com\@pib.gov.in` look official | Browser-style backslash normalisation, strict DNS host check, invalid hosts are never official and never sent, RDAP refuses invalid names | `security/ssrf.py`, `sources/official.py`, `links/rdap.py`, `links/urlinfo.py` | security checks pass |
| K13 | Medium | A 180.0065 s file failed a 180 s limit | 0.5 s tolerance | `security/uploads.py` | 180 s audio accepted |
| K14 | Medium | Validator missed near-duplicate leakage | Cross-split image matching and fuzzy claim matching | `eval/validate_manifest.py` | test K14 |
| K15 | Medium | Reason statements were not ordered by strength | Strongest first | `pipeline/report.py` | test K15 |
| K16 | Critical | A fresh install loaded EMPTY allowlists (nothing copies the templates into `data/`), so rbi.org.in was not official and every fact-checker counted as unknown | `Context.default` falls back to the shipped lists | `pipeline/graph.py` | test K16 |
| K17 | High | An uncalibrated AI-detector score was shown as a number (reads like "97% AI") | Hidden unless `AI_IMAGE_DETECTOR_CALIBRATED=1`, kept only as `raw_score_for_calibration_only` | `pipeline/graph.py` | test K17 (mocked Sightengine reply) |
| K18 | Critical | A danda (।) after a URL became part of the host: a genuine Hindi message was FAKE (I06) | URLs end at the danda and other Unicode punctuation, and a host may only contain letters, marks, digits, "-" and "." | `claims.py`, `security/ssrf.py` | I06 UNVERIFIED |
| K19 | Medium | Zero-width and full-width characters hid an official name inside a scam host (I10, I11) | Links are normalised the way browsers do (format characters dropped, NFKC, ideographic full stop to "."), and the trick itself is a moderate signal | `security/ssrf.py`, `links/urlinfo.py`, `pipeline/graph.py` | I10, I11 FAKE |
| K20 | High | Text was cut at 5,000 characters before links were read, so a scam link at the end vanished (I16, X1) | Links after the cut are still extracted and checked | `pipeline/graph.py` | I16 and X1 FAKE |
| K21 | Critical | Dates were never compared: a release saying 15 December confirmed a message saying 15 November (I21) | Every English or numeric date in the claim must appear in the release. Hindi and Telugu month names are not parsed yet | `claims.py`, `pipeline/graph.py` | I21 UNVERIFIED, same date still GENUINE |
| K22 | Critical | An open redirect on an official domain counted as an official link (I24, X3) | Redirect targets inside links (`?url=`, `next=`, `/out/https://...`) are extracted and checked as links of their own. An official link that leads elsewhere is never official support and is moderate evidence against | `links/urlinfo.py`, `pipeline/graph.py` | I24 and X3 UNVERIFIED |
| K23 | Critical | "Rs 5 crore" was read as Rs 5: crore and lakh were dropped after a currency prefix (X2) | The amount pattern keeps the multiplier | `claims.py` | test K23 |

Changes to the audit tooling itself, recorded separately because they are not product fixes:
the ADV11 input was mislabelled (corrected, old input kept as ADV13), the LLM check now compares
with the no-LLM verdict instead of a fixed FAKE, the crafted-host check now tests what reaches
the request path instead of only the parsed string, the retention check now tests the sweep
directly, and the audit scripts now exit non-zero when a check fails.

API change: `POST /v1/investigations` now returns `status: "queued"`. Poll until the status is
neither `queued` nor `running`.

---

## L. Remaining blockers

| # | Blocker | Why it matters | What closes it |
|---|---|---|---|
| L1 | **No external API verified live** | Fact Check, Safe Browsing, RDAP and PIB are central to the demo. D4 depends on Safe Browsing | Run `scripts/run_integration_tests.sh` on the MacBook with keys. Every row must be LIVE_SUCCESS or have a known fallback |
| L2 | **Dataset not collected** (0 of 100, 0 of 120) | No accuracy claim is possible | Collect it, run `eval/validate_manifest.py` until clean, evaluate the test split once with `--frozen` |
| L3 | **Image reuse matches different photos of the same scene** (hard-negative FPR 0.417) | A genuine new photo of a place from an old debunk can be called FAKE | Short term: show a side-by-side comparison and say "matches a debunked image" in the UI. Proper fix: hard negatives in a new dev set, retune, then a NEW held-out set |
| L4 | Index cliff above 250 items | Crops and screenshots of debunked images stop matching | Keep the demo index under 250, or raise `orb_all_below` and measure |
| L5 | Paraphrases are not matched (B2) | Reworded false claims stay UNVERIFIED unless live Fact Check finds them | Accept for the demo, or add multilingual embeddings and measure on the dev split |
| L6 | No manipulation or deepfake detection | T1-D asks for it | Pitch it honestly as provenance and reuse. Do not claim detection |
| L7 | Performance on the MacBook unmeasured | The demo machine decides the latency | Run `bash scripts/run_local_tests.sh` on it |
| L8 | OCR accuracy on real WhatsApp screenshots unmeasured, gate values untuned | Screenshots are the main input type | Measure on the dev split of the dataset |
| L9 | No auth, no slow-body protection, single process, rate limit bypassable from the same host | Fine for a demo, not for a public link | Reverse proxy with timeouts and a shared secret before any public URL |
| L10 | LLM path tested with a fake model only | Wording quality and grounding pass rate unknown | Run with the chosen provider, or keep LLM off for the demo |

---

## M. Final recommendation

**CONDITIONAL GO.**

Evidence for GO-level confidence in the core:

* 95 of 95 tests pass. 29 new tests guard 23 fixed bugs, and 28 of them fail on the original code.
* 16 of 16 of our adversarial verdict attacks behave correctly offline, after 4 of 12 failed before.
* An independent tester's 25 attacks, written without seeing the code: 19 of 25 on first contact
  (1 false accusation, 2 false reassurances), 25 of 25 after the fixes.
* 21 of 21 practical security checks pass, after 7 real failures before.
* Under load, 8 of 8 concurrent jobs finish, after 0 of 8 before.
* 13 of 15 end-to-end scenarios are correct. The 2 failures are a known lexical limit and a blocked API.
* No API failure produced evidence in any run, and in the fake-LLM attack the verdict was the same with and without the LLM.

Why not GO:

* Not one external API has been seen working (L1).
* No dataset, so no accuracy (L2).
* A STRONG FAKE can come from a same-scene image match, with a measured 42% false-match rate
  on hard negatives (L3).

Conditions, in order, all before the demo:

1. `scripts/run_integration_tests.sh` on the MacBook: Fact Check, Safe Browsing (D4 must pass),
   RDAP for `.in` and PIB RSS must be LIVE_SUCCESS.
2. `scripts/run_local_tests.sh` on the MacBook with the lock file: all steps as in this report.
3. In the UI and the pitch, image matches are shown side by side as "matches a debunked image",
   and the pitch says "provenance and reuse", never "deepfake detection".
4. Collect at least the 30-row dev split and report results on it, labelled as dev results.

**NO-GO triggers:** Fact Check and Safe Browsing both unavailable on the demo network, or the
MacBook run showing any FAKE for a genuine message in the adversarial set.

---

## Appendix 1. Exact macOS commands

```bash
# one-time setup (Homebrew)
brew install python@3.12 tesseract tesseract-lang ffmpeg
cd satyapan-feasibility
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r audit_logs/requirements.lock.txt      # exact versions used in this audit
# or: pip install -r requirements.txt -r requirements-dev.txt   (unpinned, newest versions)
python scripts/fetch_test_media.py
python scripts/fetch_heldout_images.py
cp .env.example .env                                  # add keys for the integration run only

# every local test, no keys, nothing uploaded (6 to 10 minutes)
bash scripts/run_local_tests.sh
bash scripts/run_local_tests.sh --quick               # skips performance and index scaling

# live APIs
bash scripts/run_integration_tests.sh
bash scripts/run_integration_tests.sh --allow-third-party

# single pieces
python -m pytest -o addopts="" -q -rA                 # unit and component tests
python audit/adversarial_verdicts.py
python audit/e2e_scenarios.py --heldout-dir data/heldout
python audit/image_eval.py --set heldout --dir data/heldout
uvicorn satyapan.api.app:app --port 8765              # then, in a second terminal:
python audit/security_practical.py --server http://127.0.0.1:8765 --data-dir data --log <uvicorn log file>
```

Test types: **unit and component** (pytest, offline), **adversarial** (mocked transport),
**LLM attack** (mocked LLM), **leakage** (mocked echoing service), **end-to-end** (real pipeline,
real API calls when keys and network exist, otherwise AUTH_REQUIRED or BLOCKED), **security** (real local server), **concurrency** (real local server),
**performance** (this machine), **held-out evaluation** (frozen thresholds), **integration**
(LIVE, only `scripts/run_integration_tests.sh`).

## Appendix 2. Files changed in this round

Product code (18 files): `satyapan/api/app.py`, `satyapan/claims.py`, `satyapan/config.py`,
`satyapan/errors.py`, `satyapan/links/rdap.py`, `satyapan/links/urlinfo.py`,
`satyapan/logging_setup.py`, `satyapan/media/audio.py`, `satyapan/media/remote.py`,
`satyapan/ocr.py`, `satyapan/pipeline/citations.py`, `satyapan/pipeline/graph.py`,
`satyapan/pipeline/report.py`, `satyapan/security/ratelimit.py`, `satyapan/security/ssrf.py`,
`satyapan/security/uploads.py`, `satyapan/sources/official.py`, `satyapan/storage.py`.

Scripts, data and tests: `scripts/build_known_index.py`, `eval/validate_manifest.py`,
`integration/run_all.py`, `templates/official_domains.txt`, `tests/test_api.py` (polls the new
`queued` status). New: `tests/test_audit_regressions.py`, `scripts/run_local_tests.sh`,
`scripts/run_integration_tests.sh`, `scripts/fetch_heldout_images.py`.

Audit tooling (new folder `audit/`): `adversarial_verdicts.py`, `concurrency.py`,
`dataset_audit.py`, `e2e_scenarios.py`, `image_eval.py`, `index_scaling.py`, `key_leakage.py`,
`llm_injection.py`, `performance.py`, `security_practical.py`, and the independent tester's
`independent_adversarial.py` and `independent_adversarial_cases.json`, and `independent_probes.py`
(its three extra probes as a script).

Docs: `docs/FINAL_TEST_AUDIT.md` (new), `docs/ARCHITECTURE.md` (evidence table),
`docs/SECURITY.md` (corrected claims about uploads, redaction, retention, rate limiting),
`docs/LIMITATIONS.md` (impersonation trade-off), `docs/TEST_RESULTS.md` and
`docs/FINAL_REPORT.md` (pointer to this audit), `README.md` (test commands).

A line-by-line diff against the delivered ZIP is in `audit_logs/CHANGES.diff`.

---

## Addendum: first live API run on the team MacBook (31 Oct 2026, 21:32 IST)

`bash scripts/run_integration_tests.sh` on a MacBook Air (home network) with one Google API key
restricted to Fact Check Tools API and Safe Browsing API. Output as reported by the team
(results folder on that machine: `results/audit/integration_20261031T160230Z/`):

| Test | Status | HTTP | Latency | What it showed |
|---|---|---|---|---|
| factcheck_search | **LIVE_SUCCESS** | 200 | 488 ms | 1 review returned for "free laptop scheme government students". Coverage of Indian claims looks thin |
| factcheck_image_search | **LIVE_SUCCESS** | 200 | 581 ms | |
| safe_browsing_v5 | SERVICE_ERROR | 200 | 652 ms | Response is not JSON. Google's reference says v5 response bodies are protocol-buffer formatted. Satyapan falls back to v4 automatically |
| safe_browsing_v4 | **LIVE_SUCCESS** | 200 | 237 ms | Google's test phishing page flagged `SOCIAL_ENGINEERING`, `india.gov.in` not flagged. So scenario D4 works live |
| rdap_bootstrap | **LIVE_SUCCESS** | | 137 ms | |
| rdap_domain | **LIVE_SUCCESS** | | 504 ms | includes `.in` |
| wikidata_sparql | **LIVE_SUCCESS** | | 1,307 ms | |
| pib_rss | **refused** (reported as AUTH_REQUIRED) | 403, 403, 403 | 322 ms | PIB needs no key. Its server refused our client on all three feeds |
| urlscan, Sightengine, Cloud Vision, LLM | not run | | | no keys, third-party sends not allowed |

These are single requests from one machine, so the latencies are examples, not benchmarks.

**Changes made after this run** (tests: 97 passed, including 2 new ones in `tests/test_pib_ingest.py`):

* A 401 or 403 from PIB is now reported as BLOCKED with a hint, not AUTH_REQUIRED (`satyapan/sources/pib.py`).
* `scripts/ingest_pib.py` gained two manual paths: `--from-file` imports an RSS file saved from a
  browser through the same parser, and `--add --title ... --link ...` adds one release by hand
  (only `https://` links on pib.gov.in are accepted). We do not disguise the client as a browser to
  get past PIB's refusal.

**Status of the conditions in section M:** Fact Check, Safe Browsing (through v4) and RDAP for `.in`
are now verified live. PIB RSS is NOT: until the feed can be fetched or imported, the release index
is empty and Satyapan cannot reach a GENUINE verdict. The v5 Safe Browsing parser is an open item.

### Full local run on the team MacBook (31 Oct 2026, run `20261031T162951Z`, reported by the team)

MacBook Air, Apple Silicon, 8 CPUs, macOS, Python 3.12 (Homebrew), ffmpeg 9.0.2, Tesseract 5.5.4
(eng, hin, tel), Google API key configured. `bash scripts/run_local_tests.sh`:

| Step | Result |
|---|---|
| Unit and component tests | 97 passed, 0 skipped |
| Adversarial verdicts | 16 of 16 |
| LLM attack, key leakage | 5 of 5, 3 of 3 |
| End-to-end scenarios | **14 of 15**. D4 (Safe Browsing test page) is now FAKE through the live API. Only B2 (paraphrase) fails |
| Image reuse, dev and held-out | identical to the Linux runs (precision 0.945, recall 0.970, FPR 0.221 held-out) |
| Security | 21 of 21 |
| Concurrency | 8 of 8 done |
| Performance and index scaling | first crashed: `music.ogg` carries cover art, and Homebrew ffmpeg 9 has no Theora encoder to copy it into the test clip. Fixed with `-vn` in `audit/performance.py` and `audit/index_scaling.py`, then rerun |

Performance on the MacBook (one run, fresh process per case):

| Input | Time | Peak memory | Main cost |
|---|---|---|---|
| Text with a scam link, live APIs | 2.57 s | 128 MB | RDAP 1.09 s, Safe Browsing 0.74 s, Fact Check 0.63 s (real API latencies) |
| Image 1 MP | 1.35 s | 120 MB | Tesseract |
| Image 12 MP | 3.66 s | 261 MB | Tesseract |
| Image 39 MP | 2.11 s | 288 MB | Tesseract on the downscaled copy |
| Video 60 s 720p | 1.70 s | 120 MB | FFmpeg keyframes |
| Video 180 s 1080p | 8.02 s | 159 MB | FFmpeg keyframes |
| Audio fingerprint, 170 s clip | index 0.60 s, query 0.56 s | | |

The index cliff is the same on the MacBook: with 251 or more indexed images, screenshot and off-centre
crop recall drop to 0 (query p50 248 ms at 250 items, 38 ms at 251).

PIB: the RSS feed opens in Chrome on the same machine (Hindi feed checked), so PIB refuses scripts,
not people. The feeds are being saved from the browser and imported with `--from-file`.

### K24, found after the PIB import on the MacBook: one swapped word still got GENUINE

With 40 real releases imported from the browser-saved feeds (20 English, 20 Hindi), all 40 exact
titles with their official links came back GENUINE and none FAKE. That shows the GENUINE path works,
but it is the easiest possible case. A follow-up probe (`audit_logs/38_word_swap_probe.log`, fixture
releases modelled on those real titles) showed a **false reassurance**: a real title with one word
swapped ("Lowest" to "Highest", "Uphold" to "Abandon") or a negation added ("will NOT celebrate"),
plus the real PIB link, was GENUINE.

Causes: support needed only 70% of the message's words to be in the release, and the "names
something specific" check was satisfied by the letters "pib" inside the link.

Fix (`satyapan/pipeline/graph.py`, `title_confirmed`): a release confirms a message only if every
content word of the release title appears in the message (numbers and currency normalised, so
"Rs 1,09,019" matches "₹1,09,019"), and the message adds no negation that the release does not
contain. Extra framing words ("Breaking", "Read", "Share") are still allowed. A forward that
shortens or rewords the title is now UNVERIFIED, which is the strict side on purpose. Test fixtures
now carry `"fixture": true` instead of a "FIXTURE" prefix in the title, because the title words are
compared. Tests: 103 passed. The 6 new K24 tests: 3 fail on the original code (the swap, the
negation and the dropped word), 3 pass on both (exact title, framing words, number formats).
Adversarial 16 of 16, independent 25 of 25, probes X1 to X3 pass, end-to-end unchanged (A1 GENUINE).

Confirmed on the team MacBook after the K24 patch (31 Oct 2026, 23:40 IST): 103 passed. All 40 real
PIB releases (20 English, 20 Hindi, imported from browser-saved feeds) were run twice with live APIs:
the exact title with its link gave **GENUINE 40 of 40**, and the same title with a negation inserted
after the second word ("not", or "नहीं" for Hindi) gave **UNVERIFIED 40 of 40**. This is a check of
one tampering pattern on real titles, not an accuracy figure.
