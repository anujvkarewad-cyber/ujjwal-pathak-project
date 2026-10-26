#!/usr/bin/env bash
# Codespaces / devcontainer bootstrap: install backend + frontend dependencies
# so that `./run-backend.sh` and `./run-frontend.sh` start instantly.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "▶ post-create: repo = $ROOT_DIR"

# ── 1. backend (Python) ─────────────────────────────────────────────────────
echo "▶ post-create: python venv + backend requirements"
python3 -m venv .venv
./.venv/bin/python -m pip install --quiet --upgrade pip wheel
# requirements-dev.txt = runtime deps + dev/test tooling (mongomock-motor,
# httpx, pytest). requirements.txt additionally pins `emergentintegrations`,
# which is not on PyPI, so it is installed best-effort only.
./.venv/bin/python -m pip install -r backend/requirements-dev.txt
./.venv/bin/python -m pip install --quiet -r backend/requirements.txt 2>/dev/null \
  || echo "  (skipped requirements.txt extras — not available on PyPI, not needed for local dev)"

# ── 2. frontend (Node) ──────────────────────────────────────────────────────
echo "▶ post-create: frontend npm dependencies"
if [ -f frontend/package-lock.json ]; then
  (cd frontend && npm ci --no-audit --no-fund) || (cd frontend && npm install --no-audit --no-fund)
else
  (cd frontend && npm install --no-audit --no-fund)
fi

# ── 3. content pipeline (optional, Node) ───────────────────────────────────
if [ -f content-pipeline/package.json ]; then
  echo "▶ post-create: content-pipeline npm dependencies (optional)"
  (cd content-pipeline && npm install --no-audit --no-fund) || echo "  (skipped)"
fi

# ── 4. generated content repo (optional sibling checkout) ──────────────────
CONTENT_REPO="${CONTENT_REPO:-anujvkarewad-cyber/student-dashboard-frontend}"
SIBLING="$(dirname "$ROOT_DIR")/student-dashboard-frontend"
if [ ! -d "$SIBLING" ] && command -v gh >/dev/null 2>&1; then
  echo "▶ post-create: cloning $CONTENT_REPO (source of content-pipeline/generated)"
  gh repo clone "$CONTENT_REPO" "$SIBLING" -- --depth 1 >/dev/null 2>&1 \
    || echo "  (skipped — set GENERATED_DIR manually if the generated JSON lives elsewhere)"
fi

chmod +x run-backend.sh run-frontend.sh 2>/dev/null || true

GEN_DIR="$(./.venv/bin/python backend/import_original.py --print-dir 2>/dev/null || true)"
echo
echo "✅ setup complete"
echo "   generated content: ${GEN_DIR:-NOT FOUND (set GENERATED_DIR)}"
echo
echo "   Terminal 1:  ./run-backend.sh     # API  → port 8010"
echo "   Terminal 2:  ./run-frontend.sh    # UI   → port 3000"
echo "   Then open the forwarded port 3000 → /ai-content/queue"
