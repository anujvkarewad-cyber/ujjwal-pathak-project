"""AI Content review APIs (mentor-only).

Review status flow (docs §7.1):
generated → auto_validated → needs_review → changes_requested | rejected | approved
→ release_candidate → published → superseded
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_mentor
from content_validation import chapter_gate, validate_question, validate_scenario
from db import (
    CONTENT_AUDIT,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_RELEASES,
    CONTENT_SCENARIOS,
    get_db,
)
from models import DecisionRequest, QuestionUpdate

router = APIRouter(prefix="/api/content", tags=["content"])

APPROVED_SET = {"approved", "release_candidate", "published"}
MENTOR_TOUCHED = {"changes_requested", "rejected", "approved", "release_candidate", "published", "superseded"}


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _audit(db, entity_id, entity_type, action, by, detail=None):
    await db[CONTENT_AUDIT].insert_one(
        {
            "at": _now(),
            "by": by,
            "action": action,
            "entityId": entity_id,
            "entityType": entity_type,
            "detail": detail or {},
        }
    )


def _push_history(doc: dict, to: str, by: str):
    history = doc.get("statusHistory") or []
    prev = history[-1]["to"] if history else None
    history.append({"from": prev, "to": to, "by": by, "at": _now()})
    doc["statusHistory"] = history
    doc["status"] = to


@router.get("/queue")
async def review_queue(
    subject: Optional[str] = None,
    group: Optional[str] = None,
    chapterId: Optional[str] = None,
    questionType: Optional[str] = None,
    difficulty: Optional[str] = None,
    status: Optional[str] = None,
    hasWarnings: Optional[bool] = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    claims: dict = Depends(require_mentor),
):
    db = get_db()
    filt: dict = {}
    if subject:
        filt["subject"] = subject
    if chapterId:
        filt["chapterId"] = chapterId
    if questionType:
        filt["questionType"] = questionType
    if difficulty:
        filt["difficulty"] = difficulty
    if status:
        filt["status"] = status
    # group filter needs the catalog/group denormalized on questions
    # (group is stamped on chapter records; questions carry subject only)
    if group:
        chapter_ids = []
        async for c in db[CONTENT_CHAPTERS].find({"group": group}, {"chapterId": 1}):
            chapter_ids.append(c["chapterId"])
        if not chapter_ids:
            return {"total": 0, "items": []}
        filt["chapterId"] = {"$in": chapter_ids}

    total = await db[CONTENT_QUESTIONS].count_documents(filt)
    cursor = db[CONTENT_QUESTIONS].find(filt).sort([("chapterId", 1), ("id", 1)]).skip(offset).limit(limit)
    items = []
    async for doc in cursor:
        doc.pop("_id", None)
        if hasWarnings is not None:
            has = bool((doc.get("validation") or {}).get("warnings"))
            if has != hasWarnings:
                continue
        items.append(doc)
    return {"total": total, "items": items}


@router.get("/questions/{question_id}")
async def get_question(question_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[CONTENT_QUESTIONS].find_one({"id": question_id}, sort=[("revision", -1)])
    if not doc:
        raise HTTPException(status_code=404, detail="Question not found")
    doc.pop("_id", None)
    return doc


@router.put("/questions/{question_id}")
async def update_question(question_id: str, body: QuestionUpdate, claims: dict = Depends(require_mentor)):
    """Edit prompt/options/correct/explanation/difficulty/tags with
    server-side revalidation. Editing an approved/published question creates a
    new revision and supersedes the previous one."""
    db = get_db()
    doc = await db[CONTENT_QUESTIONS].find_one({"id": question_id, "status": {"$nin": ["superseded", "rejected"]}}, sort=[("revision", -1)])
    if not doc:
        raise HTTPException(status_code=404, detail="Question not found or not editable")

    editable = {
        "prompt": body.prompt,
        "options": [o.model_dump() for o in body.options] if body.options is not None else None,
        "correctOptionId": body.correctOptionId,
        "explanation": body.explanation,
        "difficulty": body.difficulty,
        "conceptTags": body.conceptTags,
        "attemptSpecificRiskConfirmed": body.attemptSpecificRiskConfirmed,
        "warningsAcknowledged": body.warningsAcknowledged,
    }
    candidate = {**doc, **{k: v for k, v in editable.items() if v is not None}}

    errors, warnings = validate_question(candidate)
    candidate["validation"] = {"errors": errors, "warnings": warnings, "revalidatedAt": _now()}

    if doc["status"] in APPROVED_SET:
        # Edit of approved content → new revision, old one superseded.
        await db[CONTENT_QUESTIONS].update_one({"id": question_id, "status": doc["status"]}, {"$set": {"status": "superseded", "supersededAt": _now()}})
        candidate["revision"] = int(doc.get("revision", 1)) + 1
        candidate["approval"] = None
        _push_history(candidate, "needs_review", claims.get("sub", "mentor"))
        candidate["editedFromStatus"] = doc["status"]
        candidate.pop("_id", None)
        await db[CONTENT_QUESTIONS].insert_one(candidate)
    else:
        _push_history(candidate, "needs_review", claims.get("sub", "mentor"))
        await db[CONTENT_QUESTIONS].replace_one({"id": question_id, "status": {"$nin": ["superseded"]}}, candidate)

    await _audit(db, question_id, "question", "edit", claims.get("sub", "mentor"), {"fields": [k for k, v in editable.items() if v is not None]})
    candidate.pop("_id", None)
    return candidate


@router.post("/questions/{question_id}/decision")
async def decide_question(question_id: str, body: DecisionRequest, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[CONTENT_QUESTIONS].find_one({"id": question_id, "status": {"$nin": ["superseded"]}}, sort=[("revision", -1)])
    if not doc:
        raise HTTPException(status_code=404, detail="Question not found")

    decision = body.decision.value
    if decision == "approve":
        errors, warnings = validate_question(doc)
        if errors:
            raise HTTPException(status_code=422, detail={"message": "Question has blocking validation errors", "errors": errors})
        if warnings and not (body.warningsAcknowledged or doc.get("warningsAcknowledged")):
            raise HTTPException(status_code=422, detail={"message": "Warnings require acknowledgement before approval", "warnings": warnings})
        if doc.get("attemptSpecificRisk") and not (body.attemptSpecificRiskConfirmed or doc.get("attemptSpecificRiskConfirmed")):
            raise HTTPException(status_code=422, detail={"message": "Attempt-specific risk requires explicit mentor confirmation"})
        _push_history(doc, "approved", claims.get("sub", "mentor"))
        doc["approval"] = {"mentorId": claims.get("sub"), "at": _now(), "comments": body.comment}
    elif decision == "reject":
        _push_history(doc, "rejected", claims.get("sub", "mentor"))
        doc["rejectionReason"] = body.comment
    else:
        _push_history(doc, "changes_requested", claims.get("sub", "mentor"))
        doc["changeRequest"] = {"mentorId": claims.get("sub"), "at": _now(), "comment": body.comment}

    if body.warningsAcknowledged:
        doc["warningsAcknowledged"] = True
    if body.attemptSpecificRiskConfirmed:
        doc["attemptSpecificRiskConfirmed"] = True

    await db[CONTENT_QUESTIONS].replace_one({"id": question_id, "status": {"$nin": ["superseded"]}}, doc)
    await _audit(db, question_id, "question", decision, claims.get("sub", "mentor"), {"comment": body.comment})
    doc.pop("_id", None)
    return doc


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[CONTENT_SCENARIOS].find_one({"scenarioId": scenario_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    doc.pop("_id", None)
    questions = []
    for qid in doc.get("questionIds") or []:
        q = await db[CONTENT_QUESTIONS].find_one({"id": qid})
        if q:
            q.pop("_id", None)
            questions.append(q)
    doc["questions"] = questions
    return doc


@router.post("/scenarios/{scenario_id}/decision")
async def decide_scenario(scenario_id: str, body: DecisionRequest, claims: dict = Depends(require_mentor)):
    """Approve/reject the WHOLE scenario block (passage + 4 linked MCQs)."""
    db = get_db()
    scenario = await db[CONTENT_SCENARIOS].find_one({"scenarioId": scenario_id})
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    question_ids = scenario.get("questionIds") or []
    if len(question_ids) != 4:
        raise HTTPException(status_code=422, detail="Scenario does not link exactly 4 questions")
    questions = []
    for qid in question_ids:
        q = await db[CONTENT_QUESTIONS].find_one({"id": qid, "status": {"$nin": ["superseded"]}})
        if not q:
            raise HTTPException(status_code=422, detail=f"Linked question {qid} not found")
        questions.append(q)

    decision = body.decision.value
    if decision == "approve":
        s_errors, s_warnings = validate_scenario(scenario)
        errors = list(s_errors)
        warnings = list(s_warnings)
        for q in questions:
            q_errors, q_warnings = validate_question(q)
            errors.extend(f"{q['id']}: {e}" for e in q_errors)
            warnings.extend(f"{q['id']}: {w}" for w in q_warnings)
        if errors:
            raise HTTPException(status_code=422, detail={"message": "Block has validation errors", "errors": errors})
        if warnings and not body.warningsAcknowledged:
            raise HTTPException(status_code=422, detail={"message": "Warnings require acknowledgement", "warnings": warnings})
        _push_history(scenario, "approved", claims.get("sub", "mentor"))
        scenario["approval"] = {"mentorId": claims.get("sub"), "at": _now(), "comments": body.comment}
        await db[CONTENT_SCENARIOS].replace_one({"scenarioId": scenario_id}, scenario)
        for q in questions:
            _push_history(q, "approved", claims.get("sub", "mentor"))
            q["approval"] = {"mentorId": claims.get("sub"), "at": _now(), "comments": body.comment, "viaScenario": scenario_id}
            q["warningsAcknowledged"] = True
            if q.get("attemptSpecificRisk"):
                q["attemptSpecificRiskConfirmed"] = body.attemptSpecificRiskConfirmed
            await db[CONTENT_QUESTIONS].replace_one({"id": q["id"]}, q)
        await _audit(db, scenario_id, "scenario", "approve_block", claims.get("sub", "mentor"), {"questions": question_ids, "comment": body.comment})
    else:  # reject
        _push_history(scenario, "rejected", claims.get("sub", "mentor"))
        scenario["rejectionReason"] = body.comment
        await db[CONTENT_SCENARIOS].replace_one({"scenarioId": scenario_id}, scenario)
        for q in questions:
            _push_history(q, "rejected", claims.get("sub", "mentor"))
            q["rejectionReason"] = body.comment
            await db[CONTENT_QUESTIONS].replace_one({"id": q["id"]}, q)
        await _audit(db, scenario_id, "scenario", "reject_block", claims.get("sub", "mentor"), {"questions": question_ids, "comment": body.comment})

    scenario.pop("_id", None)
    return scenario


@router.get("/chapters")
async def list_chapters(
    subject: Optional[str] = None,
    group: Optional[str] = None,
    status: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    db = get_db()
    filt: dict = {}
    if subject:
        filt["subject"] = subject
    if group:
        filt["group"] = group
    if status:
        filt["status"] = status
    chapters = []
    async for c in db[CONTENT_CHAPTERS].find(filt).sort("chapterId", 1):
        c.pop("_id", None)
        # refresh coverage from DB counts
        plain = await db[CONTENT_QUESTIONS].count_documents({"chapterId": c["chapterId"], "questionType": "mcq", "status": {"$in": list(APPROVED_SET)}})
        scenarios = await db[CONTENT_SCENARIOS].count_documents({"chapterId": c["chapterId"], "status": {"$in": list(APPROVED_SET)}})
        scenario_mcqs = await db[CONTENT_QUESTIONS].count_documents({"chapterId": c["chapterId"], "questionType": "scenario_mcq", "status": {"$in": list(APPROVED_SET)}})
        c["coverage"] = {
            "plainApproved": plain, "plainTarget": 30,
            "scenariosApproved": scenarios, "scenariosTarget": 5,
            "scenarioMcqsApproved": scenario_mcqs, "scenarioMcqsTarget": 20,
        }
        chapters.append(c)
    return {"items": chapters}


@router.get("/chapters/{chapter_id}/gate")
async def chapter_gate_status(chapter_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    questions = []
    async for q in db[CONTENT_QUESTIONS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        q.pop("_id", None)
        questions.append(q)
    scenarios = []
    async for s in db[CONTENT_SCENARIOS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        s.pop("_id", None)
        scenarios.append(s)
    gate = chapter_gate(chapter_id, questions, scenarios)
    return {"chapterId": chapter_id, "publishable": len(gate["errors"]) == 0, **gate}


@router.post("/chapters/{chapter_id}/approve")
async def approve_chapter(chapter_id: str, claims: dict = Depends(require_mentor)):
    """Mentor confirms the chapter gate → release candidate. The actual bundle
    build + manifest publish is done by the pipeline (stage-11)."""
    db = get_db()
    questions = []
    async for q in db[CONTENT_QUESTIONS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        questions.append(q)
    scenarios = []
    async for s in db[CONTENT_SCENARIOS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        scenarios.append(s)
    gate = chapter_gate(chapter_id, questions, scenarios)
    if gate["errors"]:
        raise HTTPException(status_code=422, detail={"message": "Chapter gate not met", "errors": gate["errors"]})

    await db[CONTENT_QUESTIONS].update_many(
        {"chapterId": chapter_id, "status": "approved"}, {"$set": {"status": "release_candidate"}}
    )
    await db[CONTENT_SCENARIOS].update_many(
        {"chapterId": chapter_id, "status": "approved"}, {"$set": {"status": "release_candidate"}}
    )
    await db[CONTENT_CHAPTERS].update_one(
        {"chapterId": chapter_id},
        {"$set": {"status": "release_candidate", "releaseCandidate": {"at": _now(), "by": claims.get("sub")}}},
    )
    await _audit(db, chapter_id, "chapter", "approve_chapter", claims.get("sub", "mentor"), {"coverage": gate["coverage"]})
    return {"ok": True, "chapterId": chapter_id, "coverage": gate["coverage"]}


@router.get("/releases")
async def list_releases(limit: int = Query(default=50, le=200), claims: dict = Depends(require_mentor)):
    db = get_db()
    releases = []
    async for r in db[CONTENT_RELEASES].find({}).sort("revision", -1).limit(limit):
        r.pop("_id", None)
        releases.append(r)
    return {"items": releases}


@router.get("/releases/{revision}")
async def get_release(revision: int, claims: dict = Depends(require_mentor)):
    db = get_db()
    r = await db[CONTENT_RELEASES].find_one({"revision": revision})
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    r.pop("_id", None)
    return r


@router.get("/audit")
async def audit_history(
    entityId: Optional[str] = None,
    action: Optional[str] = None,
    by: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    claims: dict = Depends(require_mentor),
):
    db = get_db()
    filt: dict = {}
    if entityId:
        filt["entityId"] = entityId
    if action:
        filt["action"] = action
    if by:
        filt["by"] = by
    items = []
    async for row in db[CONTENT_AUDIT].find(filt).sort("at", -1).limit(limit):
        row.pop("_id", None)
        items.append(row)
    return {"items": items}


@router.get("/validation/{question_id}")
async def validation_detail(question_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[CONTENT_QUESTIONS].find_one({"id": question_id}, sort=[("revision", -1)])
    if not doc:
        raise HTTPException(status_code=404, detail="Question not found")
    return {
        "id": question_id,
        "status": doc.get("status"),
        "validation": doc.get("validation") or {},
        "similarity": doc.get("similarity") or {},
        "icaiSourceRefs": doc.get("icaiSourceRefs") or [],
        "calibrationRefs": doc.get("calibrationRefs") or [],
        "statusHistory": doc.get("statusHistory") or [],
    }
