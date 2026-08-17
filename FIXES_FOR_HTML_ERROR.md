# Fix for "Expected JSON but received HTML" — Review Queue Error

## Screenshot Error
```
Expected JSON from /api/content/queue?limit=50&offset=0 but received an HTML page (HTTP 200). 
The request did not reach the API — check that the path is a real API route and that the dev server proxies /api to the backend.
```

## Root Cause (3 reasons)

1. **Frontend proxy misconfigured (craco.config.js)**  
   - Old array syntax `proxy: [{ context: ['/api'], target: ... }]` breaks in webpack-dev-server v5 (CRA 5). Dev server returned `index.html` with 200 instead of proxying.
   - In cloud previews (Codespaces, E2B, Gitpod) browser cannot reach `http://localhost:8010`, so direct API URL fails.

2. **run-frontend.sh defaulted to `http://localhost:8010`**  
   - Locally it worked, but in any cloud preview it fails because browser cannot reach localhost. Must use `same-origin` so CRA dev server proxies `/api` → backend.

3. **Backend SPA fallback could return HTML for /api/* if route not matched**  
   - Old code returned `index.html` for unknown paths, even for `/api/*` if middleware order wrong. Need JSON 404 for all API prefixes.

4. **Empty DB when generated content missing**  
   - `content-pipeline/generated` doesn't exist locally → import fails → empty DB → 0 questions → confusing UX.

---

## Fixes Applied (this commit)

### 1. `frontend/craco.config.js` — robust proxy
**Before:**
```js
devServerConfig.proxy = [{ context: ['/api'], target: 'http://localhost:8010' }]
```

**After (object syntax, works in v4 & v5, returns JSON 502 on error instead of HTML):**
```js
const proxyTarget = process.env.MENTOR_API_PROXY_TARGET || 'http://localhost:8010';
devServerConfig.proxy = {
  '/api': {
    target: proxyTarget,
    changeOrigin: true,
    secure: false,
    xfwd: true,
    logLevel: 'debug',
    timeout: 30000,
    onError: (err, req, res) => {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ detail: `Backend unreachable at ${proxyTarget}` }));
    }
  }
}
```
- Prevents HTML fallback. If backend down, returns **JSON 502** with clear message, not HTML 200.

### 2. `run-frontend.sh` — default to `same-origin`
- Changed default from `http://localhost:8010` to `same-origin` for **all** environments.
- Same-origin uses CRA proxy → works locally AND in cloud previews.
- Added `FORCE_DIRECT_API=1` escape hatch for desktop-only direct calls.
- Also added `frontend/.env` with `REACT_APP_MENTOR_API_URL=same-origin`

### 3. `backend/server.py` — never return HTML for /api
- Moved CORS middleware **before** routers (critical for cross-origin in previews).
- Hardened `_is_api_path()` to catch any `api/` prefix + `openapi.yml`.
- `spa_fallback` now:
  - If path is API (`/api/*`, `/docs`, `/openapi.json`) → **JSON 404** with `code: API_ROUTE_NOT_FOUND`, never HTML.
  - If frontend build exists, serve static + `index.html`
  - Else return **JSON** message, not HTML, to avoid confusing client.
- Tested:
  - `curl /api/content/queue?limit=50` → JSON `{"total":100,...}`
  - `curl /api/content/queueXXX` → JSON 404 `{"detail":"Not Found: ..."}`, not HTML
  - `curl /` → HTML (when build exists) or JSON info

### 4. `backend/dev_server.py` — auto-seed demo if no generated content
- If `IMPORT_GENERATED` fails or DB empty, auto-seed demo data (`seed_demo.py`).
- Prevents 0 questions state that looks like broken.
- Now backend logs:
  ```
  [dev_server] DB empty and no generated content — seeding demo data for dev...
  Demo data seeded (synthetic content only).
    - ch-acc-01: 50 questions in review queue
    - ch-law-03: pre-approved
  ```

### 5. `frontend/src/api/backendClient.js` — better diagnostics
- Added `isHtml()` helper and distinct error messages for proxy vs direct mode.
- When same-origin proxy returns HTML, message explicitly says:
  > Backend not reachable for /api/content/queue. Fix: Run ./run-backend.sh, check curl...
- Preserves original guard that prevented `Unexpected token '<'` raw error.

### 6. `frontend/src/pages/ai-content/ReviewQueue.jsx` — user-friendly error UI
- Instead of plain red `<p>{error.message}</p>`, now shows:
  - Amber box for proxy errors (backend unreachable) vs rose for other errors
  - Step-by-step fix instructions (run backend, check proxy, curl test, cloud same-origin)
  - Retry + Reload buttons
  - `useReviewQueue` now exposes `refetch` and `isFetching` for spinner

---

## Verification

Tested in this sandbox (E2B):

```bash
# Backend alone — returns JSON, not HTML
MONGO_URL=memory:// DEV_AUTH_BYPASS=1 PORT=8010 python -m backend.dev_server
curl http://localhost:8010/api/content/queue?limit=2
# → {"total":100,"limit":2,...} ✅

curl http://localhost:8010/api/content/queueXXX
# → {"detail":"Not Found: ...","code":"API_ROUTE_NOT_FOUND"} 404 JSON ✅ (was HTML before)

# Frontend dev server proxy
REACT_APP_MENTOR_API_URL=same-origin MENTOR_API_PROXY_TARGET=http://localhost:8010 PORT=3000 npm start
curl http://localhost:3000/api/content/queue?limit=2
# → {"total":100,...} JSON via proxy ✅ (was HTML 200 before)

# Combined production build (backend serves frontend)
npm run build
curl http://localhost:8010/ → index.html
curl http://localhost:8010/api/content/queue → JSON ✅ same-origin, no proxy needed
```

## How to Run (fixed)

```bash
# Terminal 1
./run-backend.sh
# Logs: [dev_server] imported or seeded demo, Uvicorn running on http://0.0.0.0:8010

# Terminal 2
./run-frontend.sh
# Should say: mentor API: same-origin (proxy target http://localhost:8010)
# Open http://localhost:3000/ai-content/queue

# If you still see error:
curl http://localhost:8010/api/content/queue?limit=1  # must be JSON
# If not JSON → backend not running

# Production single-origin (for E2B preview without 2 ports):
cd frontend && npm run build && cd ..
# Then only backend serves both:
MONGO_URL=memory:// DEV_AUTH_BYPASS=1 PORT=8010 python -m backend.dev_server
# Open http://localhost:8010/ and http://localhost:8010/ai-content/queue
# API is at same origin, no proxy, error impossible
```

## Files Changed
- `backend/server.py`
- `backend/dev_server.py`
- `frontend/craco.config.js`
- `frontend/src/api/backendClient.js`
- `frontend/src/pages/ai-content/ReviewQueue.jsx`
- `frontend/.env` (new)
- `run-frontend.sh`
