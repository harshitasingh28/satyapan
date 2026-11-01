#!/usr/bin/env bash
# Deploy the Satyapan API to Cloud Run. Secrets come from Secret Manager, never from this file.
# Usage: PROJECT=my-project WEB_ORIGIN=https://satyapan-web-xxxx.a.run.app CLOUDFLARE_ACCOUNT_ID=<id> [AI=hf] bash deploy/deploy_api.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
WEB_ORIGIN="${WEB_ORIGIN:-http://localhost:3000}"
CHAT_MODEL="${HF_CHAT_MODEL:-Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra}"
FALLBACK_MODEL="${HF_CHAT_FALLBACK_MODEL:-openai/gpt-oss-120b:groq}"
EMBED_MODEL="${HF_EMBEDDING_MODEL:-intfloat/multilingual-e5-large-instruct}"

# AI=cloudflare (default) uses Cloudflare Workers AI on the free plan: secret cloudflare-api-token and
#   CLOUDFLARE_ACCOUNT_ID (an ID, not a secret). AI=hf uses Hugging Face (secret hf-token, needs credits).
AI="${AI:-cloudflare}"
if [ "$AI" = "cloudflare" ]; then
  : "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID (32 characters, from the Workers AI page)}"
  AI_SECRETS="CLOUDFLARE_API_TOKEN=cloudflare-api-token:latest"
  AI_ENV="AI_CHAT_PROVIDER=cloudflare@AI_EMBEDDING_PROVIDER=cloudflare@CLOUDFLARE_ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID}"
else
  AI_SECRETS="HF_TOKEN=hf-token:latest"
  AI_ENV="AI_CHAT_PROVIDER=huggingface@AI_EMBEDDING_PROVIDER=huggingface@HF_CHAT_MODEL=${CHAT_MODEL}@HF_CHAT_FALLBACK_MODEL=${FALLBACK_MODEL}@HF_EMBEDDING_MODEL=${EMBED_MODEL}@HF_EMBEDDING_PROVIDER=hf-inference@HF_EMBEDDING_FALLBACK_PROVIDER=deepinfra"
fi

gcloud config set project "$PROJECT" >/dev/null
gcloud run deploy satyapan-api --source . --region "$REGION" \
  --cpu 1 --memory 2Gi --concurrency 4 --max-instances 2 --timeout 300 \
  --set-secrets "${AI_SECRETS},MONGODB_URI=mongodb-uri:latest,GOOGLE_API_KEY=google-api-key:latest" \
  --set-env-vars "^@^${AI_ENV}@SATYAPAN_STORE=mongo@SATYAPAN_ALLOWED_ORIGINS=${WEB_ORIGIN}@SATYAPAN_TRUSTED_PROXY_HOPS=1@SATYAPAN_MAX_VIDEO_MB=25@SATYAPAN_MAX_CONCURRENT_JOBS=2@SATYAPAN_RETENTION_HOURS=168@SATYAPAN_DAILY_LLM_CALLS=600@SATYAPAN_CONTACT=${SATYAPAN_CONTACT:-team}" \
  --allow-unauthenticated
gcloud run services describe satyapan-api --region "$REGION" --format 'value(status.url)'
