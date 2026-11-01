# Satyapan feasibility audit: final report

> **Audit update (31 Oct 2026).** An end-to-end audit found and fixed 23 bugs after this page was written. Where this page and `docs/FINAL_TEST_AUDIT.md` disagree, the audit is right.

31 Oct 2026. Everything below separates what we **ran**, what we **read**, and what we **estimate**.

## 1. Critical evaluation of the idea

**T1-D text:** "A high-throughput verification platform that ingests live social feeds, multimodal media, and viral claims, cross-referencing them against verified database registries, knowledge graphs, and forensic models to detect synthetic media and trace misinformation provenance."

| T1-D requirement | How Satyapan addresses it | Status |
|---|---|---|
| High-throughput platform | FastAPI with background runs. The offline fast path takes milliseconds. ORB matching is capped at 250 brute-force comparisons | **Partial.** Throughput not measured. No queue |
| Ingests live social feeds | PIB RSS ingest, the Fact Check API as a live debunk feed, and user submissions | **Partial.** Telegram's terms forbid AI use of channel data. WhatsApp has no monitoring API |
| Multimodal media | Text, screenshots (OCR), images, video, audio | **Implemented, tested locally** |
| Viral claims | Claim extraction in Hindi, English and Telugu, with LLM grounding | **Tested locally** |
| Verified database registries | PIB releases, gov.in registry rule, RDAP, Safe Browsing, fact-check database | **Implemented. Live calls untested** |
| Knowledge graphs | Wikidata official websites (P856) build the allowlist | **Thin** |
| Forensic models to detect synthetic media | C2PA, AI-image detector as a calibrated signal. No video or voice deepfake detector | **Weakest part, by evidence-based choice** |
| Trace misinformation provenance | Image, video-frame and audio reuse matching, plus Cloud Vision web pages | **Strong locally**. No automatic dating |

**Achievable in a hackathon:**
- the verdict gate with citations,
- claim extraction and OCR,
- link impersonation analysis,
- the fact-check and PIB lookups,
- media reuse matching across image, video and audio,
- C2PA,
- a calibrated or clearly labelled AI-image signal,
- a measured 100-item evaluation.

**Difficult or impossible with current resources:**
- reliable deepfake video or voice-clone detection,
- live monitoring of WhatsApp or Telegram,
- automatic "first seen" dating,
- real throughput at scale,
- proven OCR accuracy on Telugu screenshots.

**Impressive-looking features that would not actually work (do not build):**
- a "deepfake score 97%" badge,
- voice-clone verdicts,
- a Telegram channel monitor (forbidden by its terms),
- automatic reporting to Chakshu or PIB (no API, so it would be simulated),
- myScheme scraping (forbidden),
- a "full knowledge graph of all schemes" (no source).

**Against the judging criteria** (personal estimate, not data):

| Criterion | Expected if the roadmap is delivered | What moves it |
|---|---|---|
| Technical Architecture (20) | 14 to 16 | State graph, SSRF-safe design, two-stage image index, audio fingerprints, citation validator, tests |
| AI Reasoning and Agentic (25) | 13 to 18 | Risk: the pipeline is mostly deterministic. Strengths: visible routing, self-correction, tool fallbacks, grounding and citation checks. An LLM planner would add points and risk |
| Impact and USP (25) | 16 to 19 | It refuses to guess, it is grounded in official sources, it shows provenance, and it states its limits |
| Live Demo (30) | 19 to 25 | Depends on stage 0 live tests, a prepared known index, and the offline-degradation path already proven |
| **Total** | **62 to 78** | |

**Is another T1-D direction stronger?**
- **Detector-first** (deepfake scores as the product): the evidence says no. The Meta challenge winner scored 65.18% on unseen data, and real-world audio degraded detectors by "up to one thousand percent".
- **An LLM fact-check chatbot with web search:** high hallucination risk, Google Custom Search is closed to new users, and the idea is crowded.
- **A claim-matching tool for newsrooms:** lower citizen impact and a weaker live demo.

Satyapan's provenance-first, evidence-gated design remains the strongest honest fit. It must be pitched as **verification and provenance audit**, not as a deepfake detector.

## A. Problem statement fit

**Partly yes.**
- **Strong:** registries, provenance, multimodal input, and evidence-backed verdicts.
- **Weak:** live social feeds and synthetic-media detection. The weakness is the state of the art and platform terms, not the code, and the report says so instead of hiding it.

## B. Technical feasibility

**Tested successfully, all locally:** 66 of 66 tests, plus the measured benchmarks in TEST_RESULTS.md.
- **Claims and OCR:** claim extraction in three languages, and OCR on rendered Hindi and Telugu.
- **Security:** URL safety (18 attack forms), upload validation including a decompression bomb, and key redaction.
- **Link analysis:** impersonation, punycode and lookalike detection.
- **Official-source matching:** BM25 matching of official releases with amount checks.
- **Image index:** recall@1 of 83 to 100% per edit type, with 0 held-out false matches. The thresholds were tuned on this set.
- **C2PA:** reading and stripping behaviour.
- **Video:** keyframe reuse matching.
- **Audio:** fingerprint matching through Opus and MP3 re-encodes.
- **Pipeline:** the verdict rules, conflict self-correction, citation validation, and the LangGraph equivalence check.
- **API:** the FastAPI endpoints.

