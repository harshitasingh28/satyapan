# Architecture

## Satyapan 2.0 (1 Nov 2026)

```
Browser (Next.js, no secrets) ──POST multipart──> FastAPI /v1/investigations/stream
        ^                                                   │ the pipeline runs inside this request
        └──────── server-sent events (real node events) ────┤ and every node start/end is streamed
                                                            ▼
validate_input → extract_claims → check_factchecks → check_official → investigate_links → analyse_media
   → compare_evidence → rank_evidence → [resolve_conflict] → decide → write_report → validate_citations
                                                            │
     Hugging Face router (chat + feature extraction) ◄──────┤
     Google Fact Check, Safe Browsing, RDAP, Wikidata ◄─────┤
     MongoDB Atlas (records with TTL, corpus, events) ◄─────┘
```

| Node | 2.0 change |
|---|---|
| extract_claims | Rules plus HF chat (with consent). Every AI claim must be quoted from the message |
| check_factchecks | Lexical matching as before. Reviews and curated debunks that may be the same claim in other words or another language become CANDIDATES (lexical 70 to 84, or embedding cosine above `SATYAPAN_SEMANTIC_CANDIDATE`, provisional 0.80) |
| check_official | Route 1 (every title word, no added negation) as before, plus: PIB link to a different release gives `link_mismatch`, old release with "today / breaking / आज / ఈరోజు" gives `outdated`, unknown linked PRID downgrades to moderate. Hybrid BM25 plus embedding search adds candidates |
| compare_evidence | New. One HF chat call labels each candidate (`supports`, `contradicts`, `insufficient`, same subject or not) with a quote from both texts. Code rejects any quote not found in its text. Verified labels: veto Route 1, allow Route 2 (message links the exact release, facts match), confirm a semantic fact-check match (with no conflicting numbers or dates) |
| analyse_media | Image matches get a tier. Only exact or modified copies (a similarity or affine map explains at least 80% of the keypoint matches, set on the dev set) are evidence. Similar scenes are shown, never counted |
| write_report | Template statements copied from evidence (`verified_fact`) always, plus a validated AI explanation (`ai_explanation`) |

The verdict is still made only by `satyapan/pipeline/verdict.py`. See README "What decides each verdict".

Storage: `satyapan/storage.py` (JSON files) and `satyapan/db/mongo.py` (Atlas). Collections: investigations, extracted_claims, evidence, verification_results, workflow_events, media_analysis (all with TTL on `expires_at`), source_documents (corpus), embedding_cache (vectors of public texts only). Each record is opened only with the random token returned at creation. Only its SHA-256 hash is stored.

---

## Feasibility prototype (31 Oct 2026)

The goal is the simplest system that can honestly deliver a working T1-D demo. Every component below exists in this repository and has a test, unless it is marked **planned**.

## Shape

```
Next.js UI (planned) ──HTTP──> FastAPI (satyapan/api/app.py)
                                  │  validates input, saves uploads, starts a background run
                                  ▼
                     State graph (satyapan/pipeline/graph.py)
 validate_input → extract_claims → check_factchecks → check_official → investigate_links
   → analyse_media → rank_evidence → [resolve_conflict, once] → decide → write_report → validate_citations
                                  │
          ┌───────────────────────┼────────────────────────────────────────┐
     local algorithms                     allowlisted APIs only (satyapan/http.py)
     claims, OCR (Tesseract),             Fact Check Tools, Safe Browsing v5 (v4 fallback),
     BM25 index of PIB releases,          RDAP via IANA bootstrap, Wikidata (offline allowlist build),
     domain rules, pHash + ORB index,     PIB RSS (ingest job), urlscan, Sightengine, Cloud Vision,
     C2PA, FFmpeg keyframes,              optional OpenAI-compatible LLM
     audio fingerprints
```

## Components

