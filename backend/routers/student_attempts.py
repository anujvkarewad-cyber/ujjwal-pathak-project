"""Authenticated cloud backup/restore for completed student MCQ attempts."""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from config import settings
from db import ANALYTICS_AUDIT_SYNC, CONTENT_QUESTIONS, CONTENT_SCENARIOS, STUDENT_MCQ_ATTEMPTS, get_db
from models import StudentMcqSyncRequest, StudentTokenRequest
from persist import dump_store
from routers.student_content import _student_question

router = APIRouter(prefix="/api", tags=["student-mcq-attempts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _validate_existing_student_login(student_id: str, password: str) -> dict:
    from routers.student_auth import authenticate_student

    mongo_result = await authenticate_student(student_id, password)
    if mongo_result.get("success") is True:
        return mongo_result

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
        if mongo_result.get("code") == "wrong_password":
            raise HTTPException(status_code=401, detail="Invalid Student ID or password")
        raise HTTPException(status_code=503, detail="Student login service is unavailable") from exc
    if response.status_code != 200:
        if mongo_result.get("code") == "wrong_password":
            raise HTTPException(status_code=401, detail="Invalid Student ID or password")
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


async def _question_lookup(db, question_ids: list[str]) -> dict:
    if not question_ids:
        return {}
    scenarios: dict = {}
    async for scenario in db[CONTENT_SCENARIOS].find({}):
        scenarios[scenario["scenarioId"]] = scenario
    found = {}
    async for doc in db[CONTENT_QUESTIONS].find({"id": {"$in": question_ids}}):
        found[doc.get("id")] = _student_question(doc, scenarios)
    return found


def _review_from_bank(question_ids: list, answers: dict, bank: dict) -> list:
    review = []
    for qid in question_ids:
        question = bank.get(qid)
        if not question:
            continue
        selected = answers.get(qid)
        if selected is not None:
            try:
                selected = int(selected)
            except (TypeError, ValueError):
                selected = None
        correct_index = int(question.get("answer") or 0)
        review.append({
            "id": qid,
            "prompt": question.get("prompt") or "",
            "options": question.get("options") or [],
            "answer": correct_index,
            "selected": selected,
            "explanation": question.get("explanation") or "",
            "subject": question.get("subject") or "",
            "chapter": question.get("chapter") or "",
            "difficulty": question.get("difficulty") or "",
            "kind": question.get("kind") or "",
            "correct": selected == correct_index,
        })
    return review


async def _ensure_review(db, doc: dict) -> dict:
    if not isinstance(doc, dict):
        return doc
    if doc.get("review"):
        return doc
    question_ids = list(doc.get("questionIds") or [])
    answers = doc.get("answers") or {}
    bank = await _question_lookup(db, question_ids)
    review = _review_from_bank(question_ids, answers, bank)
    if review:
        doc["review"] = review
        await db[STUDENT_MCQ_ATTEMPTS].update_one(
            {"studentId": doc.get("studentId"), "kind": doc.get("kind"), "attemptId": doc.get("attemptId")},
            {"$set": {"review": review}},
        )
    return doc


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
        if not doc.get("review"):
            bank = await _question_lookup(db, list(doc.get("questionIds") or []))
            review = _review_from_bank(list(doc.get("questionIds") or []), doc.get("answers") or {}, bank)
            if review:
                doc["review"] = review
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
        {"studentId": student_id}, {"_id": 0, "syncedAt": 0}
    ).sort("completedAt", -1):
        doc = await _ensure_review(db, doc)
        doc.pop("studentId", None)
        (daily if doc.get("kind") == "daily" else practice).append(doc)
    return {
        "studentId": student_id,
        "daily": daily[: settings.mcq_daily_retention],
        "practice": practice[: settings.mcq_practice_retention],
    }
