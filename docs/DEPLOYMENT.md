# Deployment: Vercel (frontend) + Render/Railway/Fly (backend)

The mentor dashboard is a CRA SPA (static) and the API is FastAPI (long-running
process). Vercel hosts the frontend; the backend needs a real server host —
it will NOT work as Vercel serverless functions (in-memory store, startup
import, background persistence).

## 1. Backend → Render (recommended, or Railway/Fly)

**Option A — Blueprint (one click):** Render → *New → Blueprint* → select this
repo. `render.yaml` at the repo root configures everything below.

**Option B — manual Web Service:**

| Setting        | Value                                             |
|----------------|---------------------------------------------------|
| Root Directory | `backend`                                         |
| Build Command  | `pip install -r requirements.txt && pip install mongomock-motor` |
| Start Command  | `uvicorn server:app --host 0.0.0.0 --port $PORT`  |

Environment variables:

```
MONGO_URL=memory://
DB_NAME=ujjwal_pathak
DEV_AUTH_BYPASS=1
IMPORT_GENERATED=1
GENERATED_DIR=../content-pipeline/generated
CORS_ORIGINS=*
```

`server.py` runs the same bootstrap as `python -m dev_server` when
`IMPORT_GENERATED=1` (or `SEED_DEMO`/`SEED_ALL`) is set: it restores
`backend/data/content-store.json` if present, then imports the 94 generated
chapters — so the plain `uvicorn server:app` start command is enough.

Smoke test after deploy:

```
curl https://<backend-url>/api/content/chapters   # → 94 chapters, ~sub-second
```

### Free-tier caveats

* **Cold starts** — free instances sleep after idle; first request takes ~30-60s.
* **Ephemeral disk + `MONGO_URL=memory://`** — the in-memory store is snapshotted
  to `backend/data/content-store.json` (restored on every boot; dumped after
  mentor decisions **and** every student consent / progress-sync). This survives
  plain process restarts of the same instance, but a redeploy / instance
  recycle resets the disk, so submitted student progress and decisions can be
  lost. For permanent storage create a free MongoDB Atlas cluster and set:

  ```
  MONGO_URL=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net
  DB_NAME=ujjwal_pathak
  ```

* **Auth** — `DEV_AUTH_BYPASS=1` opens mentor screens without login. For real
  deployments set it to `0` and configure `MENTOR_EMAIL`,
  `MENTOR_PASSWORD_HASH` (generate: `python -m auth hash 'password'` inside
  `backend/`), and a strong `JWT_SECRET`.

## 2. Frontend → Vercel

1. Vercel → *Add New → Project* → import this GitHub repo.
2. **Root Directory:** `frontend` — Framework preset: **Create React App**
   (auto-detected from `frontend/vercel.json`).
3. Deploy. The SPA rewrite in `vercel.json` keeps deep links
   (`/ai-content/queue`, …) working; `/api/*` is deliberately excluded from
   the rewrite so API typos surface as 404s instead of the HTML shell.

At this point the dashboard loads, but AI Content pages show
"Backend unreachable" — the API isn't on Vercel.

## 3. Point the frontend at the backend

Vercel → Project → *Settings → Environment Variables*:

```
REACT_APP_MENTOR_API_URL = https://<backend-url>   # no trailing slash
```

Then **Redeploy** (CRA bakes env vars in at build time). Gate / approve /
publish now work end-to-end.

Optionally tighten backend CORS: `CORS_ORIGINS=https://<your-app>.vercel.app`.

## 4. Local development (unchanged)

```
./run-backend.sh    # FastAPI on :8010 (memory store + generated import)
./run-frontend.sh   # CRA on :3000, /api proxied to :8010
```
