# Cloud Run deployment image for the Ujjwal Pathak platform (API + mentor SPA).
#
# One container serves everything:
#   /api/*  → FastAPI (mentor + student APIs)
#   /*      → static mentor dashboard (vanilla HTML/CSS/JS)
# The SPA calls the API same-origin, so no cross-origin config is needed.
#
# Cloud Run: gcloud run deploy --source . --region asia-south1
#
#   Local build:  docker build -t ump-api .
#   Local run:    docker run -p 8000:8000 -e MONGO_URL="mongodb+srv://..." ump-api

# ── Runtime stage: API + static dashboard ─────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

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

# Static mentor dashboard (vanilla HTML/CSS/JS, no build step needed).
COPY frontend/build /app/frontend/build

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# Shell form so Cloud Run's $PORT is expanded at runtime.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"
