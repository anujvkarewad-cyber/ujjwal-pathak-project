#!/usr/bin/env bash
# Start the mentor backend (FastAPI) on port 8010 with the REAL generated
# chapter content imported into the in-memory DB.
#
#   ./run-backend.sh
#
# What it does:
#   * creates/uses .venv and installs backend/requirements-dev.txt if needed
#   * MONGO_URL=memory://       — no MongoDB server required
#   * DEV_AUTH_BYPASS=1         — mentor screens open without login (dev only)
#   * GENERATED_DIR auto-detect — ../student-dashboard-frontend/content-pipeline/generated
#   * IMPORT_GENERATED=1        — imports 94 chapters + deletes all DEMO records
#
# Override anything with env vars, e.g.
#   PORT=9000 GENERATED_DIR=/path/to/generated ./run-backend.sh
#   SEED_DEMO=1 IMPORT_GENERATED=0 ./run-backend.sh      # old demo data instead
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV="$ROOT_DIR/.venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "[run-backend] creating virtualenv at .venv"
  python3 -m venv "$VENV"
fi
if ! "$PY" -c "import fastapi, motor, mongomock_motor" >/dev/null 2>&1; then
  echo "[run-backend] installing backend dependencies (first run only)…"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$ROOT_DIR/backend/requirements-dev.txt"
fi

export PORT="${PORT:-8010}"
export MONGO_URL="${MONGO_URL:-memory://}"
export DB_NAME="${DB_NAME:-ujjwal_pathak}"
export DEV_AUTH_BYPASS="${DEV_AUTH_BYPASS:-1}"
export CORS_ORIGINS="${CORS_ORIGINS:-*}"
export IMPORT_GENERATED="${IMPORT_GENERATED:-1}"
export PYTHONUNBUFFERED=1

# ── GENERATED_DIR auto-detect ───────────────────────────────────────────────
# (sibling checkout, /workspaces, $HOME, /app … — see backend/import_original.py)
if [ -z "${GENERATED_DIR:-}" ]; then
  GENERATED_DIR="$("$PY" "$ROOT_DIR/backend/import_original.py" --print-dir || true)"
  export GENERATED_DIR
fi
if [ -n "${GENERATED_DIR:-}" ]; then
  echo "[run-backend] generated content : $GENERATED_DIR"
else
  echo "[run-backend] WARNING: no generated content found."
  echo "[run-backend]   clone student-dashboard-frontend next to this repo, or set"
  echo "[run-backend]   GENERATED_DIR=/path/to/content-pipeline/generated"
fi

echo "[run-backend] API            : http://localhost:${PORT}/api  (docs: /docs)"
echo "[run-backend] auth bypass    : DEV_AUTH_BYPASS=${DEV_AUTH_BYPASS}"
echo "[run-backend] store          : MONGO_URL=${MONGO_URL}"

cd "$ROOT_DIR/backend"
exec "$PY" -m dev_server
