#!/usr/bin/env bash
# Deploy the mentor API + SPA container to Google Cloud Run.
#
# Usage (in Cloud Shell or local machine with gcloud logged in):
#   git pull
#   ./deploy-cloudrun.sh
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
# Owner-authorized Apps Script used for mentor batch corrections.
ENV_VARS="${ENV_VARS},STUDENT_ADMIN_SCRIPT_URL=${STUDENT_ADMIN_SCRIPT_URL:-https://script.google.com/macros/s/AKfycbyWjeCaMGwCnG5h2M5gjLsURcnBz8tOxoNzd2sZoLlBB8IA5FygE4WQKB1YEcGwpoPHfg/exec}"
# Keep total Mongo connections sane across instances: 20 × max-instances.
ENV_VARS="${ENV_VARS},MONGO_MAX_POOL_SIZE=${MONGO_MAX_POOL_SIZE:-20}"

SECRETS="MONGO_URL=MONGO_URL:latest"
SECRETS="${SECRETS},JWT_SECRET=JWT_SECRET:latest"
SECRETS="${SECRETS},MENTOR_ACCOUNTS=MENTOR_ACCOUNTS:latest"
SECRETS="${SECRETS},STUDENT_IMPORT_KEY=STUDENT_IMPORT_KEY:latest"
SECRETS="${SECRETS},SYNC_SECRET=SYNC_SECRET:latest"

# Auto-attach Google Drive/Sheets Service Account secret for Notes Inbox if present in Secret Manager.
for sa_secret in NOTES_GOOGLE_SA_JSON GOOGLE_SERVICE_ACCOUNT_JSON ump-drive-sa; do
  if gcloud secrets describe "${sa_secret}" >/dev/null 2>&1; then
    echo "Found Drive service-account secret '${sa_secret}' — attaching as GOOGLE_SERVICE_ACCOUNT_JSON."
    SECRETS="${SECRETS},GOOGLE_SERVICE_ACCOUNT_JSON=${sa_secret}:latest"
    break
  fi
done

echo "Deploying ${SERVICE} to ${REGION} (min-instances=${MIN_INSTANCES})..."
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu "${CPU}" \
  --memory "${MEMORY}" \
  --min-instances "${MIN_INSTANCES}" \
  --max-instances "${MAX_INSTANCES:-10}" \
  --concurrency 80 \
  --timeout 300 \
  --cpu-boost \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "${SECRETS}"

URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
echo "Deployed: ${URL}"
echo "Health:   $(curl -fsS "${URL}/api/health" || echo 'health check failed')"
