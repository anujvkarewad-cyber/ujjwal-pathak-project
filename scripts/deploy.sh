#!/usr/bin/env bash
# One deploy path for this project. Nothing goes live except through here.
#
#   ./scripts/deploy.sh frontend        # rebuild the SPA from THIS repo, keep the backend
#   ./scripts/deploy.sh backend         # ship backend/ from THIS repo, keep the SPA
#   ./scripts/deploy.sh both            # both (frontend first, then backend)
#
# Why this exists: the live service was patched file-by-file onto whatever image
# was running, so the repo and production drifted apart and a hand-built frontend
# once shipped without REACT_APP_APPS_SCRIPT_URL (mock data, broken profiles).
# From now on:
#   * the image is ALWAYS built from this repo,
#   * the frontend build refuses to run without the Apps Script URL (prebuild guard),
#   * every deploy ends with scripts/verify-deploy.sh, which fails loudly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
die() { echo "!! $*" >&2; exit 1; }

WHAT="${1:-}"
case "$WHAT" in frontend|backend|both) ;; *) echo "usage: $0 {frontend|backend|both}"; exit 2;; esac

# ---------------------------------------------------------------- 0. gates
# Nothing goes live unless these pass. They are cheap and they are the reason
# the same class of bug cannot reach production twice.
echo "== 0. gates"
python3 "$ROOT/scripts/contract_guard.py" || die "contract guard failed — refusing to deploy"

if [[ "$WHAT" == "backend" || "$WHAT" == "both" ]]; then
  echo "== 0b. backend test suite"
  ( cd "$ROOT/backend" && python3 -m pytest tests/ -q --no-header -p no:cacheprovider ) \
    || die "backend tests failed — refusing to deploy"
fi

if [[ "$WHAT" == "frontend" || "$WHAT" == "both" ]]; then
  echo "== 0c. frontend build env"
  ( cd "$ROOT/frontend" && node scripts/check-build-env.js ) \
    || die "frontend build env invalid — refusing to deploy"
  echo "== 0d. requested Inbox and test-authoring UI tests"
  ( cd "$ROOT/frontend" && CI=true npm test -- --runInBand --runTestsByPath \
      src/pages/NotesInbox.test.jsx src/components/tests/TestAuthoring.test.jsx \
      src/components/tests/SubmissionReviewDialog.test.jsx ) \
    || die "requested frontend flow tests failed — refusing to deploy"
fi

PROJECT="${PROJECT:-ump-dashboard}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-ujjwal-pathak-app}"
REPO="asia-south1-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}"
TAG_SUFFIX="$(date -u +%Y%m%d-%H%M%S)"

revision_image() {
  local revision="$1"
  gcloud run revisions describe "$revision" --region="$REGION" --project="$PROJECT" --format='value(spec.containers[0].image)'
}

revision_digest() {
  local image
  image="$(revision_image "$1")"
  if [[ "$image" == *@sha256:* ]]; then
    printf '%s\n' "${image##*@}"
    return 0
  fi
  gcloud artifacts docker images describe "$image" --project="$PROJECT" --format='value(image_summary.digest)'
}

build_and_deploy() {
  local kind="$1" ctx="$2" tag="${REPO}:${1}-${TAG_SUFFIX}"
  local revision_suffix="${kind}-${TAG_SUFFIX}-${GITHUB_RUN_ID:-local}"
  echo "== building $kind from $ctx"
  # The project uses a user-specified Cloud Build service account. The implicit
  # config created by `gcloud builds submit --tag` does not set logging, so
  # Cloud Build rejects it before the build starts. Use an explicit config with
  # CLOUD_LOGGING_ONLY, which satisfies the service-account logging requirement
  # without needing a logs bucket or broader bucket permissions.
  python3 - "$ctx/cloudbuild.json" "$tag" <<'PY'
import json
import sys
from pathlib import Path

config_path, image = sys.argv[1:]
config = {
    "steps": [{"name": "gcr.io/cloud-builders/docker", "args": ["build", "-t", image, "."]}],
    "images": [image],
    "options": {"logging": "CLOUD_LOGGING_ONLY"},
}
Path(config_path).write_text(json.dumps(config, indent=2) + chr(10))
PY
  ( cd "$ctx" && gcloud builds submit --config=cloudbuild.json --project="$PROJECT" \
      --region="$REGION" --timeout=30m --quiet )
  echo "== creating $kind revision without production traffic: $tag"
  # This is essential: without --no-traffic, a service update can immediately
  # move traffic to the new revision before the pre-deploy checks finish.
  gcloud run services update "$SERVICE" --region="$REGION" --project="$PROJECT" --image="$tag" --no-traffic --revision-suffix="$revision_suffix" --quiet
  LAST_DEPLOYED_REVISION="${SERVICE}-${revision_suffix}"
  DEPLOYED_REVISION="$(gcloud run revisions describe "$LAST_DEPLOYED_REVISION" --region="$REGION" --project="$PROJECT" --format='value(metadata.name)')"
  [[ "$DEPLOYED_REVISION" == "$LAST_DEPLOYED_REVISION" ]] || die "expected revision $LAST_DEPLOYED_REVISION was not created"
  echo "== ready revision $DEPLOYED_REVISION (no production traffic)"
}

