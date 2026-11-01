# Cloudflare Workers AI setup (free plan)

Satyapan's default AI provider. It needs no payment: the Workers Free plan includes 10,000 neurons a day, reset at 00:00 UTC.

| Use | Model | Endpoint |
|---|---|---|
| Chat (claims, comparison, explanation) | `@cf/qwen/qwen3-30b-a3b-fp8` (multilingual, 32,768-token context) | `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1/chat/completions` |
| Chat fallback | `@cf/meta/llama-4-scout-17b-16e-instruct` | same |
| Embeddings | `@cf/baai/bge-m3` (multilingual) | `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/baai/bge-m3` |

The models were chosen from Cloudflare's catalog on 1 Nov 2026. Some Workers AI models need the paid plan (error 5035). Only the live check below proves these work on your free account.

## 1. Create the account

1. Go to `dash.cloudflare.com/sign-up`, sign up with email and password, and verify the email.
2. You are on the Free plan by default. You do not need a domain. If any page asks for payment details to continue, stop there: Satyapan does not need them.

## 2. Get the account ID and an API token

1. In the dashboard, open **Workers AI**. Use the search box at the top if you can't see it in the sidebar (it sits under AI, or Compute & AI).
2. Select **Use REST API**.
3. Under **Get Account ID**, copy the **Account ID**. It is 32 characters of 0-9 and a-f.
4. Select **Create a Workers AI API Token**, check the prefilled permissions (Workers AI Read and Edit), select **Create API Token**, then **Copy API Token**. Cloudflare shows it once.

If you make a token by hand instead (My Profile, API Tokens, Create Token, Custom token), give it only Account, Workers AI, Read and Account, Workers AI, Edit, for your account only.

## 3. Put them in `.env`

```
AI_CHAT_PROVIDER=cloudflare
AI_EMBEDDING_PROVIDER=cloudflare
CLOUDFLARE_ACCOUNT_ID=your_32_character_account_id
CLOUDFLARE_API_TOKEN=your_token
```

Leave `CLOUDFLARE_CHAT_MODEL`, `CLOUDFLARE_CHAT_FALLBACK_MODEL` and `CLOUDFLARE_EMBEDDING_MODEL` empty to use the defaults. Empty out any old `LLM_*` and `EMBEDDING_*` values left from another provider. `HF_*` lines can stay, they are ignored.

## 4. Run the live checks (real API calls)

```bash
.venv/bin/python -m integration.run_all --allow-third-party --only cloudflare_token
.venv/bin/python -m integration.run_all --allow-third-party --only ai_chat_json
.venv/bin/python -m integration.run_all --allow-third-party --only ai_embeddings
.venv/bin/python -m integration.run_all --allow-third-party --only ai_claim_extraction_hi_te
```

| Check | Passes when |
|---|---|
| `cloudflare_token` | Cloudflare says the token is `active`. Uses no neurons |
| `ai_chat_json` | At least one chat model returns JSON. Each model's own status is listed |
| `ai_embeddings` | bge-m3 returns 1024 dimensions, and the Hindi and Telugu sentences about the same scheme are closer to the English one than an unrelated sentence |
| `ai_claim_extraction_hi_te` | The model extracts at least one claim quoted exactly from a Hindi or Telugu message |

Results are saved in `integration_results/`.

## Limits and what happens when they are hit

| Situation | What Satyapan does |
|---|---|
| Free daily allocation used up (HTTP 429, error 3036) | Stops calling Cloudflare until 00:00 UTC (no repeated failing calls). Investigations still finish with code-only evidence and the report says the AI step was rate limited |
| Out of capacity (3040) | Tries the fallback model, then continues without AI |
| Model needs the paid plan (5035) | Tries the fallback model. Pick a different free model in `.env` |
| Timeout (3007, 3008) or other errors | Retry once, then the fallback model, then continue without AI |
| Rate limits | Text generation 300 requests a minute, embeddings 3,000 a minute (Cloudflare's published defaults). Satyapan stays far below them |

Rough budget (estimate, not measured): one text check uses about 52 neurons (about 4,400 input and 1,000 output tokens on Qwen3 30B, plus about 1,300 embedding tokens on bge-m3). That is about 100 to 190 checks a day on the free allocation. The Cloudflare dashboard shows the real neuron use.
