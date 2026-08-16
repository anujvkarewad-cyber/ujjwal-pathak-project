"""Public, read-only published content for students.

Serves ONLY the contents of CONTENT_DIR (published bundles written by the
pipeline's gated stage-11). No draft content can exist here by construction —
the pipeline refuses to build bundles from non-approved items.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from config import settings

router = APIRouter(prefix="/api/content/student", tags=["student-content"])

MANIFEST_NAME = "published-manifest.json"
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_MANIFEST = "public, max-age=300"


def _safe_path(relative: str) -> Path:
    root = settings.content_dir.resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root) + "/") and target != root:
        raise HTTPException(status_code=404, detail="Not found")
    return target


@router.get("/manifest.json")
async def manifest():
    target = _safe_path(MANIFEST_NAME)
    if not target.exists():
        return JSONResponse({"error": "No published content available"}, status_code=404)
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": CACHE_MANIFEST})


@router.get("/chunks/{platform}/{file_path:path}")
async def chunk(platform: str, file_path: str):
    if platform not in ("web", "mobile"):
        raise HTTPException(status_code=404, detail="Not found")
    if not file_path.endswith(".json"):
        raise HTTPException(status_code=404, detail="Not found")
    target = _safe_path(f"{platform}/{file_path}")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": CACHE_IMMUTABLE})