if [[ "$WHAT" == "frontend" || "$WHAT" == "both" ]]; then
  BASE_REVISION="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.latestReadyRevisionName)')"
  [[ -n "$BASE_REVISION" ]] || die "Cloud Run has no ready revision to use as frontend base"
  BASE_IMAGE="$(revision_image "$BASE_REVISION")"
  BASE="$(revision_digest "$BASE_REVISION")"
  echo "== current base revision $BASE_REVISION digest $BASE"
  CTX="$(mktemp -d)"
  # only committed code ships; the SPA source lives in frontend/
  git -C "$ROOT" archive HEAD frontend | tar -x -C "$CTX" --strip-components=1
  cat > "$CTX/Dockerfile" <<EOF
FROM node:20-bookworm-slim AS fe
WORKDIR /fe
COPY . .
RUN npm ci --no-audit --no-fund && CI=false GENERATE_SOURCEMAP=false npx craco build

FROM ${BASE_IMAGE%%@*}@$BASE
USER root
COPY --from=fe /fe/build /app/frontend/build
RUN chown -R appuser:appuser /app/frontend && chmod -R u+rwX,go+rX /app/frontend
USER appuser
EOF
  build_and_deploy frontend "$CTX"
  rm -rf "$CTX"
fi

if [[ "$WHAT" == "backend" || "$WHAT" == "both" ]]; then
  if [[ -n "${LAST_DEPLOYED_REVISION:-}" ]]; then
    # In a both-target deploy, layer backend changes on the exact frontend
    # revision this run just created, not whichever revision happens to be LATEST.
    BASE_REVISION="$LAST_DEPLOYED_REVISION"
  else
    BASE_REVISION="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.latestReadyRevisionName)')"
  fi
  [[ -n "$BASE_REVISION" ]] || die "Cloud Run has no ready revision to use as backend base"
  BASE_IMAGE="$(revision_image "$BASE_REVISION")"
  BASE="$(revision_digest "$BASE_REVISION")"
  echo "== backend base revision $BASE_REVISION digest $BASE"
  CTX="$(mktemp -d)"
  git -C "$ROOT" archive HEAD backend | tar -x -C "$CTX" --strip-components=1
  cat > "$CTX/Dockerfile" <<EOF
FROM ${BASE_IMAGE%%@*}@$BASE
USER root
COPY routers/ /app/backend/routers/
COPY *.py /app/backend/
RUN find /app/backend -type d -exec chmod 0755 {} + && find /app/backend -type f -name '*.py' -exec chmod 0644 {} + && chown -R appuser:appuser /app/backend
USER appuser
EOF
  build_and_deploy backend "$CTX"
  rm -rf "$CTX"
fi

# A successful image build can still leave the service's old traffic assignment
# in place. First tag and verify the new revision without sending it user traffic;
# only promote it after its frontend AND backend pass the release-specific checks.
VERIFY_TAG="predeploy"
VERIFY_TAG_SET=0
remove_verify_tag() {
  if [[ "$VERIFY_TAG_SET" == "1" ]]; then
    gcloud run services update-traffic "$SERVICE" --region="$REGION" --project="$PROJECT" \
      --remove-tags="$VERIFY_TAG" --quiet || true
  fi
}
trap remove_verify_tag EXIT

CANDIDATE_REVISION="${LAST_DEPLOYED_REVISION:-}"
[[ -n "$CANDIDATE_REVISION" ]] || die "no candidate revision was recorded for verification"
echo "== tagging exact candidate revision $CANDIDATE_REVISION for no-traffic verification"
gcloud run services update-traffic "$SERVICE" --region="$REGION" --project="$PROJECT" \
  --update-tags="${VERIFY_TAG}=${CANDIDATE_REVISION}" --quiet
VERIFY_TAG_SET=1

SERVICE_JSON="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format=json)"
PREVIEW_URL="$(printf '%s' "$SERVICE_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(next((item.get("url", "") for item in data.get("status", {}).get("traffic", []) if item.get("tag") == "predeploy"), ""))')"
[[ -n "$PREVIEW_URL" ]] || die "could not determine the pre-deploy revision URL"
echo "== verifying candidate revision at $PREVIEW_URL (production traffic unchanged)"
"$ROOT/scripts/verify-deploy.sh" "$PREVIEW_URL"

# Promote only the exact revision that passed verification, not whichever
# revision happens to be LATEST if another deploy ran concurrently.
echo "== promoting verified revision $CANDIDATE_REVISION to 100% traffic"
gcloud run services update-traffic "$SERVICE" --region="$REGION" --project="$PROJECT" \
  --remove-tags="$VERIFY_TAG" --to-revisions="${CANDIDATE_REVISION}=100" --quiet
VERIFY_TAG_SET=0
trap - EXIT

SERVICE_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)')"
[[ -n "$SERVICE_URL" ]] || die "could not determine the deployed Cloud Run service URL"
echo "== verifying promoted service at $SERVICE_URL"
"$ROOT/scripts/verify-deploy.sh" "$SERVICE_URL"
