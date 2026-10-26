"""Authenticated cloud backup/restore for completed student MCQ attempts.

Current imported-account credentials/access are authoritative. Unverified legacy
migration is unavailable, never a fallback around denial or unknown accounts.
Only completed, size-bounded Daily/Practice attempts are accepted.
"""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from config import settings
from db import ANALYTICS_AUDIT_SYNC, CONTENT_QUESTIONS, CONTENT_SCENARIOS, STUDENT_MCQ_ATTEMPTS, get_db
from models import StudentMcqSyncRequest, StudentTokenRequest, OfficialDailySetRequest
from persist import dump_store_sync
from daily_mcq_verification import issue_set, verify_attempt, response_fingerprint, SETS
from pymongo.errors import DuplicateKeyError
from routers.student_content import _student_question

router = APIRouter(prefix="/api", tags=["student-mcq-attempts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _validate_existing_student_login(student_id: str, password: str) -> dict:
    """Validate current imported account; block unverified migration."""
    from routers.student_auth import authenticate_student

    mongo_result = await authenticate_student(student_id, password)
    if mongo_result.get("success") is True:
        return mongo_result
    if mongo_result.get("code") != "not_found":
        # A legacy service must never override an imported account's denial.
        code = mongo_result.get("code")
        raise HTTPException(status_code=403 if code in {"removed", "access_blocked", "group_closed"} else 401,
                            detail="Student authentication unavailable.")

    # The deployed legacy authority/migration checks are unavailable. Do not
    # accept an unknown account via that path until independently verified.
    raise HTTPException(status_code=503, detail="Student migration verification unavailable.")


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
    if doc.get('officialSetId'):
        official = await db[SETS].find_one({'_id': doc['officialSetId'], 'studentId': doc.get('studentId')})
        if official:
            doc['officialQuestions'] = official['questions']
            doc['review'] = _review_from_bank(doc['questionIds'], doc.get('answers') or {}, {q['id']: q for q in official['questions']})
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
    # The legacy backup limit must not delete official grading evidence or its
    # immutable response fingerprint. Ranking reads this same canonical store.
    cursor = db[STUDENT_MCQ_ATTEMPTS].find(
        {"studentId": student_id, "kind": kind, "officialSetId": {"$in": [None, ""]}}, {"_id": 1}
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
    acknowledgements = []
    for attempt in body.attempts:
        doc = attempt.model_dump()
        original_id = doc['attemptId']
        verdict = await verify_attempt(db, student_id, doc)
        doc.update(studentId=student_id, syncedAt=_now(), rankingVerification=verdict)
        key = {"studentId": student_id, "kind": doc['kind'], "attemptId": doc['attemptId']}
        if doc.get('officialSetId'):
            doc['attemptId'] = f"daily:{doc['date']}:{doc['group']}"
            key['attemptId'] = doc['attemptId']
            doc['responseFingerprint'] = response_fingerprint(doc)
            if verdict['eligible']:
                doc['score'] = verdict['correct']; doc['total'] = 10
            # Immutable submission + exact replay; never silently replace a completed answer set.
            existing = await db[STUDENT_MCQ_ATTEMPTS].find_one(key)
            if existing and existing.get('responseFingerprint') != doc['responseFingerprint']:
                raise HTTPException(409, 'Conflicting Daily MCQ backup; local answers are retained, not overwritten')
            try:
                result = await db[STUDENT_MCQ_ATTEMPTS].update_one(key, {'$setOnInsert': doc}, upsert=True)
            except DuplicateKeyError:
                result = None
            saved = await db[STUDENT_MCQ_ATTEMPTS].find_one(key)
            if saved.get('responseFingerprint') != doc['responseFingerprint']:
                raise HTTPException(409, 'Conflicting Daily MCQ backup; local answers are retained, not overwritten')
            status = 'stored' if result and result.upserted_id else 'duplicate'
        else:
            # Never let an older client overwrite verified data under the canonical daily key.
            existing = await db[STUDENT_MCQ_ATTEMPTS].find_one(key)
            if existing and existing.get('officialSetId'):
                raise HTTPException(409, 'Official Daily MCQ backup is immutable')
            await db[STUDENT_MCQ_ATTEMPTS].update_one(key, {'$set': doc}, upsert=True)
            status = 'stored'
        accepted += 1
        acknowledgements.append({'attemptId': original_id, 'status': status,
                                 'rankingEligible': verdict['eligible'], 'reason': verdict['reason']})

    await _prune_student_attempts(db, student_id, "daily", settings.mcq_daily_retention)
    await _prune_student_attempts(db, student_id, "practice", settings.mcq_practice_retention)
    await db[ANALYTICS_AUDIT_SYNC].insert_one({
        "at": _now(),
        "studentId": student_id,
        "action": "mcq_attempt_sync",
        "detail": {"accepted": accepted},
    })
    await dump_store_sync()
    return {"ok": True, "accepted": accepted, "acknowledgements": acknowledgements}


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


@router.post('/student-attempts/daily-set')
async def official_daily_set(body: OfficialDailySetRequest):
    student_id = body.studentId.strip().upper()
    profile = await _validate_existing_student_login(student_id, body.password)
    assignment = await issue_set(get_db(), student_id, profile, body.group)
    await dump_store_sync()
    return assignment
