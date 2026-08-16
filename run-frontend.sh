#!/usr/bin/env bash
# Start the mentor dashboard (React/CRA) on port 3000, wired to the backend
# started by ./run-backend.sh (port 8010).
#
#   ./run-frontend.sh
#
# API wiring:
#   * local machine / VS Code desktop → REACT_APP_MENTOR_API_URL=http://localhost:8010
#   * GitHub Codespaces in a browser  → REACT_APP_MENTOR_API_URL=same-origin
#     (the CRA dev server proxies /api → http://localhost:8010, so no second
#      forwarded port has to be made public)
# Override any time:  REACT_APP_MENTOR_API_URL=https://my-api ./run-frontend.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8010}"

if [ ! -d node_modules ]; then
  echo "[run-frontend] installing frontend dependencies (first run only)…"
  npm install --no-audit --no-fund
fi

export PORT="${PORT:-3000}"
export BROWSER="${BROWSER:-none}"
export HOST="${HOST:-0.0.0.0}"
export DANGEROUSLY_DISABLE_HOST_CHECK="${DANGEROUSLY_DISABLE_HOST_CHECK:-true}"
export WDS_SOCKET_PORT="${WDS_SOCKET_PORT:-0}"
# craco.config.js proxies /api to this target
export MENTOR_API_PROXY_TARGET="${MENTOR_API_PROXY_TARGET:-http://localhost:${BACKEND_PORT}}"

if [ -z "${REACT_APP_MENTOR_API_URL:-}" ]; then
  if [ -n "${CODESPACE_NAME:-}" ] || [ -n "${GITPOD_WORKSPACE_ID:-}" ]; then
    REACT_APP_MENTOR_API_URL="same-origin"
  else
    REACT_APP_MENTOR_API_URL="http://localhost:${BACKEND_PORT}"
  fi
fi
export REACT_APP_MENTOR_API_URL

echo "[run-frontend] dashboard : http://localhost:${PORT}"
echo "[run-frontend] mentor API: ${REACT_APP_MENTOR_API_URL} (proxy target ${MENTOR_API_PROXY_TARGET})"
echo "[run-frontend] open      : http://localhost:${PORT}/ai-content/queue"

exec npm start
