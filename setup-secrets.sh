#!/usr/bin/env bash
# One-shot Secret Manager setup for the Cloud Run deployment.
#
# Creates (or updates) the five encrypted settings the backend needs and grants
# the Cloud Run runtime service account permission to read them.
#
#   ./setup-secrets.sh
#
# Non-secret defaults live here in Git. Passwords are NEVER stored in Git — the
# script prompts for them and pipes them straight into Secret Manager.
set -euo pipefail

PROJECT="${PROJECT:-ump-dashboard}"

# Mentor dashboard login. The email is a safe, non-secret default; the password
# is always prompted. Format stored in MENTOR_ACCOUNTS is "email:password"
# (comma-separate more pairs for extra mentors).
MENTOR_EMAIL="${MENTOR_EMAIL:-mentor@ujjwalpathak.in}"

# Mongo Atlas connection details. Password is prompted, never committed.
ATLAS_USER="${ATLAS_USER:-cloudrun}"
ATLAS_HOST="${ATLAS_HOST:-cluster0.2zfikjk.mongodb.net}"

SECRET_NAMES=(MONGO_URL JWT_SECRET MENTOR_ACCOUNTS STUDENT_IMPORT_KEY SYNC_SECRET)

gcloud config set project "${PROJECT}" >/dev/null

# put_secret NAME VALUE — create the secret, or add a new version if it exists.
put_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=- >/dev/null
    echo "  updated ${name}"
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" --data-file=- >/dev/null
    echo "  created ${name}"
  fi
}

urlencode() {
  python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$1"
}

echo "Project:      ${PROJECT}"
echo "Mentor email: ${MENTOR_EMAIL}"
echo "Atlas user:   ${ATLAS_USER}@${ATLAS_HOST}"
echo

# ---------------------------------------------------------------- MONGO_URL --
if gcloud secrets describe MONGO_URL >/dev/null 2>&1; then
  echo "MONGO_URL already exists - keeping it (delete it first to change)."
else
  read -r -p "Atlas password for ${ATLAS_USER}: " ATLAS_PASS
  put_secret MONGO_URL \
    "mongodb+srv://${ATLAS_USER}:$(urlencode "${ATLAS_PASS}")@${ATLAS_HOST}/?retryWrites=true&w=majority"
  unset ATLAS_PASS
fi

# ----------------------------------------------------------- MENTOR_ACCOUNTS --
read -r -p "Mentor password for ${MENTOR_EMAIL} (blank = keep existing): " MENTOR_PASS
if [ -n "${MENTOR_PASS}" ]; then
  case "${MENTOR_PASS}" in
    *:*|*,*) echo "Password must not contain ':' or ','"; exit 1 ;;
  esac
  put_secret MENTOR_ACCOUNTS "${MENTOR_EMAIL}:${MENTOR_PASS}"
  unset MENTOR_PASS
elif ! gcloud secrets describe MENTOR_ACCOUNTS >/dev/null 2>&1; then
  echo "MENTOR_ACCOUNTS does not exist and no password was given."; exit 1
fi

# --------------------------------------------------- generated random secrets --
for pair in "JWT_SECRET 32" "STUDENT_IMPORT_KEY 16" "SYNC_SECRET 16"; do
  set -- ${pair}
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    echo "  kept $1"
  else
    put_secret "$1" "$(openssl rand -hex "$2")"
  fi
done

# ------------------------------------------------------------------- access --
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo
echo "Granting secretAccessor to ${RUNTIME_SA}"
for name in "${SECRET_NAMES[@]}"; do
  gcloud secrets add-iam-policy-binding "${name}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
done

echo
echo "All secrets ready:"
gcloud secrets list --format='value(name)'
echo
echo "Next:  ./deploy-cloudrun.sh"
