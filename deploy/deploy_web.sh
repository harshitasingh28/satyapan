#!/usr/bin/env bash
# Deploy the Satyapan web app to Cloud Run. It holds no secrets: only the public API URL.
# Usage: PROJECT=my-project API_URL=https://satyapan-api-xxxx.a.run.app bash deploy/deploy_web.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}"
: "${API_URL:?set API_URL to the satyapan-api URL}"
REGION="${REGION:-asia-south1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/satyapan/satyapan-web:$(date +%Y%m%d%H%M%S)"

gcloud config set project "$PROJECT" >/dev/null
gcloud artifacts repositories describe satyapan --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create satyapan --repository-format docker --location "$REGION"
gcloud builds submit frontend --config deploy/cloudbuild-web.yaml --substitutions "_API_URL=${API_URL},_IMAGE=${IMAGE}"
gcloud run deploy satyapan-web --image "$IMAGE" --region "$REGION" --cpu 1 --memory 512Mi --max-instances 2 \
  --allow-unauthenticated
gcloud run services describe satyapan-web --region "$REGION" --format 'value(status.url)'
