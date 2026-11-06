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
fi

PROJECT="${PROJECT:-ump-dashboard}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-ujjwal-pathak-app}"
REPO="asia-south1-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}"
TAG_SUFFIX="$(date -u +%Y%m%d-%H%M%S)"

live_image() {
  gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" \
    --format='value(spec.template.spec.containers[0].image)'
}
live_digest() {
  local image
  image="$(live_image)"
  # Cloud Run commonly returns the deployed image as TAG@sha256:DIGEST.
  # Use that pinned digest directly; Artifact Registry may no longer resolve
  # an old tag even though Cloud Run is still serving the digest.
  if [[ "$image" == *@sha256:* ]]; then
    printf '%s\n' "${image##*@}"
    return 0
  fi
  gcloud artifacts docker images describe "$image" --project="$PROJECT" \
    --format='value(image_summary.digest)'
}

build_and_deploy() {
  local kind="$1" ctx="$2" tag="${REPO}:${1}-${TAG_SUFFIX}"
  echo "== building $kind from $ctx"
  # Keep Cloud Build logs and source in a regional project-owned bucket.
  # The Google-owned default logs bucket is outside this project's VPC-SC perimeter.
  ( cd "$ctx" && gcloud builds submit --tag="$tag" --project="$PROJECT" \
      --region="$REGION" --default-buckets-behavior=regional-user-owned-bucket \
      --timeout=30m --quiet )
  echo "== deploying $tag"
  gcloud run services update "$SERVICE" --region="$REGION" --project="$PROJECT" --image="$tag" --quiet
  gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" \
    --format='value(status.latestReadyRevisionName)'
}

if [[ "$WHAT" == "frontend" || "$WHAT" == "both" ]]; then
  BASE="$(live_digest)"
  echo "== current live digest $BASE"
  CTX="$(mktemp -d)"
  # only committed code ships; the SPA source lives in frontend/
  git -C "$ROOT" archive HEAD frontend | tar -x -C "$CTX" --strip-components=1
  cat > "$CTX/Dockerfile" <<EOF
FROM node:20-bookworm-slim AS fe
WORKDIR /fe
COPY . .
RUN npm ci --no-audit --no-fund && CI=false GENERATE_SOURCEMAP=false npx craco build

FROM $(live_image | cut -d@ -f1)@$BASE
USER root
COPY --from=fe /fe/build /app/frontend/build
RUN chown -R appuser:appuser /app/frontend && chmod -R u+rwX,go+rX /app/frontend
USER appuser
EOF
  build_and_deploy frontend "$CTX"
  rm -rf "$CTX"
fi

if [[ "$WHAT" == "backend" || "$WHAT" == "both" ]]; then
  BASE="$(live_digest)"
  CTX="$(mktemp -d)"
  git -C "$ROOT" archive HEAD backend | tar -x -C "$CTX" --strip-components=1
  cat > "$CTX/Dockerfile" <<EOF
FROM $(live_image | cut -d@ -f1)@$BASE
USER root
COPY routers/ /app/backend/routers/
COPY *.py /app/backend/
RUN chmod -R 0644 /app/backend && chown -R appuser:appuser /app/backend
USER appuser
EOF
  build_and_deploy backend "$CTX"
  rm -rf "$CTX"
fi

echo "== verifying the live service"
"$ROOT/scripts/verify-deploy.sh"
