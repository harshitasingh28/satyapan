# Deploying Satyapan 2.0 to Google Cloud Run

Two Cloud Run services in `asia-south1` (Mumbai): `satyapan-api` (FastAPI, holds every secret) and `satyapan-web` (Next.js, holds none). MongoDB Atlas stores records. Hugging Face Inference Providers runs the hosted models. Nothing runs a local model, and Cloud Run never needs to reach your laptop.

**Status:** these steps and scripts have NOT been run against real Google Cloud, Atlas or Hugging Face accounts yet. The Docker images were not built in the development workspace (Docker Hub is blocked there). Cloud Build builds them. Run the smoke test after deploying and record the result in `docs/IMPLEMENTATION_LOG.md`.

## 1. Accounts (one-time)

1. **Google Cloud:** a project with billing enabled (Cloud Run requires it even inside the free tier). Set a budget alert in Billing. A budget alert warns, it does not stop spending.
2. **AI provider, one of:**
   - **Free (default):** Cloudflare Workers AI on the Workers Free plan. You need the account ID and an API token with Workers AI permission (README of this folder, or `docs/CLOUDFLARE.md`). 10,000 neurons a day, nothing charged. Deploy with the default `AI=cloudflare`.
   - **Paid:** a Hugging Face fine-grained token with only the "Inference Providers" permission, plus credits (free Hugging Face accounts have none). Deploy with `AI=hf`.
3. **MongoDB Atlas:** a free M0 cluster, a database user with `readWrite` on the `satyapan` database only, and a generated password. M0 has no private networking, so the IP access list must allow Cloud Run's changing addresses (`0.0.0.0/0`). The strong password, the least-privilege user and TLS (on by default) are what protect it.

## 2. Secrets (Secret Manager)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
for s in cloudflare-api-token mongodb-uri google-api-key     # hf-token instead of cloudflare-api-token for Hugging Face
do
  gcloud secrets create "$s" --replication-policy=automatic
done
gcloud secrets versions add cloudflare-api-token --data-file=-  # paste the token, press Enter, then Ctrl-D
gcloud secrets versions add mongodb-uri --data-file=-     # mongodb+srv://user:password@cluster/...
gcloud secrets versions add google-api-key --data-file=-
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
for s in cloudflare-api-token mongodb-uri google-api-key
do
  gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor
done
```

Pasting with `--data-file=-` keeps secrets out of shell history. Secrets are never put in `NEXT_PUBLIC_` variables, the repository or the Docker image.

## 3. Data (from the MacBook, once)

```bash
python scripts/init_db.py                          # indexes and TTL
python scripts/ingest_pib.py --copy-local-to-mongo # the PIB releases already imported locally
python scripts/import_known_debunks.py debunks.csv # real fact-checks with links
python scripts/embed_corpus.py                     # corpus vectors, cached in MongoDB
```

## 4. Deploy

```bash
PROJECT=my-project CLOUDFLARE_ACCOUNT_ID=<32-character id> bash deploy/deploy_api.sh   # prints the API URL (AI=hf for Hugging Face)
PROJECT=my-project API_URL=https://satyapan-api-xxxx.a.run.app bash deploy/deploy_web.sh   # prints the web URL
PROJECT=my-project CLOUDFLARE_ACCOUNT_ID=<id> WEB_ORIGIN=https://satyapan-web-xxxx.a.run.app bash deploy/deploy_api.sh   # again, for CORS
python deploy/smoke_test.py --api https://satyapan-api-xxxx.a.run.app --origin https://satyapan-web-xxxx.a.run.app --check-rate-limit
```

`--source .` builds with Cloud Build on linux/amd64, so Apple Silicon is not a problem.

## 5. Settings that matter on Cloud Run

| Setting | Value | Why |
|---|---|---|
| Billing | request-based (default) | CPU only while a request is open. The investigation runs INSIDE the streaming request, so it keeps CPU for its whole run |
| `--timeout 300` | 5 minutes | Longest video plus slow APIs. The stream sends a keep-alive every 10 s |
| `--concurrency 4`, `SATYAPAN_MAX_CONCURRENT_JOBS=2` | | OCR, FFmpeg and OpenCV are CPU-bound. Extra jobs wait and the stream says so |
| `--max-instances 2` | | Caps cost and keeps the per-instance rate limits meaningful |
| `--memory 2Gi` | | `/tmp` is in memory on Cloud Run. Uploads and frames live there until the report is done |
| `SATYAPAN_MAX_VIDEO_MB=25` | | Cloud Run refuses HTTP/1 requests above 32 MiB |
| `SATYAPAN_TRUSTED_PROXY_HOPS=1` | | The client IP is the last `X-Forwarded-For` entry. Earlier entries can be forged. Confirm with the smoke test's `--check-rate-limit` |
| `SATYAPAN_ALLOWED_ORIGINS` | web URL | Only the web app may call the API from a browser |
| `MALLOC_ARENA_MAX=2` | in the Dockerfile | Halved peak memory under parallel jobs in the audit |

If the user closes the tab mid-run, the request ends and the instance may lose CPU. The record then shows `interrupted` after 15 minutes, and the user can run it again.

## 6. Costs (estimated 1 Nov 2026, check before relying on them)

| Item | Estimate |
|---|---|
| Cloudflare Workers AI (default) | free: 10,000 neurons a day. Estimate about 100 to 190 text checks a day (about 52 neurons each with Qwen3 30B and bge-m3, more if the model thinks at length) |
| Hugging Face (optional) | about $0.001 per text check, needs purchased credits |
| Cloud Run | inside the monthly free tier for this volume (180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests) |
| Atlas M0 | free |
| Artifact Registry, Cloud Build, Secret Manager | not checked, small |

Spending guards in code: `SATYAPAN_DAILY_LLM_CALLS` and `SATYAPAN_DAILY_EMBEDDING_CALLS` per instance per day, the per-IP rate limit and `--max-instances`.

## 7. Quotas and limits to know

- Atlas M0: 512 MB storage, 100 operations per second, 500 connections, at most 3 search or vector indexes (Satyapan uses none).
- Google Fact Check Tools: quota shown in the Cloud console, not published.
- Safe Browsing v4: non-commercial use.
- PIB: refuses automated feed requests (HTTP 403). Save feeds from a browser and import them.
