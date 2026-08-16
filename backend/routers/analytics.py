"""Mentor analytics APIs over consented MCQ summaries (docs §8).

Everything here reads ONLY the analytics_* namespace (consent-gated device
summaries) plus follow-ups. Existing backend data (students, tracker,
attendance, notes, leaderboard, MCQ aggregates) continues to flow through the
existing Apps Script channel untouched; the frontend joins the two datasets.

No raw MCQ answers ever exist here — only the allowlisted summary fields.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_mentor
from db import (
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TRENDS,
    CONTENT_AUDIT,
    get_db,
)
from models import FollowupCreate, FollowupUpdate

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

BAND_ORDER = {"Not assessed": 0, "Weak": 1, "Medium": 2, "Strong": 3, "Mastered": 4}
INACTIVE_DAYS = 14


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _audit(db, actor, endpoint, detail):
    await db[CONTENT_AUDIT].insert_one(
        {"at": _now(), "by": actor, "action": f"analytics:{endpoint}", "entityId": detail.get("studentId"), "entityType": "analytics", "detail": detail}
    )


async def _consenting_students(db) -> set:
    ids = set()
    async for c in db[ANALYTICS_CONSENTS].find({"sharing": True}, {"studentId": 1}):
        ids.add(c["studentId"])
    return ids


def _band_trend(points: list) -> Optional[str]:
    """improving | declining | stable | None (insufficient data)."""
    ordered = sorted(points, key=lambda p: p.get("weekStart", ""))
    if len(ordered) < 2:
        return None
    values = [BAND_ORDER.get(p.get("masteryBand"), 0) for p in ordered[-4:]]
    if values[-1] > values[0]:
        return "improving"
    if values[-1] < values[0]:
        return "declining"
    return "stable"


@router.get("/overview")
async def overview(claims: dict = Depends(require_mentor)):
    db = get_db()
    consenting = await _consenting_students(db)
    summaries = []
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": {"$in": list(consenting)} if consenting else []}):
        summaries.append(s)

    band_counts = {"Not assessed": 0, "Weak": 0, "Medium": 0, "Strong": 0, "Mastered": 0}
    chapters_covered = set()
    inactive = 0
    threshold = date.today() - timedelta(days=INACTIVE_DAYS)
    for s in summaries:
        band = s.get("masteryBand")
        if band in band_counts:
            band_counts[band] += 1
        chapters_covered.add(s["chapterId"])
        if s.get("lastActivityDate"):
            try:
                if date.fromisoformat(str(s["lastActivityDate"])) < threshold:
                    inactive += 1
            except ValueError:
                pass

    open_followups = await db[ANALYTICS_FOLLOWUPS].count_documents({"status": {"$in": ["open", "in_progress"]}})
    await _audit(db, claims.get("sub"), "overview", {})
    return {
        "consentOnStudents": len(consenting),
        "studentsWithSummaries": len({s["studentId"] for s in summaries}),
        "chaptersCovered": len(chapters_covered),
        "bandDistribution": band_counts,
        "inactiveChapterCells": inactive,
        "openFollowups": open_followups,
    }


@router.get("/students")
async def students_list(claims: dict = Depends(require_mentor)):
    """All students with sharing state + summary counts (join with existing
    Apps Script student data happens in the frontend)."""
    db = get_db()
    consents: dict = {}
    async for c in db[ANALYTICS_CONSENTS].find({}):
        consents[c["studentId"]] = {
            "sharing": bool(c.get("sharing")),
            "updatedAt": c.get("updatedAt"),
        }
    students = []
    async for s in db[ANALYTICS_SUMMARIES].find({}):
        sid = s["studentId"]
        if sid not in consents:
            consents[sid] = {"sharing": None, "updatedAt": None}
    for sid, c in consents.items():
        n = await db[ANALYTICS_SUMMARIES].count_documents({"studentId": sid})
        students.append({"studentId": sid, "sharing": c["sharing"], "consentUpdatedAt": c["updatedAt"], "summaryCount": n})
    students.sort(key=lambda x: x["studentId"])
    await _audit(db, claims.get("sub"), "students", {})
    return {"items": students}


@router.get("/students/{student_id}")
async def student_analysis(student_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    consent = await db[ANALYTICS_CONSENTS].find_one({"studentId": student_id})
    sharing = bool(consent and consent.get("sharing"))

    summaries = []
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": student_id}):
        s.pop("_id", None)
        summaries.append(s)
    trends = []
    async for t in db[ANALYTICS_TRENDS].find({"studentId": student_id}).sort("weekStart", 1):
        t.pop("_id", None)
        trends.append(t)

    weak_chapters = [s for s in summaries if s.get("masteryBand") in ("Weak", "Not assessed")]
    weak_concepts = sorted({tag for s in summaries for tag in (s.get("weakConceptTags") or [])})
    subject_performance: dict = {}
    for s in summaries:
        subject = s.get("subject", "Unknown")
        subject_performance.setdefault(subject, []).append(BAND_ORDER.get(s.get("masteryBand"), 0))
    subject_performance = {k: round(sum(v) / len(v), 2) for k, v in subject_performance.items()}

    by_chapter = {}
    for t in trends:
        by_chapter.setdefault(t["chapterId"], []).append(t)
    improving = [c for c, pts in by_chapter.items() if _band_trend(pts) == "improving"]
    declining = [c for c, pts in by_chapter.items() if _band_trend(pts) == "declining"]

    last_activity = None
    for s in summaries:
        if s.get("lastActivityDate"):
            try:
                d = date.fromisoformat(str(s["lastActivityDate"]))
                if last_activity is None or d > last_activity:
                    last_activity = d
            except ValueError:
                pass

    recommendations = []
    if weak_chapters:
        recommendations.append(f"Focus practice on {len(weak_chapters)} weak chapter(s)")
    if declining:
        recommendations.append(f"Declining in {len(declining)} chapter(s) — consider mentor intervention")
    if last_activity and (date.today() - last_activity).days > INACTIVE_DAYS:
        recommendations.append(f"No activity for {(date.today() - last_activity).days} days")

    followups = []
    async for f in db[ANALYTICS_FOLLOWUPS].find({"studentId": student_id}).sort("createdAt", -1):
        f.pop("_id", None)
        followups.append(f)

    await _audit(db, claims.get("sub"), f"students/{student_id}", {"studentId": student_id})
    return {
        "studentId": student_id,
        "sharing": sharing,
        "summaries": summaries,
        "weakChapters": weak_chapters,
        "weakConcepts": weak_concepts,
        "subjectPerformance": subject_performance,
        "improvingChapters": improving,
        "decliningChapters": declining,
        "lastActivity": last_activity.isoformat() if last_activity else None,
        "recommendations": recommendations,
        "followups": followups,
    }


@router.get("/heatmap")
async def heatmap(
    group: Optional[str] = None,
    subject: Optional[str] = None,
    chapterId: Optional[str] = None,
    band: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    """Rows = students, columns = chapters, cells = mastery band.
    'No recent activity' is an overlay computed from lastActivityDate."""
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"students": [], "chapters": [], "cells": []}

    filt: dict = {"studentId": {"$in": list(consenting)}}
    if chapterId:
        filt["chapterId"] = chapterId
    if band:
        filt["masteryBand"] = band
    summaries = []
    async for s in db[ANALYTICS_SUMMARIES].find(filt):
        summaries.append(s)

    chapters = sorted({s["chapterId"] for s in summaries})
    threshold = date.today() - timedelta(days=INACTIVE_DAYS)
    cells = []
    for s in summaries:
        cell = {
            "studentId": s["studentId"],
            "chapterId": s["chapterId"],
            "masteryBand": s.get("masteryBand"),
            "attemptCount": s.get("attemptCount"),
            "accuracyRange": s.get("accuracyRange"),
        }
        try:
            d = date.fromisoformat(str(s.get("lastActivityDate")))
            cell["inactive"] = d < threshold
        except (ValueError, TypeError):
            cell["inactive"] = False
        cells.append(cell)
    await _audit(db, claims.get("sub"), "heatmap", {})
    return {"students": sorted({c["studentId"] for c in cells}), "chapters": chapters, "cells": cells}


@router.get("/weak-chapters")
async def weak_chapters(subject: Optional[str] = None, claims: dict = Depends(require_mentor)):
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"items": []}
    agg: dict = {}
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": {"$in": list(consenting)}}):
        if subject and s.get("subject") != subject:
            continue
        key = s["chapterId"]
        agg.setdefault(key, {"chapterId": key, "weakStudents": 0, "totalStudents": 0})
        agg[key]["totalStudents"] += 1
        if s.get("masteryBand") in ("Weak", "Not assessed"):
            agg[key]["weakStudents"] += 1
    items = sorted(agg.values(), key=lambda x: (-(x["weakStudents"] / max(x["totalStudents"], 1)), x["chapterId"]))
    await _audit(db, claims.get("sub"), "weak-chapters", {})
    return {"items": items}


@router.get("/groups")
async def groups(claims: dict = Depends(require_mentor)):
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"items": []}
    agg: dict = {}
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": {"$in": list(consenting)}}):
        g = s.get("group", "Unknown")
        agg.setdefault(g, {"group": g, "bandCounts": {"Weak": 0, "Medium": 0, "Strong": 0, "Mastered": 0, "Not assessed": 0}})
        band = s.get("masteryBand")
        if band in agg[g]["bandCounts"]:
            agg[g]["bandCounts"][band] += 1
    await _audit(db, claims.get("sub"), "groups", {})
    return {"items": list(agg.values())}


@router.get("/at-risk")
async def at_risk(claims: dict = Depends(require_mentor)):
    """Rule-based at-risk detection (docs §8.3) from summary + trend data."""
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"items": []}
    by_student: dict = {}
    async for t in db[ANALYTICS_TRENDS].find({"studentId": {"$in": list(consenting)}}):
        by_student.setdefault(t["studentId"], {}).setdefault(t["chapterId"], []).append(t)

    items = []
    for student_id, chapters in by_student.items():
        declining = [c for c, pts in chapters.items() if _band_trend(pts) == "declining"]
        if declining:
            items.append({"studentId": student_id, "decliningChapters": len(declining), "chapters": declining, "reason": "declining_trend"})
    items.sort(key=lambda x: -x["decliningChapters"])
    await _audit(db, claims.get("sub"), "at-risk", {})
    return {"items": items}


@router.get("/improvement")
async def improvement(claims: dict = Depends(require_mentor)):
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"items": []}
    by_student: dict = {}
    async for t in db[ANALYTICS_TRENDS].find({"studentId": {"$in": list(consenting)}}):
        by_student.setdefault(t["studentId"], {}).setdefault(t["chapterId"], []).append(t)

    items = []
    for student_id, chapters in by_student.items():
        improving = [c for c, pts in chapters.items() if _band_trend(pts) == "improving"]
        declining = [c for c, pts in chapters.items() if _band_trend(pts) == "declining"]
        if improving or declining:
            items.append({"studentId": student_id, "improvingChapters": improving, "decliningChapters": declining})
    await _audit(db, claims.get("sub"), "improvement", {})
    return {"items": items}


@router.get("/inactive")
async def inactive(days: int = Query(default=INACTIVE_DAYS, ge=1, le=365), claims: dict = Depends(require_mentor)):
    db = get_db()
    consenting = await _consenting_students(db)
    if not consenting:
        return {"items": []}
    threshold = date.today() - timedelta(days=days)
    items = []
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": {"$in": list(consenting)}}):
        try:
            d = date.fromisoformat(str(s.get("lastActivityDate")))
        except (ValueError, TypeError):
            continue
        if d < threshold:
            items.append({"studentId": s["studentId"], "chapterId": s["chapterId"], "lastActivityDate": d.isoformat()})
    await _audit(db, claims.get("sub"), "inactive", {})
    return {"items": items}


@router.get("/followups")
async def list_followups(
    studentId: Optional[str] = None,
    status: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    db = get_db()
    filt: dict = {}
    if studentId:
        filt["studentId"] = studentId
    if status:
        filt["status"] = status
    items = []
    async for f in db[ANALYTICS_FOLLOWUPS].find(filt).sort("createdAt", -1):
        f.pop("_id", None)
        items.append(f)
    return {"items": items}


@router.post("/followups")
async def create_followup(body: FollowupCreate, claims: dict = Depends(require_mentor)):
    import uuid

    db = get_db()
    doc = {
        "followupId": str(uuid.uuid4()),
        "studentId": body.studentId,
        "title": body.title,
        "priority": body.priority,
        "rule": body.rule,
        "status": "open",
        "createdAt": _now(),
        "createdBy": claims.get("sub"),
        "notes": [],
    }
    await db[ANALYTICS_FOLLOWUPS].insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/followups/{followup_id}")
async def update_followup(followup_id: str, body: FollowupUpdate, claims: dict = Depends(require_mentor)):
    db = get_db()
    updates: dict = {"updatedAt": _now()}
    if body.status:
        updates["status"] = body.status
    push: dict = {}
    if body.note:
        push["notes"] = {"note": body.note, "at": _now(), "by": claims.get("sub")}
    doc = await db[ANALYTICS_FOLLOWUPS].find_one({"followupId": followup_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if push:
        notes = list(doc.get("notes") or []) + [push["notes"]]
        updates["notes"] = notes
    await db[ANALYTICS_FOLLOWUPS].update_one({"followupId": followup_id}, {"$set": updates})
    return {"ok": True, "followupId": followup_id}
