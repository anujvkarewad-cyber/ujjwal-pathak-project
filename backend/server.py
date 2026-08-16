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
from routers import auth_router, content, student_content, student_sync, analytics

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection (config in backend/config.py; MONGO_URL=memory:// runs the
# in-memory mock for dev/test — production passes a real connection string as before)
db = get_db()

# Create the main app without a prefix
app = FastAPI()

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
app.include_router(student_sync.router)
app.include_router(analytics.router)

# ── SPA static serving (production deployment + live preview) ───────────────
# Serves the built React dashboard from the same origin as /api. Registered
# AFTER every router, so /api, /docs and /openapi.json always win. When the
# frontend build directory is absent, the catch-all simply 404s.
FRONTEND_BUILD_DIR = ROOT_DIR.parent / 'frontend' / 'build'

from fastapi.responses import FileResponse, Response

@app.get('/{full_path:path}', include_in_schema=False)
async def spa_fallback(full_path: str):
    if FRONTEND_BUILD_DIR.is_dir():
        candidate = (FRONTEND_BUILD_DIR / full_path).resolve()
        build_root = FRONTEND_BUILD_DIR.resolve()
        if full_path and str(candidate).startswith(str(build_root)) and candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_BUILD_DIR / 'index.html'
        if index.is_file():
            return FileResponse(index, media_type='text/html')
    return Response('{"message":"Hello World"}', media_type='application/json')

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_db_client():
    await ensure_indexes()

@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        from persist import dump_store

        await dump_store()
    except Exception:
        logging.getLogger(__name__).exception("failed to persist content store")
    await close_db()
