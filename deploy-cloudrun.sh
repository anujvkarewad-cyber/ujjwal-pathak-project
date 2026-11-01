#!/usr/bin/env bash
# Deploy the mentor API + SPA container to Google Cloud Run (safe in-place update).
#
# Usage (in Cloud Shell):
#   cd ~/ujjwal-pathak-project
#   git pull origin main
#   ./deploy-cloudrun.sh
set -euo pipefail

SERVICE="${SERVICE:-ujjwal-pathak-app}"
PROJECT="${PROJECT:-ump-dashboard}"
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
ENV_VARS="${ENV_VARS},STUDENT_ADMIN_SCRIPT_URL=${STUDENT_ADMIN_SCRIPT_URL:-https://script.google.com/macros/s/AKfycbyWjeCaMGwCnG5h2M5gjLsURcnBz8tOxoNzd2sZoLlBB8IA5FygE4WQKB1YEcGwpoPHfg/exec}"
ENV_VARS="${ENV_VARS},MONGO_MAX_POOL_SIZE=${MONGO_MAX_POOL_SIZE:-20}"
# Safety holds: prevent background cron catch-up blasts on deploy (especially Sunday evening).
# Mentor-triggered pushes (Notes Inbox publish, announcements, targets) still work normally.
ENV_VARS="${ENV_VARS},WEEKLY_REPORT_HOLD=${WEEKLY_REPORT_HOLD:-1}"
ENV_VARS="${ENV_VARS},PUSH_SCHEDULER=${PUSH_SCHEDULER:-0}"

SECRETS="MONGO_URL=MONGO_URL:latest"
SECRETS="${SECRETS},JWT_SECRET=JWT_SECRET:latest"
SECRETS="${SECRETS},MENTOR_ACCOUNTS=MENTOR_ACCOUNTS:latest"
SECRETS="${SECRETS},STUDENT_IMPORT_KEY=STUDENT_IMPORT_KEY:latest"
SECRETS="${SECRETS},SYNC_SECRET=SYNC_SECRET:latest"

# Auto-attach Google Drive/Sheets Service Account secret for Notes Inbox if present in Secret Manager,
# and ensure the Cloud Run runtime service account has secretAccessor permission first.
gcloud config set project "${PROJECT}" >/dev/null 2>&1 || true
PROJECT_ID="${PROJECT}"
PROJECT_NUM=""
if [ -n "${PROJECT_ID}" ]; then
  PROJECT_NUM="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null || true)"
fi

for sa_secret in NOTES_GOOGLE_SA_JSON GOOGLE_SERVICE_ACCOUNT_JSON ump-drive-sa; do
  if gcloud secrets describe "${sa_secret}" >/dev/null 2>&1; then
    echo "Found Drive service-account secret '${sa_secret}' — attaching as GOOGLE_SERVICE_ACCOUNT_JSON."
    if [ -n "${PROJECT_NUM}" ]; then
      gcloud secrets add-iam-policy-binding "${sa_secret}" \
        --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor" --quiet >/dev/null 2>&1 || true
    fi
    SECRETS="${SECRETS},GOOGLE_SERVICE_ACCOUNT_JSON=${sa_secret}:latest"
    break
  fi
done

echo "Deploying commit $(git rev-parse --short HEAD) to ${SERVICE} (${PROJECT} / ${REGION})..."
# NOTE: --update-env-vars and --update-secrets preserve any extra env vars / secrets
# (such as AI keys or FCM credentials) already configured on the Cloud Run service.
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" \
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
  --update-env-vars "${ENV_VARS}" \
  --update-secrets "${SECRETS}"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" --format='value(status.url)')"
echo "Deployed: ${URL}"
echo "Health:   $(curl -fsS "${URL}/api/health" || echo 'health check failed')"
