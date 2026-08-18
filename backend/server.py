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

from db import (
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    STUDENT_MCQ_ATTEMPTS,
    close_db,
    ensure_indexes,
    ensure_unique_indexes,
    get_db,
)
from persist import uses_real_mongo
from routers import auth_router, content, student_attempts, student_content, student_sync, analytics, admin_fast

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

db = get_db()

app = FastAPI(
    title="Ujjwal Pathak Mentor API",
    description="Mentor dashboard APIs + SPA hosting",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")


class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


@api_router.get("/")
async def root():
    return {"message": "Hello World"}


@api_router.get("/health")
async def health():
    total = await db[CONTENT_QUESTIONS].count_documents({})
    published = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})
    chapters = await db[CONTENT_CHAPTERS].count_documents({})
    attempts = await db[STUDENT_MCQ_ATTEMPTS].count_documents({})
    return {
        "ok": True,
        "store": "mongo" if uses_real_mongo() else "memory",
        "questions": total,
        "published": published,
        "chapters": chapters,
        "studentAttempts": attempts,
    }


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    _ = await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks


app.include_router(api_router)
app.include_router(auth_router.router)
app.include_router(content.router)
app.include_router(student_content.router)
app.include_router(student_attempts.router)
app.include_router(student_sync.router)
app.include_router(analytics.router)
app.include_router(admin_fast.router)

FRONTEND_BUILD_DIR = ROOT_DIR.parent / 'frontend' / 'build'

from fastapi.responses import FileResponse, JSONResponse

API_PREFIXES = ('api', 'docs', 'redoc', 'openapi.json', 'openapi.yml')


def _is_api_path(full_path: str) -> bool:
    clean = full_path.lstrip('/').lower()
    if not clean:
        return False
    head = clean.split('/', 1)[0]
    if head in API_PREFIXES:
        return True
    if clean.startswith('api/'):
        return True
    return False


@app.get('/{full_path:path}', include_in_schema=False)
async def spa_fallback(full_path: str):
    if _is_api_path(full_path):
        return JSONResponse(
            {'detail': f'Not Found: /{full_path.lstrip("/")}', 'code': 'API_ROUTE_NOT_FOUND'},
            status_code=404,
        )

    if FRONTEND_BUILD_DIR.is_dir():
        try:
            candidate = (FRONTEND_BUILD_DIR / full_path).resolve()
            build_root = FRONTEND_BUILD_DIR.resolve()
            if full_path and str(candidate).startswith(str(build_root)) and candidate.is_file():
                return FileResponse(candidate)
            index = FRONTEND_BUILD_DIR / 'index.html'
            if index.is_file():
                return FileResponse(index, media_type='text/html')
        except Exception:
            pass
    return JSONResponse(
        {'message': 'API running. Frontend not built. Run npm run 
