from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone

from db import get_db, close_db, ensure_indexes
from routers import auth_router, content, student_attempts, student_content, student_sync, analytics, admin_fast

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection (config in backend/config.py; MONGO_URL=memory:// runs the
# in-memory mock for dev/test — production passes a real connection string as before)
db = get_db()

# Create the main app without a prefix
app = FastAPI(
    title="Ujjwal Pathak Mentor API",
    description="Mentor dashboard APIs + SPA hosting",
    version="1.0.0"
)

# FIX: CORS must be added BEFORE routers so preflight works for all routes
# This is critical for cloud previews where frontend and backend are on different ports
# And fixes the HTML error when browser tries cross-origin fetch
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)

    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()

    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)

    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])

    return status_checks

# Include the router in the main app
app.include_router(api_router)

# ── NEW: AI Content + Analytics + student sync routers (additive) ──────────
app.include_router(auth_router.router)
app.include_router(content.router)
app.include_router(student_content.router)
app.include_router(student_attempts.router)
app.include_router(student_sync.router)
app.include_router(analytics.router)
app.include_router(admin_fast.router)

# ── SPA static serving (production deployment + live preview) ───────────────
# Serves the built React dashboard from the same origin as /api. Registered
# AFTER every router, so /api, /docs and /openapi.json always win. When the
# frontend build directory is absent, the catch-all simply 404s.
FRONTEND_BUILD_DIR = ROOT_DIR.parent / 'frontend' / 'build'

from fastapi.responses import FileResponse, JSONResponse

# Path prefixes that belong to the API surface, never to the SPA. A request
# under one of these that reached the catch-all matched NO real route, so it
# must return a JSON 404 — serving index.html here is what produced
# `Unexpected token '<', "<!doctype "... is not valid JSON` in the browser:
# fetch() saw HTTP 200 + text/html and res.json() choked on the markup.
# FIX: Expanded and hardened to prevent ANY /api/* from ever returning HTML
API_PREFIXES = ('api', 'docs', 'redoc', 'openapi.json', 'openapi.yml')


def _is_api_path(full_path: str) -> bool:
    clean = full_path.lstrip('/').lower()
    if not clean:
        return False
    head = clean.split('/', 1)[0]
    if head in API_PREFIXES:
        return True
    # Any path starting with api/ is API
    if clean.startswith('api/'):
        return True
    return False


@app.get('/{full_path:path}', include_in_schema=False)
async def spa_fallback(full_path: str):
    # Unknown API route → JSON 404 (never the SPA shell).
    # This is THE fix for "Expected JSON but received HTML"
    if _is_api_path(full_path):
        return JSONResponse(
            {'detail': f'Not Found: /{full_path.lstrip("/")}', 'code': 'API_ROUTE_NOT_FOUND'},
            status_code=404,
        )

    if FRONTEND_BUILD_DIR.is_dir():
        try:
            candidate = (FRONTEND_BUILD_DIR / full_path).resolve()
            build_root = FRONTEND_BUILD_DIR.resolve()
            # Security: prevent path traversal
            if full_path and str(candidate).startswith(str(build_root)) and candidate.is_file():
                return FileResponse(candidate)
            index = FRONTEND_BUILD_DIR / 'index.html'
            if index.is_file():
                return FileResponse(index, media_type='text/html')
        except Exception:
            pass
    # No frontend build — return JSON, not HTML, to avoid confusing the client
    return JSONResponse(
        {'message': 'API running. Frontend not built. Run npm run build in frontend/ or run frontend dev server on port 3000.'},
        status_code=200
    )

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _bootstrap_requested() -> bool:
    """True when the process should seed/import content at startup.

    Makes `uvicorn server:app --host 0.0.0.0 --port $PORT` (Render/Railway/Fly
    start command) behave like `python -m dev_server`: restore the persisted
    store and import the generated chapters when the usual env flags are set.
    Tests and plain production deployments (no flags) are unaffected.
    """
    if os.environ.get('BOOTSTRAP_DONE') == '1':  # dev_server already ran it in-process
        return False
    flags = ('IMPORT_GENERATED', 'SEED_DEMO', 'SEED_ALL')
    return any(os.environ.get(f, '').strip().lower() in ('1', 'true', 'yes', 'on') for f in flags)


@app.on_event("startup")
async def startup_db_client():
    await ensure_indexes()
    if _bootstrap_requested():
        from dev_server import bootstrap

        await bootstrap()
        os.environ['BOOTSTRAP_DONE'] = '1'

@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        from persist import dump_store_sync

        await dump_store_sync()
    except Exception:
        logging.getLogger(__name__).exception("failed to persist content store")
    await close_db()
