"""Student test-history sync (consent-gated) + mentor read endpoints.

Students upload their mentor-test attempts here:
- MCQ tests: auto-graded score (score/total/scorePct).
- Paper tests: the submission record, then the SELF-EVALUATED marks the
  student writes after checking his answer sheet with the answer key and
  marking scheme — this is how the mentor learns what marks the student
  gave himself.

Sync contract mirrors /api/progress-sync (student_sync.py):
- Consent must be ON for the student (Profile → share progress).
- X-Sync-Token = HMAC-SHA256(studentId) when SYNC_SECRET is configured;
  without a secret the endpoint runs in documented dev mode.
- Paper-test entries upsert in place per student+test (one submission,
  marks can be updated); MCQ attempts append (entry id is unique).
"""
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from auth import require_mentor, verify_sync_token
from config import settings
from db import ANALYTICS_AUDIT_SYNC, ANALYTICS_CONSENTS, ANALYTICS_TEST_HISTORY, get_db
from models import TestHistorySyncRequest

router = APIRouter(prefix="/api", tags=["test-history"])

_last_sync: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/test-history/sync")
async def sync_test_history(
    body: TestHistorySyncRequest,
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

    stored = 0
    for entry in body.entries:
        data = entry.model_dump()
        data["entryId"] = entry.id
        data["studentId"] = body.studentId
        if body.studentName:
            data["studentName"] = body.studentName
        if body.batch:
            data["batch"] = body.batch
        data["syncedAt"] = _now()
        await db[ANALYTICS_TEST_HISTORY].update_one(
            {
                "studentId": body.studentId,
                "testId": entry.testId,
                "kind": entry.kind,
                "entryId": entry.id,
            },
            {"$set": data},
            upsert=True,
        )
        stored += 1

    await db[ANALYTICS_AUDIT_SYNC].insert_one(
        {"at": _now(), "studentId": body.studentId, "action": "test_history_sync", "detail": {"entries": stored}}
    )
    return {"ok": True, "accepted": stored}


@router.get("/test-history")
async def list_test_history(
    student_id: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    """Mentor view: latest-first test attempts of all students (or one)."""
    db = get_db()
    query = {"studentId": student_id} if student_id else {}
    docs = await db[ANALYTICS_TEST_HISTORY].find(query).sort("at", -1).to_list(length=1000)
    for doc in docs:
        doc.pop("_id", None)
    return {"ok": True, "entries": docs}


@router.get("/test-history/{student_id}")
async def student_test_history(student_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    docs = await db[ANALYTICS_TEST_HISTORY].find({"studentId": student_id}).sort("at", -1).to_list(length=300)
    for doc in docs:
        doc.pop("_id", None)
    return {"ok": True, "studentId": student_id, "entries": docs}