**Not tested:** anything that needs the internet.

## C. API feasibility

| Group | Integrations | Status |
|---|---|---|
| Keyless | RDAP, Wikidata, PIB RSS | BLOCKED from our workspace. The fetcher probe found RDAP and PIB RSS endpoints exist |
| Free key | Fact Check Tools, Safe Browsing (v4 deprecated, so v5 first), urlscan, Sightengine | AUTH_REQUIRED or BLOCKED here |
| Billing | Cloud Vision | AUTH_REQUIRED |
| Optional | LLM (Ollama or Gemini, both with privacy caveats), VirusTotal | NOT_TESTED |
| Not usable | Telegram data (terms), myScheme (bots prohibited), RBI deep links (permission needed), TinEye (paid), Bing (retired) | n/a |

**Live successes so far: zero.** That is the first blocker.

## D. Deepfake detection feasibility

| | Image | Video | Audio |
|---|---|---|---|
| **Proven** (ran here) | reuse matching (pHash+ORB), C2PA reading | reuse matching through keyframes | reuse matching through fingerprints |
| **Planned, unproven** | Sightengine AI-image signal (gated by calibration), Cloud Vision web provenance | per-frame AI-image signal | none |
| **Not feasible as a verdict** | open-source detectors on forwarded images (published generalisation failures) | face-swap and lip-sync detection (65.18% challenge winner, AUC drop of 50% in the wild) | voice-clone detection (degradation up to 1000%). Reported as UNVERIFIED |

So Satyapan can genuinely **demonstrate manipulation audit by provenance and credentials**. It cannot honestly demonstrate deepfake **detection**.

## E. Evaluation results

- **Claim-level dataset:** not collected. **No accuracy figures exist and none are claimed.**
  - Plan: 100 items (30 dev, 70 test). On test, 21 TRUE, 46 FALSE, 3 UNRESOLVED.
  - Separate detector set: 120 images.
  - Validator, runner (test split locked behind `--frozen`) and metrics with Wilson intervals are built and mechanically checked.
- **Local provenance benchmark:** 12 indexed images × 10 edit types, plus 15 held-out queries (TEST_RESULTS.md section 2). It is small, uses sample photos rather than WhatsApp forwards, and its thresholds were tuned on it, so treat it as a smoke test, not accuracy.
- **Limitation:** even the full plan only bounds the false-accusation rate below about 14% if no errors occur.

## F. Five biggest technical risks

1. **No external API is proven live.** Fact Check coverage of Indian claims is unknown. If it is thin, FAKE recall rests on the hand-curated index.
2. **The known-debunk index may be too small.** Provenance only works against what the team curates (at least 60 items with links). Curation is manual, because Telegram and myScheme cannot be scraped.
3. **Lexical matching across languages.** Hindi or Telugu claims against English fact-checks will miss. Short claims risk false matches.
4. **The "deepfake" expectation gap.** Judges may expect detection. Overclaiming would be worse than the gap. The pitch needs the evidence slide.
5. **Hosting and demo reliability.** Render's free tier has 512 MB and sleeps after 15 minutes. Cloud Run needs billing. Free-tier quotas and rate limits apply. FFmpeg and OpenCV memory use on the host is untested.

Non-technical, from earlier: confirm the team meets Forge's IIT, NIT, IIIT and BITS eligibility rule.

## G. Hackathon implementation plan

See ROADMAP.md.
- **Stage 0:** prove the APIs live on the MacBook.
- **Stage 1:** curate data (PIB ingest, 60+ known debunks, 30 dev rows, detector set).
- **Stage 2:** tune on dev only.
- **Stage 3:** freeze, then run the 70 test items once.
- **Stage 4:** UI, multilingual report, optional LLM, deploy.
- **Stage 5:** demo hardening, including a live offline-failure demo.

## H. Final recommendation: CONDITIONAL GO

It is worth building because the core works on real local data. Specifically:
- the evidence gate,
- citations,
- provenance across three media types,
- link impersonation analysis,
- input safety.

It meets T1-D honestly where the state of the art allows.

**Blockers to resolve before committing fully:**
1. **Stage 0:** LIVE_SUCCESS on the MacBook for Fact Check search, Safe Browsing (v5 or v4), RDAP, Wikidata and PIB RSS. Note which PIB URL is English.
2. **Data:** at least 60 curated known debunks with links, at least 25 with media, by day 3.
3. **Dev check:** zero dev genuine items called FAKE. Debunk recall high enough that F1 items are mostly caught (team sets the number before running).
4. **Deploy:** a smoke test passes on the chosen host with a real video and a screenshot.
5. **Framing:** the team commits to "verification and provenance audit" with stated limits, never "deepfake detector".

If blocker 1 or 2 fails by day 3, the one-time switch agreed earlier applies. Otherwise build it.
