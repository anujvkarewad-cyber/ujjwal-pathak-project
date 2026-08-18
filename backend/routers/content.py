"""AI Content review APIs (mentor-only).

Review status flow (docs §7.1):
generated → auto_validated → needs_review → changes_requested | rejected | approved
→ release_candidate → published → superseded
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_mentor
from config import settings
from content_validation import chapter_gate, validate_question, validate_scenario
from db import (
    CONTENT_AUDIT,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_RELEASES,
    CONTENT_SCENARIOS,
    get_db,
)
from models import ChapterPublishRequest, DecisionRequest, QuestionUpdate
from persist import dump_store

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


async def _promote_complete_scenarios(db, chapter_id: str, by: str = "system") -> int:
    """Approve scenario blocks whose 4 linked MCQs are already approved.

    Mentors typically approve questions one-by-one (Review Queue / Approve &
    Next). Without this, the chapter Gate stays locked on
    \"5 scenarios not all approved\" even after all 50 questions are approved.
    """
    if not chapter_id:
        return 0
    pending = []
    async for scenario in db[CONTENT_SCENARIOS].find(
        {"chapterId": chapter_id, "status": {"$nin": list(APPROVED_SET | {"rejected", "superseded"})}}
    ):
        pending.append(scenario)
    if not pending:
        return 0
    # Single pass: collect the chapter's approved question ids once instead of
    # issuing 4 find_one() calls per pending scenario.
    approved_ids = set()
    async for q in db[CONTENT_QUESTIONS].find(
        {"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}, {"id": 1}
    ):
        approved_ids.add(q.get("id"))
    promoted = 0
    for scenario in pending:
        qids = scenario.get("questionIds") or []
        if len(qids) != 4 or not all(qid in approved_ids for qid in qids):
            continue
        sid = scenario.get("scenarioId")
        scenario.pop("_id", None)
        _push_history(scenario, "approved", by)
        scenario["approval"] = scenario.get("approval") or {
            "mentorId": by,
            "at": _now(),
            "comments": "auto-approved: all 4 linked MCQs approved",
        }
        await db[CONTENT_SCENARIOS].replace_one({"scenarioId": sid}, scenario)
        promoted += 1
    return promoted


def _content_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _strip_id(doc: dict) -> dict:
    out = dict(doc)
    out.pop("_id", None)
    return out


async def _load_publishable(db, chapter_id: str):
    questions = []
    async for q in db[CONTENT_QUESTIONS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        questions.append(_strip_id(q))
    scenarios = []
    async for s in db[CONTENT_SCENARIOS].find({"chapterId": chapter_id, "status": {"$in": list(APPROVED_SET)}}):
        scenarios.append(_strip_id(s))
    return questions, scenarios


def _write_release_files(revision: int, chapter_id: str, questions: list, scenarios: list, published_at: str, published_by: str) -> dict:
    """Write a stage-11-compatible manifest + chapter chunks so students can fetch them."""
    root = settings.content_dir
    root.mkdir(parents=True, exist_ok=True)
    (root / "web" / "chunks").mkdir(parents=True, exist_ok=True)
    (root / "mobile" / "chunks").mkdir(parents=True, exist_ok=True)

    plain = [q for q in questions if q.get("questionType") == "mcq"]
    scenario_qs = [q for q in questions if q.get("questionType") == "scenario_mcq"]
    bundle = {
        "chapterId": chapter_id,
        "revision": revision,
        "catalogRevision": "may-2026",
        "plainQuestions": plain,
        "scenarios": [
            {
                "scenarioId": s.get("scenarioId"),
                "passage": s.get("passage"),
                "icaiSourceRefs": s.get("icaiSourceRefs"),
                "calibrationRefs": s.get("calibrationRefs"),
                "questionIds": s.get("questionIds"),
                "questions": [q for q in scenario_qs if q.get("id") in (s.get("questionIds") or [])],
            }
            for s in scenarios
        ],
    }
    digest = _content_hash(bundle)
    short = digest.replace("sha256:", "")[:8]
    web_rel = f"chunks/{chapter_id}.r{revision}.{short}.json"
    mobile_rel = f"chunks/m/{chapter_id}.r{revision}.{short}.json"
    (root / "web" / "chunks").mkdir(parents=True, exist_ok=True)
    (root / "mobile" / "chunks" / "m").mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, default=str, indent=2) + "\n"
    (root / "web" / web_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / "mobile" / mobile_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / "web" / web_rel).write_text(payload, encoding="utf-8")
    (root / "mobile" / mobile_rel).write_text(payload, encoding="utf-8")

    chapter_entry = {
        "chapterId": chapter_id,
        "counts": {
            "plain": len(plain),
            "scenarios": len(scenarios),
            "scenarioMcqs": len(scenario_qs),
            "total": len(plain) + len(scenario_qs),
        },
        "questionIds": sorted(q.get("id") for q in questions if q.get("id")),
        "chunkWeb": web_rel,
        "chunkMobile": mobile_rel,
        "contentHash": digest,
    }

    manifest_path = root / "published-manifest.json"
    prev = {}
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    kept = [c for c in (prev.get("chapters") or []) if c.get("chapterId") != chapter_id]
    kept.append(chapter_entry)
    manifest = {
        "schemaVersion": 1,
        "revision": revision,
        "publishedAt": published_at,
        "publishedBy": published_by,
        "catalogRevision": "may-2026",
        "chapters": sorted(kept, key=lambda c: c.get("chapterId") or ""),
    }
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    return {"manifest": manifest, "chapter": chapter_entry}


@router.get("/stats")
async def content_stats(claims: dict = Depends(require_mentor)):
    """Counts for the main mentor dashboard MCQ review card."""
    db = get_db()
    total = await db[CONTENT_QUESTIONS].count_documents({})
    chapters = await db[CONTENT_CHAPTERS].count_documents({})
    needs_review = await db[CONTENT_QUESTIONS].count_documents({"status": "needs_review"})
    approved = await db[CONTENT_QUESTIONS].count_documents({"status": {"$in": list(APPROVED_SET)}})
    rejected = await db[CONTENT_QUESTIONS].count_documents({"status": "rejected"})
    changes = await db[CONTENT_QUESTIONS].count_documents({"status": "changes_requested"})
    return {
        "total": total,
        "chapters": chapters,
        "needsReview": needs_review,
        "approved": approved,
        "rejected": rejected,
        "changesRequested": changes,
    }


@router.get("/queue")
async def review_queue(
    subject: Optional[str] = None,
    group: Optional[str] = None,
    chapterId: Optional[str] = None,
    questionType: Optional[str] = None,
    difficulty: Optional[str] = None,
    status: Optional[str] = None,
    hasWarnings: Optional[bool] = None,
    view: Optional[Literal["summary", "scenario_index", "references"]] = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
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
    if hasWarnings is True:
        filt["validation.warnings.0"] = {"$exists": True}
    elif hasWarnings is False:
        filt["$and"] = filt.get("$and", []) + [
            {
                "$or": [
                    {"validation.warnings": {"$exists": False}},
                    {"validation.warnings": []},
                    {"validation.warnings": None},
                ]
            }
        ]
    # group filter needs the catalog/group denormalized on questions
    # (group is stamped on chapter records; questions carry subject only)
    if group:
        chapter_ids = []
        async for c in db[CONTENT_CHAPTERS].find({"group": group}, {"chapterId": 1}):
            chapter_ids.append(c["chapterId"])
        if not chapter_ids:
            return {"total": 0, "limit": limit, "offset": offset, "items": []}
        filt["chapterId"] = {"$in": chapter_ids}

    total = await db[CONTENT_QUESTIONS].count_documents(filt)

    # List screens need only a small projection. Returning complete question
    # documents (options, explanations, histories, similarity and metadata)
    # made a 50-row page ~128 KiB and the 4,700-row reference/index requests
    # ~12 MiB. Full documents remain available from /questions/{id}.
    projections = {
        "summary": {
            "_id": 0,
            "id": 1,
            "prompt": 1,
            "chapterId": 1,
            "chapterTitle": 1,
            "questionType": 1,
            "difficulty": 1,
            "status": 1,
            "validation.warnings": 1,
        },
        "scenario_index": {
            "_id": 0,
            "id": 1,
            "chapterId": 1,
            "status": 1,
            "scenario": 1,
        },
        "references": {
            "_id": 0,
            "id": 1,
            "prompt": 1,
            "icaiSourceRefs": 1,
            "calibrationRefs": 1,
        },
    }
    projection = projections.get(view)
    cursor = db[CONTENT_QUESTIONS].find(filt, projection).sort([("chapterId", 1), ("id", 1)]).skip(offset).limit(limit)
    items = []
    async for doc in cursor:
        doc.pop("_id", None)
        items.append(doc)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


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
    await dump_store()
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
    await dump_store()
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

    await dump_store()
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
        chapters.append(c)
    if not chapters:
        return {"items": []}

    by_id = {c["chapterId"]: c for c in chapters if c.get("chapterId")}
    wanted = set(by_id)
    pending_scenarios: dict = {}          # chapterId -> [scenario, ...] not yet approved
    approved_scenarios: dict = {}         # chapterId -> count
    approved_qids: dict = {}              # chapterId -> {question id, ...} (approved)
    plain_counts: dict = {}               # chapterId -> approved plain MCQ count
    scenario_mcq_counts: dict = {}        # chapterId -> approved scenario MCQ count

    # Single pass over questions: one full scan instead of 2 count_documents
    # per chapter (mongomock has no indexes, so per-chapter counts were O(N)
    # full-collection scans — ~14s for 94 chapters / 4700 questions).
    async for q in db[CONTENT_QUESTIONS].find(
        {"status": {"$in": list(APPROVED_SET)}}, {"chapterId": 1, "questionType": 1, "id": 1}
    ):
        cid = q.get("chapterId")
        if cid not in wanted:
            continue
        approved_qids.setdefault(cid, set()).add(q.get("id"))
        if q.get("questionType") == "mcq":
            plain_counts[cid] = plain_counts.get(cid, 0) + 1
        elif q.get("questionType") == "scenario_mcq":
            scenario_mcq_counts[cid] = scenario_mcq_counts.get(cid, 0) + 1

    # Single pass over scenarios: split approved vs pending per chapter.
    async for s in db[CONTENT_SCENARIOS].find({}):
        cid = s.get("chapterId")
        if cid not in wanted:
            continue
        status = s.get("status")
        if status in APPROVED_SET:
            approved_scenarios[cid] = approved_scenarios.get(cid, 0) + 1
        elif status not in ("rejected", "superseded"):
            pending_scenarios.setdefault(cid, []).append(s)

    # Promote scenario blocks whose 4 linked MCQs are already approved, so the
    # Gate button is not stuck after question-by-question review.
    by = claims.get("sub", "mentor")
    for cid, scenarios_list in pending_scenarios.items():
        qids_approved = approved_qids.get(cid, set())
        for scenario in scenarios_list:
            qids = scenario.get("questionIds") or []
            if len(qids) != 4 or not all(qid in qids_approved for qid in qids):
                continue
            sid = scenario.get("scenarioId")
            scenario.pop("_id", None)
            _push_history(scenario, "approved", by)
            scenario["approval"] = scenario.get("approval") or {
                "mentorId": by,
                "at": _now(),
                "comments": "auto-approved: all 4 linked MCQs approved",
            }
            await db[CONTENT_SCENARIOS].replace_one({"scenarioId": sid}, scenario)
            approved_scenarios[cid] = approved_scenarios.get(cid, 0) + 1

    for cid, c in by_id.items():
        c["coverage"] = {
            "plainApproved": plain_counts.get(cid, 0), "plainTarget": 30,
            "scenariosApproved": approved_scenarios.get(cid, 0), "scenariosTarget": 5,
            "scenarioMcqsApproved": scenario_mcq_counts.get(cid, 0), "scenarioMcqsTarget": 20,
        }
    return {"items": chapters}


@router.get("/chapters/{chapter_id}/gate")
async def chapter_gate_status(chapter_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    await _promote_complete_scenarios(db, chapter_id, claims.get("sub", "mentor"))
    questions, scenarios = await _load_publishable(db, chapter_id)
    gate = chapter_gate(chapter_id, questions, scenarios)
    return {
        "chapterId": chapter_id,
        "chapterTitle": chapter.get("chapterTitle") or chapter_id,
        "chapterStatus": chapter.get("status") or "needs_review",
        "publishable": len(gate["errors"]) == 0,
        **gate,
    }


@router.post("/chapters/{chapter_id}/approve")
async def approve_chapter(chapter_id: str, claims: dict = Depends(require_mentor)):
    """Mentor confirms the chapter gate → release candidate."""
    db = get_db()
    chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    await _promote_complete_scenarios(db, chapter_id, claims.get("sub", "mentor"))
    questions, scenarios = await _load_publishable(db, chapter_id)
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
    await dump_store()
    return {"ok": True, "chapterId": chapter_id, "status": "release_candidate", "coverage": gate["coverage"]}


@router.post("/chapters/{chapter_id}/publish")
async def publish_chapter(
    chapter_id: str,
    body: ChapterPublishRequest = ChapterPublishRequest(),
    claims: dict = Depends(require_mentor),
):
    """Mentor publishes a gated chapter from the dashboard (no pipeline CLI).

    Promotes approved items → release_candidate → published, writes a release
    record + student bundles, and persists so the Gate button actually ships
    content after approve-to-publish.
    """
    db = get_db()
    chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    by = claims.get("sub", "mentor")
    await _promote_complete_scenarios(db, chapter_id, by)
    questions, scenarios = await _load_publishable(db, chapter_id)
    gate = chapter_gate(chapter_id, questions, scenarios)
    if gate["errors"]:
        raise HTTPException(status_code=422, detail={"message": "Chapter gate not met", "errors": gate["errors"]})
    if gate["warnings"] and not body.warningsAcknowledged:
        raise HTTPException(status_code=422, detail={"message": "Warnings require acknowledgement", "warnings": gate["warnings"]})

    published_at = _now()
    latest = None
    async for row in db[CONTENT_RELEASES].find({}).sort("revision", -1).limit(1):
        latest = row
    revision = int((latest or {}).get("revision") or 0) + 1

    files_written = False
    chapter_entry = None
    manifest = None
    try:
        written = _write_release_files(revision, chapter_id, questions, scenarios, published_at, by)
        manifest = written["manifest"]
        chapter_entry = written["chapter"]
        files_written = True
    except OSError:
        chapter_entry = {
            "chapterId": chapter_id,
            "counts": gate["coverage"],
            "questionIds": [q.get("id") for q in questions],
            "contentHash": _content_hash({"chapterId": chapter_id, "revision": revision}),
        }
        manifest = {
            "schemaVersion": 1,
            "revision": revision,
            "publishedAt": published_at,
            "publishedBy": by,
            "catalogRevision": "may-2026",
            "chapters": [chapter_entry],
        }

    await db[CONTENT_QUESTIONS].update_many(
        {"chapterId": chapter_id, "status": {"$in": ["approved", "release_candidate"]}},
        {"$set": {"status": "published", "publishedInRevision": revision, "publishedAt": published_at}},
    )
    await db[CONTENT_SCENARIOS].update_many(
        {"chapterId": chapter_id, "status": {"$in": ["approved", "release_candidate"]}},
        {"$set": {"status": "published", "publishedInRevision": revision, "publishedAt": published_at}},
    )
    await db[CONTENT_CHAPTERS].update_one(
        {"chapterId": chapter_id},
        {"$set": {"status": "published", "releaseCandidate": {"revision": revision, "at": published_at, "by": by}}},
    )
    await db[CONTENT_RELEASES].insert_one(
        {
            "revision": revision,
            "manifest": manifest,
            "publishedAt": published_at,
            "publishedBy": by,
            "chapters": [chapter_id],
            "gates": [{"chapterId": chapter_id, **gate}],
        }
    )
    await _audit(db, chapter_id, "chapter", "publish", by, {"revision": revision, "coverage": gate["coverage"]})
    await dump_store()
    return {
        "ok": True,
        "chapterId": chapter_id,
        "status": "published",
        "revision": revision,
        "coverage": gate["coverage"],
        "filesWritten": files_written,
        "chapter": chapter_entry,
    }


# ── Bulk approve + publish (mentor one-click for large banks) ───────────────
#
# The per-question → gate → publish flow is correct for careful review, but a
# 4,700-question bank needs a mentor-driven bulk path. These endpoints approve
# AND publish every eligible item in scope in one shot, creating a proper
# release. Only documents with blocking validation errors are skipped (left in
# review and reported back) so broken questions never reach students.

BULK_ELIGIBLE = ["generated", "auto_validated", "needs_review", "changes_requested", "approved", "release_candidate"]


async def _next_revision(db) -> int:
    latest = None
    async for row in db[CONTENT_RELEASES].find({}).sort("revision", -1).limit(1):
        latest = row
    return int((latest or {}).get("revision") or 0) + 1


async def _bulk_approve_publish(q_filter: dict, s_filter: dict, c_filter: dict, scope: str, by: str) -> dict:
    db = get_db()
    now = _now()

    # 1) Questions in scope that are still eligible for review → validate each,
    #    publish the clean ones, skip (and report) the ones with blocking errors.
    valid_ids: list = []
    skipped: list = []
    async for q in db[CONTENT_QUESTIONS].find({**q_filter, "status": {"$in": BULK_ELIGIBLE}}):
        errors, _warnings = validate_question(q)
        if errors:
            skipped.append({"id": q.get("id"), "errors": errors[:3]})
        else:
            valid_ids.append(q.get("id"))
    already_published = await db[CONTENT_QUESTIONS].count_documents({**q_filter, "status": "published"})

    # 2) Scenario blocks: publish only those whose linked MCQs will all be live.
    live_ids = set(valid_ids)
    async for q in db[CONTENT_QUESTIONS].find({**q_filter, "status": "published"}, {"id": 1}):
        live_ids.add(q.get("id"))
    scenario_ids: list = []
    async for s in db[CONTENT_SCENARIOS].find({**s_filter, "status": {"$in": BULK_ELIGIBLE}}):
        s_errors, _s_warnings = validate_scenario(s)
        qids = s.get("questionIds") or []
        if s_errors or not all(qid in live_ids for qid in qids):
            continue
        scenario_ids.append(s.get("scenarioId"))

    # 3) One shared release revision for the whole bulk action.
    revision = await _next_revision(db)

    published_questions = 0
    if valid_ids:
        res = await db[CONTENT_QUESTIONS].update_many(
            {"id": {"$in": valid_ids}},
            {
                "$set": {
                    "status": "published",
                    "publishedAt": now,
                    "publishedInRevision": revision,
                    "warningsAcknowledged": True,
                    "attemptSpecificRiskConfirmed": True,
                    "approval": {"mentorId": by, "at": now, "comments": f"Bulk approve & publish ({scope})"},
                    "bulkAction": scope,
                }
            },
        )
        published_questions = res.modified_count

    published_scenarios = 0
    if scenario_ids:
        res = await db[CONTENT_SCENARIOS].update_many(
            {"scenarioId": {"$in": scenario_ids}},
            {
                "$set": {
                    "status": "published",
                    "publishedAt": now,
                    "publishedInRevision": revision,
                    "approval": {"mentorId": by, "at": now},
                    "bulkAction": scope,
                }
            },
        )
        published_scenarios = res.modified_count

    # 4) Chapters in scope → published.
    chapter_ids: list = []
    async for c in db[CONTENT_CHAPTERS].find(c_filter, {"chapterId": 1}):
        chapter_ids.append(c.get("chapterId"))
    if chapter_ids:
        await db[CONTENT_CHAPTERS].update_many(
            {"chapterId": {"$in": chapter_ids}},
            {
                "$set": {
                    "status": "published",
                    "releaseCandidate": {"revision": revision, "at": now, "by": by},
                    "bulkAction": scope,
                }
            },
        )

    # 5) Stage-11 release files (best effort — /bank.json serves straight from
    #    the DB, so a read-only or ephemeral filesystem must not fail publishing).
    files_written = 0
    for cid in chapter_ids:
        try:
            questions, scenarios = await _load_publishable(db, cid)
            if not questions:
                continue
            _write_release_files(revision, cid, questions, scenarios, now, by)
            files_written += 1
        except OSError:
            pass

    await db[CONTENT_RELEASES].insert_one(
        {
            "revision": revision,
            "manifest": {
                "schemaVersion": 1,
                "revision": revision,
                "publishedAt": now,
                "publishedBy": by,
                "catalogRevision": "may-2026",
                "scope": scope,
            },
            "publishedAt": now,
            "publishedBy": by,
            "chapters": chapter_ids,
            "gates": [],
            "bulk": True,
        }
    )
    await _audit(
        db,
        scope,
        "bulk",
        "bulk_approve_publish",
        by,
        {"questions": published_questions, "scenarios": published_scenarios, "chapters": len(chapter_ids), "skipped": len(skipped)},
    )
    await dump_store()
    message = f"Published {published_questions} questions across {len(chapter_ids)} chapters (revision {revision})."
    if skipped:
        message += f" {len(skipped)} questions were skipped for validation errors — they stay in review."
    return {
        "ok": True,
        "scope": scope,
        "revision": revision,
        "publishedQuestions": published_questions,
        "alreadyPublished": already_published,
        "publishedScenarios": published_scenarios,
        "chapters": len(chapter_ids),
        "skippedWithErrors": len(skipped),
        "skippedSample": skipped[:20],
        "filesWritten": files_written,
        "message": message,
    }


@router.post("/chapters/{chapter_id}/bulk-approve-publish")
async def bulk_approve_publish_chapter(chapter_id: str, claims: dict = Depends(require_mentor)):
    """One click: approve + publish EVERY eligible question in one chapter."""
    db = get_db()
    chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return await _bulk_approve_publish(
        q_filter={"chapterId": chapter_id},
        s_filter={"chapterId": chapter_id},
        c_filter={"chapterId": chapter_id},
        scope=f"chapter:{chapter_id}",
        by=claims.get("sub", "mentor"),
    )


@router.post("/subjects/{subject}/bulk-approve-publish")
async def bulk_approve_publish_subject(subject: str, claims: dict = Depends(require_mentor)):
    """One click: approve + publish every eligible question in one subject."""
    db = get_db()
    chapter_ids: list = []
    async for c in db[CONTENT_CHAPTERS].find({"subject": subject}, {"chapterId": 1}):
        chapter_ids.append(c["chapterId"])
    if not chapter_ids:
        raise HTTPException(status_code=404, detail=f"No chapters found for subject '{subject}'")
    return await _bulk_approve_publish(
        q_filter={"chapterId": {"$in": chapter_ids}},
        s_filter={"chapterId": {"$in": chapter_ids}},
        c_filter={"chapterId": {"$in": chapter_ids}},
        scope=f"subject:{subject}",
        by=claims.get("sub", "mentor"),
    )


@router.post("/bulk-approve-publish-all")
async def bulk_approve_publish_all(claims: dict = Depends(require_mentor)):
    """One click: approve + publish the whole bank (e.g. all ~4,700 MCQs)."""
    return await _bulk_approve_publish(
        q_filter={},
        s_filter={},
        c_filter={},
        scope="all",
        by=claims.get("sub", "mentor"),
    )


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
