# Implementation log

## 1 Nov 2026, afternoon (2): Cloudflare Workers AI as the default free provider

The team's Gemini access ended (trial credits finished) and the team asked to avoid paid APIs entirely.

- **Default provider: Cloudflare Workers AI, Workers Free plan.** Chat `@cf/qwen/qwen3-30b-a3b-fp8` (fallback `@cf/meta/llama-4-scout-17b-16e-instruct`) through the official OpenAI-compatible endpoint, embeddings `@cf/baai/bge-m3` through the official `/ai/run/` endpoint. Checked on Cloudflare's docs: both models are Cloudflare-hosted with no paid tag, free allocation 10,000 neurons a day, error 3036 when it is used up.
- **Independent providers:** `AI_CHAT_PROVIDER` and `AI_EMBEDDING_PROVIDER` (cloudflare, openai, huggingface, none). Gemini is no longer the default or the suggested free option. Any OpenAI-compatible provider still works.
- **Free-limit handling (`satyapan/cloudflare.py`):** 3036 pauses Cloudflare calls until 00:00 UTC, 3040 and 5035 move to the fallback model, timeouts retry then fall back, and investigations always finish with code-only evidence. Qwen3 thinking is switched off with `/no_think` to save neurons. JSON mode rejections are retried without `response_format`.
- **Safety:** the account ID must be 32 hexadecimal characters before it goes into a URL. `CLOUDFLARE_API_TOKEN` is redacted from logs. Blank `.env` model lines now mean "use the default".
- **Live checks added:** `cloudflare_token`, `ai_chat_json`, `ai_embeddings` (1024 dimensions, Hindi and Telugu closer than unrelated text), `ai_claim_extraction_hi_te`.
- **Results (offline):** pytest 141 passed (8 new Cloudflare tests). Cloudflare is not reachable from the development workspace.
- **LIVE results on the team MacBook, 1 Nov 2026 13:56 IST (Workers Free plan, real API calls):**

| Check | Result |
|---|---|
| `cloudflare_token` | LIVE_SUCCESS, token active (997 ms) |
| `ai_chat_json` | LIVE_SUCCESS. `@cf/qwen/qwen3-30b-a3b-fp8` returned valid JSON in 552 ms. Fallback `@cf/meta/llama-4-scout-17b-16e-instruct` returned valid JSON in 507 ms. Both work on the free plan |
| `ai_embeddings` | LIVE_SUCCESS. `@cf/baai/bge-m3`: 1024 dimensions, unit length, 261 ms. Cosine English to Hindi (same claim) 0.842, English to Telugu (same claim) 0.873, English to an unrelated claim 0.353 |
| `ai_claim_extraction_hi_te` | LIVE_SUCCESS. Hindi: 2 claims kept, 0 rejected. Telugu: 2 claims kept, 0 rejected. Every kept claim is an exact quote from the message |

- **LIVE end-to-end runs in the web app, team MacBook, 1 Nov 2026 14:10 to 14:14 IST** (backend and frontend local, Cloudflare Workers AI free plan, Google Fact Check and Safe Browsing, RDAP, 40 real PIB releases embedded with bge-m3 in 3 calls):

| Test | Message | Verdict | Notes |
|---|---|---|---|
| 1 | Exact title and link of a real PIB release (PRID 2331041) | GENUINE | Fact-check search, embeddings, Safe Browsing, AI comparison (1.11 s) and AI explanation (0.92 s) all ran live |
| 2 | Hindi free-laptop forward with a `.top` link | UNVERIFIED | One weak link signal only (score 1). Safe Browsing and RDAP ran live and found nothing |
| 3 | PM-Kisan message with `pmkisan.gov.in.ekyc-update.top` | FAKE, high | Score 4 from 2 independent sources, 1 strong |
| 4 | Google's Safe Browsing test page | FAKE, high | Score 4 from 2 independent sources, 1 strong |

  One example per language is not an accuracy measurement. `SATYAPAN_SEMANTIC_CANDIDATE` (0.80) was set for e5 and should be re-tuned for bge-m3 on the development split.

## 1 Nov 2026, afternoon: free AI provider option

The team asked for a free option after Hugging Face reported "no remaining credits" (free Hugging Face accounts have no included credits). Live result on the MacBook before this change: the HF token was accepted, both HF checks failed with that credit message.

- Chat and embeddings now work with any hosted OpenAI-compatible provider: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, and a chat fallback on another provider (`LLM_FALLBACK_*`). Recommended free setup: Google Gemini free tier for both, Groq free tier as the chat fallback. Hugging Face still works unchanged.
- Leftover `HF_*` model names are ignored when another provider is set. Gemini (`AIza`) and Groq (`gsk_`) keys are redacted in logs.
- `/v1/status` now names the provider hosts that receive text, and the integration keys are `ai_chat` and `ai_embeddings`. The consent box names the provider and warns about Gemini free-tier data use.
- Integration checks renamed: `ai_chat_json`, `ai_embeddings`, `ai_claim_extraction`. `integration/run_all.py` now also runs as a file.
- Results (offline): pytest 133 passed (4 new provider tests), frontend Vitest 55/55, type check, build and bundle scan pass. Not yet run live: Gemini and Groq.
- Not verified from the published pages: whether `gemini-embedding-001` is free of charge, and the free-tier rate limits (shown in AI Studio). The live check answers both.

## 1 Nov 2026: Satyapan 2.0 build (development workspace)

Built on the audited feasibility code of 31 Oct 2026 (source fingerprint of its 73 Python files: `4ff8d989f6a964d93092620df64c6c184ee24916d524089f40cd4e5f2a78571d`). The original folder was not changed. The work was done in a copy, with AI coding assistance (see `docs/AI_USAGE_DISCLOSURE.md`).