| Component | Purpose | Input to output | External calls | Failure handling |
|---|---|---|---|---|
| `api/app.py` | HTTP entry point | multipart form to investigation id, then report | none | 400 for empty input, 413 for oversize, 429 by token bucket, errors stored as `status: error` |
| `security/uploads.py` | Trust bytes, not names | file to `MediaInfo` | none (local ffprobe) | rejection recorded as `INPUT_ERROR` and listed in limitations |
| `security/ssrf.py` | URL safety | URL to ok or reason | none by default | unsafe links are analysed lexically but never sent anywhere |
| `claims.py`, `ocr.py` | Module 1, claim extraction | text and screenshots to `Claim` list | none | OCR missing becomes `NOT_TESTED` and is noted |
| `llm.py` | Optional structured extraction and rewrite | text to claims that are quoted from the source | LLM endpoint, only with consent | any LLM failure falls back to deterministic output |
| `sources/factcheck.py` | Module 2, fact-check search | claim to ClaimReview list | Fact Check Tools | `AUTH_REQUIRED`, `BLOCKED`, `SERVICE_ERROR` recorded, verdict continues |
| `sources/pib.py`, `textindex.py` | Module 2, official records | claim to best PIB release (BM25) | none at query time, RSS ingest is a separate job | empty store means no official evidence |
| `sources/official.py` | gov.in rule, allowlist, Wikidata | domain to official or not | Wikidata, only in `scripts/build_allowlist.py` | allowlist is reviewed by a human |
| `links/*` | Module 3 | URL to flags, registration age, advisories, sandbox verdict | RDAP, Safe Browsing, urlscan (consent, background) | each tool independent, failures listed |
| `media/image_index.py` | Module 4 | image to matches in the known-debunk index | none | low-texture images can miss (measured) |
| `media/remote.py` | Module 4 | sanitised image to web pages or AI score | Cloud Vision, Sightengine, consent only | daily budgets protect free tiers |
| `media/c2pa_inspect.py` | Module 5 | file to credentials status | none (remote manifests need network) | absence never counts as evidence |
| `media/video.py` | Module 6 | video to distinct keyframes | none | scene detection with uniform fallback |
| `media/audio.py` | Module 7 | audio to fingerprint matches, authenticity UNVERIFIED | none | voice-clone detection is off unless calibrated |
| `pipeline/evidence.py` | Modules 8 and 9 | evidence to scores per independent group | none | duplicates of one source count once |
| `pipeline/verdict.py` | Module 10 | scores to GENUINE, FAKE or UNVERIFIED | none | conflict or thin evidence gives UNVERIFIED |
| `pipeline/citations.py` | Module 11 | statements to cited statements | none | uncited statements are dropped, a verdict with no surviving statement becomes UNVERIFIED |
| `logging_setup.py`, `http.py` | Module 12 | JSON logs, call records | n/a | keys redacted from URLs, headers and errors |
| `storage.py` | Persistence | JSON per investigation, uploads deleted after 24 h | none | MongoDB Atlas M0 planned for hosting |

## How evidence becomes a verdict

Each tool writes `Evidence` with a stance (supports, contradicts, neutral), a strength, a plain statement of what it established, a source and an independence key.

| Evidence | Stance and strength |
|---|---|
| Fact-check from a listed fact-checker, rated false or misleading, similarity at least 85 | contradicts, strong (moderate if the publisher is not in `factcheckers.txt`, weak if similarity is 70 to 85) |
| Match in our known-debunk text index, similarity at least 85 | contradicts, strong |
| Image or audio matches media from a known debunk | contradicts, strong |
| Message invokes government or a scheme and links to a non-official domain that imitates a SPECIFIC official one (official domain inside another host, close lookalike or homoglyph, an official name such as `pmkisan` as a label part, an official name in userinfo or behind a backslash trick) | contradicts, strong |
| Same, with only a generic signal ("gov" in a non-gov.in name, an official name as a fragment, a punycode host that is not a close lookalike) | contradicts, moderate |
| Same, without any imitation signal, but the message asks people to act through the link (click, register, apply now, KYC, OTP; not "share" or "forward") | contradicts, weak |
| Foreign government domains (`state.gov`, `gov.uk`) | flagged as foreign government, never as impersonation |
| Safe Browsing advisory, or urlscan malicious verdict | contradicts, strong |
| C2PA says generative AI was used | contradicts, moderate |
| C2PA credentials present but fail validation (file changed after signing) | contradicts, moderate |
| Domain registered less than 90 days ago, or not registered at all | contradicts, weak |
| AI-image score at least 0.9, **only if the detector passed calibration** | contradicts, weak (otherwise neutral) |
| PIB release matches at least 70% of claim terms, EVERY content word of the release title is in the message, no added negation, amounts agree exactly (numbers compared as values, so Rs 200 never matches Rs 2000, and lakh and crore count), English and numeric dates agree, all links official and none redirects elsewhere | supports, strong |
| Link on an official domain that carries a redirect to another site (`?url=`, `next=`) | contradicts, moderate. The target is analysed as its own link |
| A related PIB release with different details | neutral (shown as context, never as confirmation) |
| Link is on gov.in, nic.in or the allowlist | supports, weak |

All lexical link rules share one independence key (`url_rules`): two suspicious links in one message are one source, not two.

Rules (`pipeline/verdict.py`):
- **FAKE:** contradiction score at least 3 and no strong support.
- **GENUINE:** strong support and zero contradiction.
- **UNVERIFIED:** everything else.

When strong evidence points both ways, `resolve_conflict` runs once. It demands stricter matches, re-scores, and gives UNVERIFIED if the conflict remains. The unit of judgement is the message: a message that impersonates an official source is FAKE even if the scheme it names exists.

## Why not LangGraph by default

All nodes are deterministic, so a 20-line runner is enough and easier to test. `pipeline/graph_langgraph.py` wires the same nodes into LangGraph, and a test checks both runners give identical verdicts and evidence. LangGraph earns its place when:
- an LLM planner chooses tools,
- a paused investigation must resume when urlscan finishes, using checkpointing,
- or a human reviewer must approve before publishing, using interrupts.

## Deployment (planned, not tested)

| Option | Fit | Evidence |
|---|---|---|
| Vercel Hobby for the Next.js UI | yes | "restricted to non-commercial personal use only" |
| Google Cloud Run for the backend container (FFmpeg, OpenCV, Tesseract) | best, if a card is available | free monthly allowance, "Verify that billing is enabled" |
| Render free web service | risky | 512 MB RAM and sleeps after 15 minutes idle, wake "about one minute". FFmpeg plus OpenCV in 512 MB is untested |
| MongoDB Atlas M0 | yes | 512 MB, at most 3 search or vector indexes |

Run a deploy smoke test with a real video before choosing.
