# Ujjwal Pathak — Mentor Platform

FastAPI mentor backend + React mentor dashboard + ICAI content pipeline.

## Quick start (GitHub Codespaces / local)

```bash
./run-backend.sh     # API  → http://localhost:8010  (imports 94 chapters, DEV_AUTH_BYPASS=1)
./run-frontend.sh    # UI   → http://localhost:3000/ai-content/queue
```

Full setup, URLs, mentor access and import details: **[CODESPACES.md](CODESPACES.md)**.

## Layout

| Path | What |
|------|------|
| `backend/` | FastAPI app (content review, analytics, student sync, auth) |
| `backend/import_original.py` | Imports `content-pipeline/generated/**/*.json` into the backend content DB and deletes all SEED_DEMO records |
| `frontend/` | React (CRA + craco) mentor dashboard |
| `content-pipeline/` | Chapter catalog + generation/validation/publish stages |
| `.devcontainer/` | Codespaces setup (auto-installs backend + frontend deps) |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q
```
