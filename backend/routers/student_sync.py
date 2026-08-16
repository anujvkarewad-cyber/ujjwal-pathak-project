"""Student-facing consent + progress-summary sync (additive, consent-gated).

Privacy contract (docs §9):
- The ONLY data accepted is the allowlisted summary shape (studentId, chapterId,
  masteryBand, attemptCount, accuracyRange, lastActivityDate, weakConceptTags)
  plus a bounded time series of the same fields.
- Raw answers / per-question history are rejected by schema.
- Stored in separate `analytics_*` collections, never in content or student
  namespaces. Every accepted sync and consent change is audited.
- When SYNC_SECRET is configured, X-Sync-Token = HMAC-SHA256(studentId) is
  required; otherwise the endpoint runs in dev mode (documented, not silent).
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from auth import verify_sync_token
from config import settings
from db import ANALYTICS_AUDIT_SYNC, ANALYTICS_CONSENTS, ANALYTICS_SUMMARIES, ANALYTICS_TRENDS, get_db
from models import ConsentRequest, ProgressSyncRequest

router = APIRouter(prefix="/api", tags=["student-sync"])

# Simple per-student rate limiting (in-process; replaced by Redis if scaled).
_last_sync: dict = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _audit(db, student_id, action, detail):
    return db[ANALYTICS_AUDIT_SYNC].insert_one(
        {"at": _now(), "studentId": student_id, "action": action, "detail": detail}
    )


@router.post("/consent")
async def set_consent(body: ConsentRequest, request: Request):
    db = get_db()
    await db[ANALYTICS_CONSENTS].update_one(
        {"studentId": body.studentId},
        {"$set": {"studentId": body.studentId, "sharing": body.sharing, "updatedAt": _now(), "device": body.device}},
        upsert=True,
    )
    await _audit(db, body.studentId, "consent_set", {"sharing": body.sharing, "device": body.device})
    return {"ok": True, "studentId": body.studentId, "sharing": body.sharing}


@router.post("/progress-sync")
async def progress_sync(
    body: ProgressSyncRequest,
    request: Request,
    x_sync_token: str = Header(default=""),
):
    if not verify_sync_token(body.studentId, x_sync_token):
        raise HTTPException(status_code=401, detail="Invalid sync token")

    db = get_db()
    consent = await db[ANALYTICS_CONSENTS].find_one({"studentId": body.studentId})
    if not consent or not consent.get("sharing"):
        raise HTTPException(status_code=403, detail="Sharing is disabled for this student")

    now_ts = time.time()
    last = _last_sync.get(body.studentId, 0)
    if now_ts - last < settings.sync_rate_limit_seconds:
        raise HTTPException(status_code=429, detail="Rate limited")
    _last_sync[body.studentId] = now_ts

    if len(body.summaries) > settings.sync_max_summaries:
        raise HTTPException(status_code=422, detail="Too many summaries")

    stored = 0
    for summary in body.summaries:
        data = summary.model_dump()
        data["syncedAt"] = _now()
        data["lastActivityDate"] = summary.lastActivityDate.isoformat()
        await db[ANALYTICS_SUMMARIES].update_one(
            {"studentId": summary.studentId, "chapterId": summary.chapterId},
            {"$set": data},
            upsert=True,
        )
        stored += 1

    trend_stored = 0
    for point in body.trend[: settings.sync_max_summaries * 12]:
        data = point.model_dump()
        data["syncedAt"] = _now()
        data["weekStart"] = point.weekStart.isoformat()
        # keep at most 12 weekly snapshots per student+chapter (prune oldest)
        key = {"studentId": body.studentId, "chapterId": point.chapterId, "weekStart": point.weekStart.isoformat()}
        await db[ANALYTICS_TRENDS].update_one(key, {"$set": data}, upsert=True)
        trend_stored += 1

    await _audit(db, body.studentId, "progress_sync", {"summaries": stored, "trend": trend_stored})
    return {"ok": True, "accepted": {"summaries": stored, "trend": trend_stored}}


@router.get("/consent/{student_id}")
async def get_consent(student_id: str):
    db = get_db()
    doc = await db[ANALYTICS_CONSENTS].find_one({"studentId": student_id})
    if not doc:
        return {"studentId": student_id, "sharing": None, "note": "No consent record — default is Off"}
    doc.pop("_id", None)
    return doc
