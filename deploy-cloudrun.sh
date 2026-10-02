#!/usr/bin/env bash
# Deploy the mentor API + SPA container to Google Cloud Run.
#
# One-time setup:
#   gcloud auth login
#   gcloud config set project <YOUR_PROJECT_ID>
#   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
#       artifactregistry.googleapis.com secretmanager.googleapis.com
#
# Create the encrypted secrets once (values are stored in Secret Manager,
# encrypted at rest, never in Git — this is Cloud Run's "encrypted settings"):
#   printf '%s' 'mongodb+srv://...'      | gcloud secrets create MONGO_URL             --data-file=-
#   printf '%s' "$(openssl rand -hex 32)"| gcloud secrets create JWT_SECRET            --data-file=-
#   printf '%s' 'mentor@x.in:Pass'       | gcloud secrets create MENTOR_ACCOUNTS       --data-file=-
#   printf '%s' '<random>'               | gcloud secrets create STUDENT_IMPORT_KEY    --data-file=-
#   printf '%s' '<random>'               | gcloud secrets create SYNC_SECRET           --data-file=-
# Optional, for the one-shot four-account reset (delete it after the first boot):
#   printf '%s' '{"UMP0043":"..","UMP0081":"..","UMP0088":"..","UMP0090":".."}' \
#       | gcloud secrets create ACCOUNT_RESET_SHEET_PASSWORDS --data-file=-
#
# Then just:  ./deploy-cloudrun.sh
set -euo pipefail

SERVICE="${SERVICE:-ujjwal-pathak-app}"
REGION="${REGION:-asia-south1}"          # Mumbai — Tier 1, free allowance applies
MIN_INSTANCES="${MIN_INSTANCES:-0}"      # 0 = free but cold starts; 1 = always warm (~$5-9/mo)
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"

# IMPORT_GENERATED=0 once the content is in Atlas: skips the 94-chapter import
# on every cold start, which is the single biggest cold-start saving.
ENV_VARS="DB_NAME=ujjwal_pathak"
ENV_VARS="${ENV_VARS},DEV_AUTH_BYPASS=0"
ENV_VARS="${ENV_VARS},IMPORT_GENERATED=${IMPORT_GENERATED:-0}"
ENV_VARS="${ENV_VARS},GENERATED_DIR=../content-pipeline/generated"
ENV_VARS="${ENV_VARS},CORS_ORIGINS=*"

SECRETS="MONGO_URL=MONGO_URL:latest"
SECRETS="${SECRETS},JWT_SECRET=JWT_SECRET:latest"
SECRETS="${SECRETS},MENTOR_ACCOUNTS=MENTOR_ACCOUNTS:latest"
SECRETS="${SECRETS},STUDENT_IMPORT_KEY=STUDENT_IMPORT_KEY:latest"
SECRETS="${SECRETS},SYNC_SECRET=SYNC_SECRET:latest"
# Uncomment for the first boot of the four-account reset, then remove and redeploy:
# SECRETS="${SECRETS},ACCOUNT_RESET_SHEET_PASSWORDS=ACCOUNT_RESET_SHEET_PASSWORDS:latest"

echo "Deploying ${SERVICE} to ${REGION} (min-instances=${MIN_INSTANCES})..."
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --cpu "${CPU}" \
  --memory "${MEMORY}" \
  --min-instances "${MIN_INSTANCES}" \
  --max-instances "${MAX_INSTANCES:-4}" \
  --concurrency 80 \
  --timeout 300 \
  --cpu-boost \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "${SECRETS}"

URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
echo "Deployed: ${URL}"
echo "Health:   $(curl -fsS "${URL}/api/health" || echo 'health check failed')"
