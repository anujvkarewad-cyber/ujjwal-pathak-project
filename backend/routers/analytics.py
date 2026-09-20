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
    ANALYTICS_TEST_HISTORY,
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


async def _test_stats(db, student_ids=None):
    """Aggregate mentor-test submissions (MCQ auto-scores + paper self-marks)."""
    query = {"studentId": {"$in": list(student_ids)}} if student_ids is not None else {}
    entries = []
    async for t in db[ANALYTICS_TEST_HISTORY].find(query):
        t.pop("_id", None)
        entries.append(t)
    mcq = [e for e in entries if e.get("kind") == "mcq-test" and e.get("scorePct") is not None]
    return {
        "submissions": len(entries),
        "studentsTested": len({e.get("studentId") for e in entries}),
        "pendingSelfMarks": len([e for e in entries if e.get("kind") == "paper-test" and e.get("score") is None]),
        "avgMcqTestPct": round(sum(e["scorePct"] for e in mcq) / len(mcq)) if mcq else None,
        "entries": entries,
    }


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

    tests = await _test_stats(db, consenting or None)
    recent = sorted(tests.pop("entries"), key=lambda e: e.get("at") or "", reverse=True)[:8]

    await _audit(db, claims.get("sub"), "overview", {})
    return {
        "consentOnStudents": len(consenting),
        "studentsWithSummaries": len({s["studentId"] for s in summaries}),
        "chaptersCovered": len(chapters_covered),
        "bandDistribution": band_counts,
        "inactiveChapterCells": inactive,
        "openFollowups": open_followups,
        "tests": tests,
        "recentTestSubmissions": recent,
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
    # name/batch/test stats come from synced test-history records
    test_info: dict = {}
    async for t in db[ANALYTICS_TEST_HISTORY].find({}):
        sid = t.get("studentId")
        info = test_info.setdefault(sid, {"studentName": None, "batch": None, "testCount": 0, "lastTestAt": None})
        if t.get("studentName"):
            info["studentName"] = t["studentName"]
        if t.get("batch"):
            info["batch"] = t["batch"]
        info["testCount"] += 1
        if not info["lastTestAt"] or (t.get("at") or "") > info["lastTestAt"]:
            info["lastTestAt"] = t.get("at")

    for sid, c in consents.items():
        n = await db[ANALYTICS_SUMMARIES].count_documents({"studentId": sid})
        info = test_info.get(sid, {"studentName": None, "batch": None, "testCount": 0, "lastTestAt": None})
        students.append({
            "studentId": sid,
            "studentName": info["studentName"],
            "batch": info["batch"],
            "sharing": c["sharing"],
            "consentUpdatedAt": c["updatedAt"],
            "summaryCount": n,
            "testCount": info["testCount"],
            "lastTestAt": info["lastTestAt"],
        })
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

    test_history = []
    async for t in db[ANALYTICS_TEST_HISTORY].find({"studentId": student_id}).sort("at", -1):
        t.pop("_id", None)
        test_history.append(t)
    mcq_tests = [t for t in test_history if t.get("kind") == "mcq-test" and t.get("scorePct") is not None]
    test_stats = {
        "count": len(test_history),
        "pendingSelfMarks": len([t for t in test_history if t.get("kind") == "paper-test" and t.get("score") is None]),
        "avgMcqTestPct": round(sum(t["scorePct"] for t in mcq_tests) / len(mcq_tests)) if mcq_tests else None,
    }

    await _audit(db, claims.get("sub"), f"students/{student_id}", {"studentId": student_id})
    return {
        "studentId": student_id,
        "sharing": sharing,
        "testHistory": test_history,
        "testStats": test_stats,
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


def _range_cutoff(range_key: Optional[str]):
    """Week cutoff for report ranges: week = current week, month = last 5 weeks, all = no cutoff."""
    if range_key == "week":
        return date.today() - timedelta(days=date.today().weekday())
    if range_key == "month":
        return date.today() - timedelta(days=date.today().weekday() + 28)
    return None


async def _student_names(db) -> dict:
    """studentId → {studentName, batch} from consent records + test history."""
    names: dict = {}
    async for c in db[ANALYTICS_CONSENTS].find({}):
        if c.get("studentName") or c.get("batch"):
            names.setdefault(c["studentId"], {}).update(
                {k: v for k, v in (("studentName", c.get("studentName")), ("batch", c.get("batch")), ("joinedOn", c.get("joinedOn"))) if v}
            )
    async for t in db[ANALYTICS_TEST_HISTORY].find({}):
        sid = t.get("studentId")
        entry = names.setdefault(sid, {})
        if t.get("studentName") and not entry.get("studentName"):
            entry["studentName"] = t["studentName"]
        if t.get("batch") and not entry.get("batch"):
            entry["batch"] = t["batch"]
    return names


@router.get("/batch-report")
async def batch_report(
    range: Optional[str] = Query(default="all", pattern="^(week|month|all)$"),
    claims: dict = Depends(require_mentor),
):
    """Cohort report till date with a weekly series — who is progressing, who
    is falling behind, subject averages and weak chapters. Range filter:
    week = current week, month = last 5 weeks, all = everything synced."""
    db = get_db()
    consenting = await _consenting_students(db)
    cutoff = _range_cutoff(range)
    names = await _student_names(db)

    # weekly series from trends
    series: dict = {}
    async for t in db[ANALYTICS_TRENDS].find({"studentId": {"$in": list(consenting)} if consenting else []}):
        week = str(t.get("weekStart") or "")[:10]
        if not week:
            continue
        if cutoff and date.fromisoformat(week) < cutoff:
            continue
        point = series.setdefault(week, {"bandScores": [], "students": set()})
        point["bandScores"].append(BAND_ORDER.get(t.get("masteryBand"), 0))
        point["students"].add(t.get("studentId"))

    # tests per week
    tests_total = 0
    test_pcts = []
    pending_marks = 0
    async for e in db[ANALYTICS_TEST_HISTORY].find({}):
        day = str(e.get("at") or "")[:10]
        if cutoff and day and date.fromisoformat(day) < cutoff:
            continue
        week = (date.fromisoformat(day) - timedelta(days=date.fromisoformat(day).weekday())).isoformat() if day else None
        tests_total += 1
        if e.get("kind") == "paper-test" and e.get("score") is None:
            pending_marks += 1
        if e.get("scorePct") is not None:
            test_pcts.append(e["scorePct"])
        if week and week in series:
            series[week].setdefault("tests", 0)
            series[week]["tests"] += 1

    weeks = []
    for week in sorted(series):
        point = series[week]
        weeks.append({
            "weekStart": week,
            "avgBandScore": round(sum(point["bandScores"]) / len(point["bandScores"]), 2),
            "activeStudents": len(point["students"]),
            "testsGiven": point.get("tests", 0),
        })

    # current mastery snapshot (summaries)
    summaries = []
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": {"$in": list(consenting)} if consenting else []}):
        summaries.append(s)
    band_counts = {"Not assessed": 0, "Weak": 0, "Medium": 0, "Strong": 0, "Mastered": 0}
    subject_scores: dict = {}
    weak_agg: dict = {}
    for s in summaries:
        band = s.get("masteryBand")
        if band in band_counts:
            band_counts[band] += 1
        subject_scores.setdefault(s.get("subject") or "Unknown", []).append(BAND_ORDER.get(band, 0))
        if band in ("Weak", "Not assessed"):
            key = s["chapterId"]
            agg = weak_agg.setdefault(key, {"chapterId": key, "subject": s.get("subject"), "weakStudents": 0, "totalStudents": 0})
            agg["weakStudents"] += 1
    for s in summaries:
        key = s["chapterId"]
        if key in weak_agg:
            weak_agg[key]["totalStudents"] += 1
    subject_averages = [
        {"subject": k, "avgScore": round(sum(v) / len(v), 2), "chapters": len(v)}
        for k, v in sorted(subject_scores.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
    ]
    weak_chapters = sorted(weak_agg.values(), key=lambda x: -x["weakStudents"])[:8]

    # progressing vs falling behind (trend over the last 4 snapshots)
    by_student_chapter: dict = {}
    async for t in db[ANALYTICS_TRENDS].find({"studentId": {"$in": list(consenting)} if consenting else []}):
        by_student_chapter.setdefault(t.get("studentId"), {}).setdefault(t.get("chapterId"), []).append(t)
    progressing, falling_behind = [], []
    for sid, chapters in by_student_chapter.items():
        improving = [c for c, pts in chapters.items() if _band_trend(pts) == "improving"]
        declining = [c for c, pts in chapters.items() if _band_trend(pts) == "declining"]
        info = names.get(sid, {})
        label = info.get("studentName") or sid
        if improving and not declining:
            progressing.append({"studentId": sid, "name": label, "batch": info.get("batch"), "chapters": improving})
        elif declining:
            falling_behind.append({"studentId": sid, "name": label, "batch": info.get("batch"), "chapters": declining, "reason": "declining_trend"})
    # inactive students join the falling-behind list
    threshold = date.today() - timedelta(days=INACTIVE_DAYS)
    last_seen: dict = {}
    for s in summaries:
        try:
            d = date.fromisoformat(str(s.get("lastActivityDate")))
            if d > last_seen.get(s["studentId"], date.min):
                last_seen[s["studentId"]] = d
        except (ValueError, TypeError):
            pass
    already = {x["studentId"] for x in falling_behind}
    for sid, d in last_seen.items():
        if d < threshold and sid not in already:
            info = names.get(sid, {})
            falling_behind.append({
                "studentId": sid, "name": info.get("studentName") or sid, "batch": info.get("batch"),
                "chapters": [], "reason": f"inactive_{(date.today() - d).days}d",
            })

    await _audit(db, claims.get("sub"), "batch-report", {"range": range})
    return {
        "range": range or "all",
        "kpis": {
            "students": len(consenting),
            "chaptersCovered": len({s["chapterId"] for s in summaries}),
            "avgMasteryScore": round(sum(BAND_ORDER.get(s.get("masteryBand"), 0) for s in summaries) / len(summaries), 2) if summaries else 0,
            "testsGiven": tests_total,
            "avgTestPct": round(sum(test_pcts) / len(test_pcts)) if test_pcts else None,
            "pendingSelfMarks": pending_marks,
        },
        "weeks": weeks,
        "bandDistribution": band_counts,
        "subjectAverages": subject_averages,
        "weakChapters": weak_chapters,
        "progressing": progressing,
        "fallingBehind": falling_behind,
    }


@router.get("/student-report/{student_id}")
async def student_report(student_id: str, claims: dict = Depends(require_mentor)):
    """Individual report: everything from joining till date — journey, mastery,
    tests, weaknesses and recommendations."""
    db = get_db()
    consent = await db[ANALYTICS_CONSENTS].find_one({"studentId": student_id}) or {}
    sharing = bool(consent.get("sharing"))
    names = await _student_names(db)
    info = names.get(student_id, {})

    summaries = []
    async for s in db[ANALYTICS_SUMMARIES].find({"studentId": student_id}):
        s.pop("_id", None)
        summaries.append(s)
    trends = []
    async for t in db[ANALYTICS_TRENDS].find({"studentId": student_id}).sort("weekStart", 1):
        t.pop("_id", None)
        trends.append(t)

    # weekly journey series
    journey: dict = {}
    for t in trends:
        week = str(t.get("weekStart") or "")[:10]
        if not week:
            continue
        point = journey.setdefault(week, {"bandScores": [], "attempts": 0})
        point["bandScores"].append(BAND_ORDER.get(t.get("masteryBand"), 0))
        point["attempts"] += t.get("attemptCount") or 0
    weeks = [
        {
            "weekStart": week,
            "avgBandScore": round(sum(p["bandScores"]) / len(p["bandScores"]), 2),
            "masteredCount": sum(1 for b in p["bandScores"] if b >= 4),
            "attempts": p["attempts"],
        }
        for week, p in sorted(journey.items())
    ]

    tests = []
    async for t in db[ANALYTICS_TEST_HISTORY].find({"studentId": student_id}).sort("at", -1):
        t.pop("_id", None)
        tests.append(t)
    mcq_tests = [t for t in tests if t.get("kind") == "mcq-test" and t.get("scorePct") is not None]

    earliest = None
    for s in summaries:
        try:
            d = date.fromisoformat(str(s.get("lastActivityDate")))
            if earliest is None or d < earliest:
                earliest = d
        except (ValueError, TypeError):
            pass
    for t in trends:
        try:
            d = date.fromisoformat(str(t.get("weekStart"))[:10])
            if earliest is None or d < earliest:
                earliest = d
        except (ValueError, TypeError):
            pass
    joined_on = consent.get("joinedOn") or (earliest.isoformat() if earliest else None)

    weak_chapters = [s for s in summaries if s.get("masteryBand") in ("Weak", "Not assessed")]
    weak_concepts = sorted({tag for s in summaries for tag in (s.get("weakConceptTags") or [])})
    by_chapter = {}
    for t in trends:
        by_chapter.setdefault(t.get("chapterId"), []).append(t)
    improving = [c for c, pts in by_chapter.items() if _band_trend(pts) == "improving"]
    declining = [c for c, pts in by_chapter.items() if _band_trend(pts) == "declining"]

    recommendations = []
    if weak_chapters:
        recommendations.append(f"Focus practice on {len(weak_chapters)} weak chapter(s): " + ", ".join(w["chapterId"] for w in weak_chapters[:3]))
    if declining:
        recommendations.append("Declining in " + ", ".join(declining) + " — schedule a mentor call")
    if improving:
        recommendations.append("Strong improvement in " + ", ".join(improving) + " — keep the momentum")
    if any(t.get("kind") == "paper-test" and t.get("score") is None for t in tests):
        recommendations.append("Paper self-evaluation marks are still due")

    followups = []
    async for f in db[ANALYTICS_FOLLOWUPS].find({"studentId": student_id}).sort("createdAt", -1):
        f.pop("_id", None)
        followups.append(f)

    await _audit(db, claims.get("sub"), f"student-report/{student_id}", {"studentId": student_id})
    return {
        "studentId": student_id,
        "profile": {
            "studentName": info.get("studentName") or consent.get("studentName"),
            "batch": info.get("batch") or consent.get("batch"),
            "group": next((s.get("group") for s in summaries if s.get("group")), None),
            "joinedOn": joined_on,
            "sharing": sharing,
        },
        "totals": {
            "chaptersTracked": len(summaries),
            "mastered": sum(1 for s in summaries if s.get("masteryBand") == "Mastered"),
            "weak": len(weak_chapters),
            "totalAttempts": sum(s.get("attemptCount") or 0 for s in summaries),
            "testsGiven": len(tests),
            "avgMcqTestPct": round(sum(t["scorePct"] for t in mcq_tests) / len(mcq_tests)) if mcq_tests else None,
            "pendingSelfMarks": sum(1 for t in tests if t.get("kind") == "paper-test" and t.get("score") is None),
        },
        "weeks": weeks,
        "chapters": sorted(summaries, key=lambda s: -BAND_ORDER.get(s.get("masteryBand"), 0)),
        "weakConcepts": weak_concepts,
        "improvingChapters": improving,
        "decliningChapters": declining,
        "tests": tests,
        "recommendations": recommendations,
        "followups": followups,
    }
