#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────
# CA Inter MCQ Pipeline — run.sh
# One-command runner for Linux / macOS / WSL / GitHub Codespaces
# Usage: ./run.sh [ingest|generate|validate|stage|publish|verify|full|test]
#        ./run.sh generate --chapter=advanced-accounting-1
#        ./run.sh generate --dry-run
# ──────────────────────────────────────────────────────────────

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$ROOT/content-pipeline"
cd "$PIPELINE_DIR"

CMD="${1:-help}"
shift || true
EXTRA_ARGS="$*"

info() { echo -e "\033[1;34m[run.sh]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[ERR]\033[0m $*" >&2; }

check_node() {
  if ! command -v node >/dev/null 2>&1; then
    err "Node.js not found. Install Node >=20 from https://nodejs.org"
    exit 1
  fi
  VER=$(node -v | sed 's/v//')
  MAJOR=$(echo "$VER" | cut -d. -f1)
  if [ "$MAJOR" -lt 20 ]; then
    warn "Node $VER detected, pipeline needs >=20. Please upgrade."
  fi
}

check_env() {
  if [ ! -f .env ]; then
    warn ".env not found — copying from ../.env.example and content-pipeline may have its own template"
    if [ -f "$ROOT/.env.example" ]; then
      cp "$ROOT/.env.example" .env
      info "Created .env from template — PLEASE EDIT with real keys!"
    elif [ -f .env.example ]; then
      cp .env.example .env
    else
      err "No .env.example found. Create .env manually (see RUN_ACTIONS.md)"
      exit 1
    fi
  fi

  if [ ! -f secrets/service-account.json ] && [ ! -f ./secrets/service-account.json ]; then
    warn "secrets/service-account.json missing — Drive sync (stage-1) will fail. Create it per RUNNING.md"
  fi
}

install_deps() {
  if [ ! -d node_modules ]; then
    info "npm install..."
    npm install
  fi
}

do_ingest() {
  info "→ Ingest (stages 0-4)"
  npm run stage:catalog
  npm run stage:drive
  npm run stage:extract
  npm run stage:normalize
  npm run stage:map
  info "Check state/mapping.json for BLOCKED chapters"
}

do_generate() {
  info "→ Generate stage-5 $EXTRA_ARGS"
  node src/stage-5-generate.mjs $EXTRA_ARGS
}

do_validate() {
  info "→ Validate stages 6-9"
  npm run stage:validate-schema || true
  npm run stage:validate-content || true
  npm run stage:duplicates || true
  npm run stage:coverage || true
  ls -lh state/*.json 2>/dev/null || true
}

do_stage() {
  info "→ Stage to review (stage-10)"
  npm run stage:stage
}

do_publish() {
  info "→ Publish $EXTRA_ARGS"
  node src/stage-11-publish.mjs $EXTRA_ARGS
  node src/stage-12-verify.mjs || true
}

check_node
check_env
install_deps

case "$CMD" in
  ingest)
    do_ingest
    ;;
  generate)
    do_generate
    ;;
  validate)
    do_validate
    ;;
  stage)
    do_stage
    ;;
  publish)
    do_publish
    ;;
  verify)
    node src/stage-12-verify.mjs
    ;;
  full)
    do_ingest
    do_generate
    do_validate
    do_stage
    info "Full done. Now review in dashboard, then ./run.sh publish --chapter=<id>"
    ;;
  test)
    npm test
    ;;
  help|-h|--help|*)
    cat <<USAGE
Usage: ./run.sh <command> [extra args]

Commands:
  ingest                 Catalog + Drive + Extract + Normalize + Map (stages 0-4)
  generate [--dry-run] [--chapter=ID]   AI generation (stage-5)
  validate               Schema + content + duplicates + coverage (6-9)
  stage                  Push to mentor review queue (10)
  publish --chapter=ID   Publish approved chapter (11) + verify (12)
  verify                 Verify published bundles
  full                   ingest -> generate -> validate -> stage
  test                   npm test

Examples:
  ./run.sh ingest
  ./run.sh generate --dry-run
  ./run.sh generate --chapter=advanced-accounting-1
  ./run.sh validate
  ./run.sh stage
  ./run.sh publish --chapter=advanced-accounting-1
  ./run.sh full --chapter=audit-1   (full will forward extra args to generate)

Setup:
  1. cp .env.example .env   (fill OPENAI_API_KEY + Drive folder IDs)
  2. Place service-account.json in content-pipeline/secrets/
  3. Share Drive folders with SA email as Viewer
  4. ./run.sh ingest

See:
  content-pipeline/RUNNING.md
  RUN_ACTIONS.md
USAGE
    ;;
esac
