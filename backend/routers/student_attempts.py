"""Authenticated cloud backup/restore for completed student MCQ attempts.

Student credentials remain owned by the existing Apps Script backend. Every
backup/restore request delegates authentication there; MongoDB never stores the
password. Only completed, size-bounded Daily/Practice attempts are accepted.
"""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_mentor
from config import settings
from db import ANALYTICS_AUDIT_SYNC, STUDENT_MCQ_ATTEMPTS, get_db
from models import StudentMcqSyncRequest, StudentTokenRequest
from persist import dump_store

router = APIRouter(prefix="/api", tags=["student-mcq-attempts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _validate_existing_student_login(student_id: str, password: str) -> dict:
    """Delegate credential verification to the existing Apps Script API."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                settings.student_auth_url,
                json={
                    "action": "validateLogin",
                    "payload": {"studentId": student_id, "password": password},
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Student login service is unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Student login service rejected the verification request")
    try:
        envelope = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Student login service returned an invalid response") from exc
    result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(result, dict) or result.get("success") is not True:
        raise HTTPException(status_code=401, detail="Invalid Student ID or password")
    returned_id = str(result.get("studentId") or student_id).strip().upper()
    if returned_id != student_id:
        raise HTTPException(status_code=401, detail="Student identity mismatch")
    return result


async def _prune_student_attempts(db, student_id: str, kind: str, keep: int) -> None:
    stale_ids = []
    cursor = db[STUDENT_MCQ_ATTEMPTS].find(
        {"studentId": student_id, "kind": kind}, {"_id": 1}
    ).sort("completedAt", -1).skip(keep)
    async for row in cursor:
        stale_ids.append(row["_id"])
    if stale_ids:
        await db[STUDENT_MCQ_ATTEMPTS].delete_many({"_id": {"$in": stale_ids}})


@router.post("/student-attempts/sync")
async def sync_student_attempts(body: StudentMcqSyncRequest):
    student_id = body.studentId.strip().upper()
    await _validate_existing_student_login(student_id, body.password)
    db = get_db()
    accepted = 0
    for attempt in body.attempts:
        doc = attempt.model_dump()
        doc.update({
            "studentId": student_id,
            "syncedAt": _now(),
        })
        await db[STUDENT_MCQ_ATTEMPTS].update_one(
            {
                "studentId": student_id,
                "kind": doc["kind"],
                "attemptId": doc["attemptId"],
            },
            {"$set": doc},
            upsert=True,
        )
        accepted += 1

    await _prune_student_attempts(db, student_id, "daily", settings.mcq_daily_retention)
    await _prune_student_attempts(db, student_id, "practice", settings.mcq_practice_retention)
    await db[ANALYTICS_AUDIT_SYNC].insert_one({
        "at": _now(),
        "studentId": student_id,
        "action": "mcq_attempt_sync",
        "detail": {"accepted": accepted},
    })
    await dump_store()
    return {"ok": True, "accepted": accepted}


@router.post("/student-attempts/restore")
async def restore_student_attempts(body: StudentTokenRequest):
    student_id = body.studentId.strip().upper()
    await _validate_existing_student_login(student_id, body.password)
    db = get_db()
    daily = []
    practice = []
    async for doc in db[STUDENT_MCQ_ATTEMPTS].find(
        {"studentId": student_id}, {"_id": 0, "studentId": 0, "syncedAt": 0}
    ).sort("completedAt", -1):
        (daily if doc.get("kind") == "daily" else practice).append(doc)
    return {
        "studentId": student_id,
        "daily": daily[: settings.mcq_daily_retention],
        "practice": practice[: settings.mcq_practice_retention],
    }


@router.get("/student-attempts/mentor")
async def mentor_student_attempts(
    studentId: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=100, ge=1, le=330),
    claims: dict = Depends(require_mentor),
):
    """Mentor-readable raw attempt history; the mentor UI can consume this later."""
    student_id = studentId.strip().upper()
    db = get_db()
    items = []
    async for doc in db[STUDENT_MCQ_ATTEMPTS].find(
        {"studentId": student_id}, {"_id": 0}
    ).sort("completedAt", -1).limit(limit):
        items.append(doc)
    return {"studentId": student_id, "items": items}
