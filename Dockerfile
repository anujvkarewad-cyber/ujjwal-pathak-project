# Koyeb deployment image for the Ujjwal Pathak platform (API + mentor SPA).
#
# Replaces the Vercel deployment that started returning
# HTTP 402 DEPLOYMENT_DISABLED. One container serves everything:
#   /api/*  → FastAPI (mentor + student APIs)
#   /*      → the CRA build (SPA fallback in server.py)
# The SPA calls the API same-origin, so no cross-origin config is needed.
#
# Koyeb: Create Service → GitHub → this repo → Builder: Dockerfile
#        (Dockerfile path: ./Dockerfile, work directory: repo root).
# Koyeb injects $PORT; health check path: /api/health.
#
#   Local build:  docker build -t ump-api .
#   Local run:    docker run -p 8000:8000 -e MONGO_URL="mongodb+srv://..." ump-api

# ── Stage 1: build the mentor SPA ─────────────────────────────────────────
FROM node:20-bookworm-slim AS web

WORKDIR /web

# Same-origin API calls: the FastAPI container serves the SPA itself.
ENV REACT_APP_APPS_SCRIPT_URL=https://script.google.com/macros/s/AKfycbzyfWa8agayMB0XLjkbfhfj2MdIRElAiY2Wnd7-eQKd1zlMl099ky6Cif06TWydzr8D/exec \
    REACT_APP_MENTOR_API_URL=same-origin \
    CI=false \
    GENERATE_SOURCEMAP=false \
    NODE_OPTIONS=--max-old-space-size=2048

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ── Stage 2: API runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# build-essential for wheels that need compiling; curl for the health check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first so code edits do not bust the layer cache.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/backend/requirements.txt \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/*

# Application code: backend + the generated content the importer reads.
COPY backend/ /app/backend/
COPY content-pipeline/ /app/content-pipeline/

# Mentor SPA from stage 1 (server.py serves it via the SPA fallback).
COPY --from=web /web/build /app/frontend/build

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# Shell form so Koyeb's $PORT is expanded at runtime.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"