**Where it was tested:** a Linux workspace whose network reaches only package registries and GitHub. So Hugging Face, MongoDB Atlas, Google APIs, RDAP and Docker Hub were NOT reachable there. Every test below is offline (mocked services, labelled as such) unless it says "live".

### What changed

| Area | Files |
|---|---|
| Hugging Face chat with fallback model, hosted only | `satyapan/llm.py`, `satyapan/config.py`, `satyapan/http.py` |
| Multilingual embeddings (hf-inference and DeepInfra routes), cache | `satyapan/hf.py` (new) |
| AI comparison with quotes checked in code | `satyapan/pipeline/compare.py` (new) |
| Release-ID, outdated-news and fact-compatibility checks | `satyapan/pipeline/checks.py` (new) |
| Pipeline: candidates, Route 2 GENUINE, semantic FAKE, AI veto, reason codes, live events, statement kinds | `satyapan/pipeline/graph.py`, `evidence.py`, `citations.py`, `report.py`, `satyapan/models.py` |
| MongoDB store with TTL, private records (token hashes), events, corpus, vector cache | `satyapan/db/mongo.py` (new), `satyapan/storage.py`, `satyapan/sources/pib.py` |
| Streaming API, history and report downloads, status, CORS, Cloud Run client IP | `satyapan/api/app.py`, `docs/API_CONTRACT.md` |
| Image match tiers (similar scene is never evidence) | `satyapan/media/image_index.py`, `audit/image_eval.py --evidence-tiers` |
| Next.js frontend (TypeScript, Tailwind) | `frontend/` (built by a separate agent session against `docs/API_CONTRACT.md`, then re-verified) |
| Deployment | `Dockerfile`, `.dockerignore`, `deploy/`, `frontend/Dockerfile`, `docs/DEPLOYMENT.md`, `.env.example` |
| Data and evaluation tools | `scripts/init_db.py`, `embed_corpus.py`, `import_known_debunks.py`, `collect_factchecks.py`, `ingest_pib.py`, `eval/model_bakeoff.py`, `eval/metrics.py`, `eval/run_eval.py`, `integration/run_all.py` |
| Tests | `tests/test_v2_pipeline.py`, `tests/test_v2_api.py` (new), `tests/test_api.py` and three audit scripts now send the access token, `audit/llm_injection.py` uses a mocked hosted router instead of a local server |

No existing expected verdict was changed. Two test harness changes were needed by design: API reads now send `X-Access-Token` (records are private), and the LLM attack audit moved from an `http://localhost` fake server to a mocked HTTPS router because local model servers are now refused.

### Results (offline unless marked)

| Check | Result |
|---|---|
| `pytest` | **129 passed**, 0 failed, 0 skipped (103 existing plus 26 new) |
| New rule tests | Route 2 GENUINE, invented quote rejected, wrong amount blocks GENUINE, paraphrase without link stays UNVERIFIED, AI veto, AI outage keeps code-only verdict, P3 link mismatch, P5 outdated news, cross-language fact-check FAKE, similarity alone never FAKE, different-claim and number-conflict controls, model cannot set the verdict, no consent means no AI calls, explanation labelled: all pass |
| `audit/adversarial_verdicts.py` | 16/16 |
| `audit/independent_adversarial.py` | 25/25 |
| `audit/independent_probes.py` | 3/3 |
| `audit/llm_injection.py` | 6/6, including the new "invented comparison quote rejected" |
| `audit/key_leakage.py` | 3/3, now also with an HF token and a MongoDB password planted |
| `audit/security_practical.py` (local server) | 21/21 |
| `audit/concurrency.py` (local server, 8 parallel 12 MP uploads) | 8/8 finished, budget race pass |
| `audit/e2e_scenarios.py` | 13/15. B2 (paraphrase) needs the live HF model, D4 needs live Safe Browsing. Both passed or failed the same way offline before 2.0 |
| Image tiers, dev set (tuning) | evidence-tier recall 140/144, 0 false matches |
| Image tiers, held-out set | run 1 (similarity fit): hard-negative false copies 1/36, recall 93.2%. A video scenario then showed stretched copies were missed, so the fit was widened to affine on dev data. Run 2: hard-negative false copies **1/36 (was 15/36 before tiers)**, recall **95.8% (was 97.0%)**. This set was already seen on 31 Oct, so it is not a clean test |
| `deploy/smoke_test.py` against a local server | 9/9 (stream, incremental events, private records, report, CORS) |
| Frontend | `tsc` pass, Vitest 53/53, `next build` pass, bundle secret scan pass, Playwright 7/7 against the real local backend (live trace, verdict, history, Markdown download, axe accessibility, 360 px width) |
| Docker images | **not built**: Docker Hub is blocked in the workspace. Cloud Build builds them on deploy |
| Live HF, Atlas, Google, Cloud Run | **not run** from the workspace. Run section "Next" on the MacBook |

### Next (on the MacBook, in this order)

1. `python -m pytest` in the new folder (expect 129 passed).
2. `python integration/run_all.py --allow-third-party --only hf_chat_json`, then `--only hf_embeddings`, then `--only mongodb`, then the full run. Record results here.
3. Import data: `scripts/ingest_pib.py`, `--set-date` for releases, `import_known_debunks.py`, `embed_corpus.py`.
4. Label development pairs and run `eval/model_bakeoff.py`. Choose `HF_CHAT_MODEL`.
5. Collect the evaluation dataset with `scripts/collect_factchecks.py` plus manual review, tune on dev, freeze, run test once.
6. Photograph a new hard-negative image set (same scenes, different photos) and run `audit/image_eval.py`.
7. Deploy (`docs/DEPLOYMENT.md`) and run `deploy/smoke_test.py --check-rate-limit`.
