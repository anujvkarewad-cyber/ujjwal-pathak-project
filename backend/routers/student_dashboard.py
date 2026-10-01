"""Student dashboard reads/writes on Mongo, with sheet import merge."""
import asyncio
import csv
import io
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from auth import require_mentor
from config import settings
from db import DASHBOARD_SHARED, DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db
from routers.student_auth import normalize_student_id, _attempt_ym

router = APIRouter(prefix="/api/student-dashboard", tags=["student-dashboard"])

# Durable tombstones are kept outside the sheet-imported shared document.
# An old sheet sync can never make a mentor-deleted announcement visible again.
ANNOUNCEMENT_DELETIONS = "announcement_deletions"


async def _deleted_announcement_ids(db) -> set:
    return {str(row["_id"]) async for row in db[ANNOUNCEMENT_DELETIONS].find({}, {"_id": 1})}


async def _visible_announcements(db, rows) -> list:
    deleted = await _deleted_announcement_ids(db)
    return [row for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and str(row.get("id") or "").strip() not in deleted]


@router.get("/announcements/deleted")
async def deleted_announcements(_mentor=Depends(require_mentor)):
    ids = sorted(await _deleted_announcement_ids(get_db()))
    return JSONResponse({"deletedIds": ids}, headers={"Cache-Control": "no-store"})


@router.delete("/announcements/{announcement_id}")
async def delete_announcement(announcement_id: str, mentor=Depends(require_mentor)):
    aid = str(announcement_id or "").strip()
    if not aid or len(aid) > 120:
        raise HTTPException(status_code=400, detail="A valid announcement ID is required.")
    # Idempotent: record deletion only. Do not delete sheet rows or send messages.
    await get_db()[ANNOUNCEMENT_DELETIONS].update_one(
        {"_id": aid},
        {"$setOnInsert": {"deletedAt": _now(), "deletedBy": mentor.get("sub") or "mentor"}},
        upsert=True,
    )
    return {"ok": True, "id": aid}


MATERIAL_DELETIONS = "material_deletions"
CONTENT_RESET_ARCHIVE = "content_reset_archive"


def _material_keys(row) -> set:
    if not isinstance(row, dict):
        return set()
    keys = set()
    for field, prefix in (("id", "id:"), ("fileId", "file:"), ("fileUrl", "url:")):
        value = str(row.get(field) or "").strip()
        if value:
            keys.add(prefix + value)
    return keys


async def _hidden_material_keys(db) -> set:
    return {str(row["_id"]) async for row in db[MATERIAL_DELETIONS].find({}, {"_id": 1})}


async def _visible_materials(db, rows) -> list:
    hidden = await _hidden_material_keys(db)
    return [row for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and not (_material_keys(row) & hidden)]


@router.get("/materials/hidden")
async def hidden_materials(_mentor=Depends(require_mentor)):
    keys = sorted(await _hidden_material_keys(get_db()))
    return JSONResponse({"hiddenKeys": keys}, headers={"Cache-Control": "no-store"})


class ClearOldContentBody(BaseModel):
    confirm: str = ""
    dryRun: bool = True
    # Snapshot of the sheet-backed mentor view, if any rows have not synced yet.
    sheetAnnouncements: list[dict] = Field(default_factory=list, max_length=5000)
    sheetMaterials: list[dict] = Field(default_factory=list, max_length=5000)


@router.post("/content/clear-old")
async def clear_old_app_content(body: ClearOldContentBody, mentor=Depends(require_mentor)):
    if body.confirm != "CLEAR_OLD_APP_CONTENT_ONLY":
        raise HTTPException(status_code=400, detail="Explicit content-only confirmation is required.")
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    announcements = list(shared.get("announcements") or []) + body.sheetAnnouncements
    materials = list(shared.get("notes") or []) + body.sheetMaterials
    personal = []
    async for doc in db[DASHBOARD_STUDENTS].find({}, {"studentId": 1, "notes": 1}):
        notes = doc.get("notes") if isinstance(doc.get("notes"), list) else []
        if notes:
            personal.append({"studentId": doc.get("studentId"), "notes": notes})
            materials.extend(notes)
    ann_ids = {str(x.get("id") or "").strip() for x in announcements if isinstance(x, dict)} - {""}
    keys = set().union(*(_material_keys(x) for x in materials)) if materials else set()
    # A row without stable identity could reappear after sync: stop, do not guess.
    if any(not _material_keys(x) for x in materials) or any(not isinstance(x, dict) or not str(x.get("id") or "").strip() for x in announcements):
        raise HTTPException(status_code=409, detail="Some content has no stable ID. Reset stopped; no content was changed.")
    counts = {"announcementIds": len(ann_ids), "sharedMaterialRows": len(shared.get("notes") or []),
              "sheetMaterialRows": len(body.sheetMaterials), "personalMaterialRows": sum(len(x["notes"]) for x in personal),
              "materialIdentityKeys": len(keys)}
    if body.dryRun:
        return {"ok": True, "dryRun": True, "counts": counts}
    reset_id = "content-reset-" + uuid.uuid4().hex
    now = _now()
    # Archive content only. No logs, scores, accounts, targets or Drive files touched.
    await db[CONTENT_RESET_ARCHIVE].insert_one({"_id": reset_id, "createdAt": now,
        "createdBy": mentor.get("sub") or "mentor", "announcements": announcements,
        "sharedMaterials": shared.get("notes") or [], "sheetMaterials": body.sheetMaterials, "counts": counts})
    for index, doc in enumerate(personal):
        await db[CONTENT_RESET_ARCHIVE].insert_one({"_id": reset_id + ":" + str(index), "resetId": reset_id, **doc})
    for aid in sorted(ann_ids):
        await db[ANNOUNCEMENT_DELETIONS].update_one({"_id": aid},
            {"$setOnInsert": {"deletedAt": now, "deletedBy": mentor.get("sub") or "mentor", "resetId": reset_id}}, upsert=True)
    for key in sorted(keys):
        await db[MATERIAL_DELETIONS].update_one({"_id": key},
            {"$setOnInsert": {"hiddenAt": now, "resetId": reset_id}}, upsert=True)
    return {"ok": True, "dryRun": False, "resetId": reset_id, "counts": counts,
            "localNotificationsCleared": False, "driveFilesDeleted": False,
            "protectedDataUnchanged": True}


PERSONAL_ACTIONS = {
    "getStats": "stats",
    "getStudyLog": "studyLog",
    "getWeeklyReports": "reports",
    "getStudentMentorNotes": "mentorNotes",
    "getStudentFeedback": "feedback",
}
SHARED_ACTIONS = {
    "getAnnouncements": "announcements",
    "getLeaderboard": "leaderboard",
}

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(IST).date().isoformat()


TRACKER_SHEET_ID = os.environ.get(
    "TRACKER_SHEET_ID",
    "1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc",
).strip()
TRACKER_FORM_SHEET = os.environ.get("TRACKER_FORM_SHEET", "Form responses 1").strip()


def _parse_tracker_day(value: Any) -> Optional[date]:
    """Read an ISO or Google-Sheets India date without timezone drift."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt, length in (
        ("%Y-%m-%d", 10),
        ("%d/%m/%Y", 10),
        ("%d/%m/%Y %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%a %b %d %Y", 15),
    ):
        try:
            return datetime.strptime(text[:length], fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _tracker_submission_day(study_value: Any, timestamp_value: Any) -> Optional[date]:
    study_day = _parse_tracker_day(study_value)
    timestamp_day = _parse_tracker_day(timestamp_value)
    # A broken browser/date control can serialize an epoch date such as 1970.
    # Prefer the form timestamp when the supplied study date is implausibly far
    # away, rather than losing a genuine submission or assigning it to 1970.
    if study_day and timestamp_day and abs((timestamp_day - study_day).days) > 366:
        return timestamp_day
    return study_day or timestamp_day


def _fetch_tracker_submissions_sync() -> list[dict]:
    """Read the complete tracker form history; this endpoint never writes to Sheets."""
    if not TRACKER_SHEET_ID:
        raise RuntimeError("Tracker sheet is not configured.")
    url = f"https://docs.google.com/spreadsheets/d/{TRACKER_SHEET_ID}/gviz/tq"
    response = requests.get(
        url,
        params={"tqx": "out:csv", "sheet": TRACKER_FORM_SHEET, "_": str(int(datetime.now().timestamp()))},
        headers={"User-Agent": "UPM-mentor-tracker-report/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    by_key = {_header_key(name): name for name in fields}
    id_col = by_key.get("student id") or by_key.get("studentid")
    timestamp_col = by_key.get("timestamp")
    study_date_col = by_key.get("study date")
    if not id_col or not timestamp_col:
        raise RuntimeError("Tracker sheet columns could not be identified.")

    submissions = []
    for row in reader:
        sid = normalize_student_id(row.get(id_col) or "")
        day = _tracker_submission_day(
            row.get(study_date_col) if study_date_col else "",
            row.get(timestamp_col) or "",
        )
        if sid and day:
            submissions.append({"studentId": sid, "date": day})
    return submissions


def _build_missed_tracker_report(
    accounts: list[dict],
    submissions: list[dict],
    from_day: date,
    to_day: date,
) -> dict:
    submitted_by_student: dict[str, set[date]] = {}
    for row in submissions:
        sid = normalize_student_id(row.get("studentId") or "")
        day = row.get("date")
        if sid and isinstance(day, date) and from_day <= day <= to_day:
            submitted_by_student.setdefault(sid, set()).add(day)

    items = []
    roster_count = 0
    for account in accounts:
        if account.get("master") or _attempt_ym(account.get("attempt") or "", account.get("batch") or "") != (2027, 1):
            continue
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        roster_count += 1
        joined = _parse_tracker_day(account.get("joinedOn") or "")
        expected_from = max(from_day, joined) if joined else from_day
        expected_dates = []
        if expected_from <= to_day:
            expected_dates = [
                expected_from + timedelta(days=offset)
                for offset in range((to_day - expected_from).days + 1)
            ]
        submitted = submitted_by_student.get(sid, set())
        submitted_dates = [day for day in expected_dates if day in submitted]
        missed_dates = [day for day in expected_dates if day not in submitted]
        items.append({
            "studentId": sid,
            "studentName": str(account.get("studentName") or sid).strip() or sid,
            "group": str(account.get("group") or "Unassigned").strip() or "Unassigned",
            "batch": str(account.get("batch") or "Unassigned").strip() or "Unassigned",
            "joinedOn": joined.isoformat() if joined else None,
            "expectedFrom": expected_from.isoformat(),
            "expectedDays": len(expected_dates),
            "submittedDays": len(submitted_dates),
            "missedDays": len(missed_dates),
            "submittedDates": [day.isoformat() for day in submitted_dates],
            "missedDates": [day.isoformat() for day in missed_dates],
        })

    items.sort(key=lambda row: (-row["missedDays"], row["studentName"].lower(), row["studentId"]))
    students_with_misses = sum(1 for row in items if row["missedDays"] > 0)
    return {
        "attempt": "Jan 2027",
        "from": from_day.isoformat(),
        "to": to_day.isoformat(),
        "dayRule": "Every calendar day",
        "totalCalendarDays": (to_day - from_day).days + 1,
        "rosterCount": roster_count,
        "studentsWithMissedDays": students_with_misses,
        "studentsWithNoMissedDays": max(0, roster_count - students_with_misses),
        "items": items,
    }


@router.get("/tracker-missed-report")
async def tracker_missed_report(
    from_value: str = Query(alias="from"),
    to_value: str = Query(alias="to"),
    _mentor=Depends(require_mentor),
):
    from_day = _parse_tracker_day(from_value)
    to_day = _parse_tracker_day(to_value)
    if not from_day or not to_day:
        raise HTTPException(status_code=400, detail="From and To must be valid YYYY-MM-DD dates.")
    if from_day > to_day:
        raise HTTPException(status_code=400, detail="From date cannot be after To date.")
    if (to_day - from_day).days > 365:
        raise HTTPException(status_code=400, detail="Choose a date range of 366 days or fewer.")
    today = datetime.now(IST).date()
    if to_day > today:
        raise HTTPException(status_code=400, detail="To date cannot be in the future.")

    db = get_db()
    accounts = await db[STUDENT_ACCOUNTS].find(
        {},
        {
            "studentId": 1,
            "studentName": 1,
            "group": 1,
            "batch": 1,
            "attempt": 1,
            "joinedOn": 1,
            "master": 1,
        },
    ).to_list(length=500)
    try:
        submissions = await asyncio.to_thread(_fetch_tracker_submissions_sync)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Tracker form data could not be loaded. No report was calculated.") from exc

    report = _build_missed_tracker_report(accounts, submissions, from_day, to_day)
    report["source"] = "Form responses 1"
    report["sourceSubmissionRows"] = len(submissions)
    report["generatedAt"] = _now()
    return JSONResponse(report, headers={"Cache-Control": "no-store"})


def _import_allowed(request: Request) -> bool:
    if settings.dev_auth_bypass:
        return True
    header = (request.headers.get("X-UMP-Import") or "").strip()
    expected = (getattr(settings, "student_import_key", "") or "").strip()
    if expected and header and header == expected:
        return True
    return False


class DashboardStudentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    studentId: str = Field(min_length=1, max_length=64)
    studentName: str = ""
    stats: Any = None
    studyLog: Any = None
    reports: Any = None
    mentorNotes: Any = None
    feedback: Any = None
    notes: Any = None


class DashboardImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    announcements: Optional[list] = None
    leaderboard: Optional[list] = None
    notes: Optional[list] = None
    students: list[DashboardStudentItem] = Field(default_factory=list, max_length=500)


class DashboardGetBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str = ""
    studentId: Optional[str] = None
    payload: Optional[dict] = None


class DashboardWriteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str = ""
    payload: Optional[dict] = None
    result: Optional[Any] = None


def _parse_day(value):
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _merge_logs(old, new) -> list:
    """One row per date+topic+hours. Extra proof-only copies from dual-write are collapsed."""
    best = {}
    order = []
    for row in list(new or []) + list(old or []):
        if not isinstance(row, dict):
            continue
        try:
            hours = round(float(row.get("hours") or 0), 2)
        except (TypeError, ValueError):
            hours = 0.0
        date = str(row.get("date") or "")[:10]
        topic = str(row.get("topic") or row.get("subjects") or "")
        proof = str(row.get("proof") or "")
        if not date and not hours:
            continue
        key = (date, topic, hours)
        current = best.get(key)
        if current is None:
            best[key] = {"date": date, "topic": topic, "hours": hours, "proof": proof}
            order.append(key)
        elif len(proof) > len(str(current.get("proof") or "")):
            current["proof"] = proof
    out = [best[key] for key in order]
    out.sort(key=lambda r: r.get("date") or "", reverse=True)
    return out[:400]


def _recompute_stats(logs: list, prev: Optional[dict] = None) -> dict:
    prev = dict(prev or {})
    today = datetime.now(IST).date()
    month_key = today.strftime("%Y-%m")
    week_start = today - timedelta(days=6)
    last7 = [0.0] * 7
    total = 0.0
    today_h = 0.0
    month_h = 0.0
    week_h = 0.0
    last_sub = ""
    entries = 0
    for row in logs or []:
        if not isinstance(row, dict):
            continue
        day = _parse_day(row.get("date"))
        try:
            hours = float(row.get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        if not day or hours <= 0:
            continue
        entries += 1
        total += hours
        if day == today:
            today_h += hours
        if day.strftime("%Y-%m") == month_key:
            month_h += hours
        if week_start <= day <= today:
            week_h += hours
            last7[(day.weekday() + 1) % 7] += hours
        iso = day.isoformat()
        if iso > last_sub:
            last_sub = iso
    dated = set()
    for row in logs or []:
        if not isinstance(row, dict):
            continue
        day = _parse_day(row.get("date"))
        try:
            row_hours = float(row.get("hours") or 0)
        except (TypeError, ValueError):
            row_hours = 0.0
        if day and row_hours > 0:
            dated.add(day)
    cursor = today if today in dated else today - timedelta(days=1)
    streak = 0
    while cursor in dated:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return {
        "totalHours": round(total, 2),
        "monthlyHours": round(month_h, 2),
        "weeklyHours": round(week_h, 2),
        "todayHours": round(today_h, 2),
        "averageHours": round(total / entries, 2) if entries else 0,
        "totalEntries": entries,
        "lastSubmission": last_sub,
        "last7": [round(x, 1) for x in last7],
        "streak": streak,
        "rank": int(prev.get("rank") or 0),
        "weeklyRank": int(prev.get("weeklyRank") or 0),
        "monthlyRank": int(prev.get("monthlyRank") or 0),
    }


def _weekly_reports_from_logs(logs: list, stats: Optional[dict] = None) -> list:
    stats = dict(stats or {})
    buckets: dict = {}
    for row in logs or []:
        if not isinstance(row, dict):
            continue
        day = _parse_day(row.get("date"))
        try:
            hours = float(row.get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        if not day or hours <= 0:
            continue
        start = day - timedelta(days=day.weekday())
        key = start.isoformat()
        bucket = buckets.setdefault(key, {"hours": 0.0, "days": set()})
        bucket["hours"] += hours
        bucket["days"].add(day)
    today = datetime.now(IST).date()
    this_week = (today - timedelta(days=today.weekday())).isoformat()
    out = []
    for key in sorted(buckets.keys(), reverse=True):
        hours = round(buckets[key]["hours"], 1)
        if hours <= 0:
            continue
        if hours >= 35:
            level = "Excellent"
        elif hours >= 20:
            level = "Strong"
        else:
            level = "Progressing"
        start = datetime.strptime(key, "%Y-%m-%d").date()
        item = {
            "weekOf": start.strftime("%d %b %Y"),
            "weeklyHours": hours,
            "streak": int(stats.get("streak") or 0) if key == this_week else len(buckets[key]["days"]),
            "rank": int(stats.get("weeklyRank") or stats.get("rank") or 0) if key == this_week else 0,
            "level": level,
        }
        out.append(item)
    return out[:12]


async def _rebuild_leaderboard(db) -> None:
    names = {}
    async for account in db[STUDENT_ACCOUNTS].find({}):
        sid = account.get("studentId")
        if sid:
            names[sid] = (account.get("studentName") or "").strip() or sid
    rows = []
    async for doc in db[DASHBOARD_STUDENTS].find({}):
        sid = doc.get("studentId")
        if not sid:
            continue
        stats = doc.get("stats") or {}
        rows.append({
            "studentId": sid,
            "studentName": names.get(sid) or (doc.get("studentName") or "").strip() or sid,
            "weeklyHours": round(float(stats.get("weeklyHours") or 0), 1),
            "totalHours": round(float(stats.get("totalHours") or 0), 2),
            "streak": int(stats.get("streak") or 0),
            "status": "Active" if float(stats.get("weeklyHours") or 0) > 0 else "Inactive",
        })
    rows.sort(key=lambda r: (-r["weeklyHours"], -r["totalHours"], r["studentId"]))
    for index, row in enumerate(rows, 1):
        row["rank"] = index
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": row["studentId"]},
            {"$set": {"stats.rank": index, "stats.weeklyRank": index}},
        )
    await db[DASHBOARD_SHARED].update_one(
        {"_id": "shared"},
        {"$set": {"leaderboard": rows, "updatedAt": _now()}},
        upsert=True,
    )


def _notes_for_student(notes: list, account: Optional[dict]) -> list:
    if not isinstance(notes, list):
        return []
    if not account:
        return notes
    batch = str(account.get("batch") or "")
    group = str(account.get("group") or "")
    out = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        audience = str(note.get("audience") or "All Batches")
        note_group = str(note.get("group") or "Both Groups")
        batch_ok = audience in ("", "All Batches") or audience == batch
        group_ok = note_group in ("", "Both Groups") or not group or group == "Both Groups" or note_group == group
        if batch_ok and group_ok:
            out.append(note)
    return out


async def _leaderboard_for_student(db, rows, student_id: str) -> list:
    """Hide closed/unknown cohorts at read time without deleting stored history.

    Use current student accounts, never a stale imported row's attempt.
    Older app clients omit studentId: they receive only the two open cohorts.
    Clients sending studentId receive only their own open attempt.
    """
    allowed = {(2027, 1): "Jan 2027", (2027, 5): "May 2027"}
    attempts = {}
    async for account in db[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "attempt": 1}):
        sid = normalize_student_id(account.get("studentId") or "")
        if sid:
            attempts[sid] = _attempt_ym(account.get("attempt") or "", "")

    wanted = normalize_student_id(student_id or "")
    wanted_attempt = attempts.get(wanted) if wanted else None
    if wanted and wanted_attempt not in allowed:
        return []

    result = []
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        sid = normalize_student_id(row.get("studentId") or "")
        attempt = attempts.get(sid)
        if not sid or sid in seen or attempt not in allowed:
            continue
        if wanted and attempt != wanted_attempt:
            continue
        seen.add(sid)
        item = dict(row)
        item["studentId"] = sid
        item["attempt"] = allowed[attempt]
        item["rank"] = len(result) + 1
        result.append(item)
    return result


@router.get("/status")
async def dashboard_status():
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
    students = await db[DASHBOARD_STUDENTS].count_documents({})
    return {
        "ok": True,
        "shared": bool(shared),
        "students": students,
        "announcements": len((shared or {}).get("announcements") or []),
        "notes": len((shared or {}).get("notes") or []),
        "leaderboard": len((shared or {}).get("leaderboard") or []),
        "updatedAt": (shared or {}).get("updatedAt"),
    }


@router.post("/import")
async def import_dashboard(body: DashboardImportBody, request: Request):
    if not _import_allowed(request):
        try:
            await require_mentor(request)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Import not allowed")

    db = get_db()
    shared_set = {"updatedAt": _now()}
    if body.announcements is not None:
        shared_set["announcements"] = await _visible_announcements(db, body.announcements)
    if body.notes is not None:
        shared_set["notes"] = await _visible_materials(db, body.notes)
    if len(shared_set) > 1:
        await db[DASHBOARD_SHARED].update_one(
            {"_id": "shared"},
            {"$set": shared_set},
            upsert=True,
        )

    upserted = 0
    for item in body.students:
        sid = normalize_student_id(item.studentId)
        if not sid:
            continue
        existing = await db[DASHBOARD_STUDENTS].find_one({"studentId": sid}) or {}
        incoming_logs = item.studyLog if isinstance(item.studyLog, list) else []
        existing_logs = existing.get("studyLog") if isinstance(existing.get("studyLog"), list) else []
        merged_logs = _merge_logs(existing_logs, incoming_logs)
        prev_stats = dict(existing.get("stats") or {})
        if item.stats and isinstance(item.stats, dict):
            for key, value in item.stats.items():
                if value not in (None, "", []):
                    prev_stats[key] = value
        stats = _recompute_stats(merged_logs, prev_stats)
        doc = {
            "studentId": sid,
            "updatedAt": _now(),
            "studyLog": merged_logs,
            "stats": stats,
            "reports": _weekly_reports_from_logs(merged_logs, stats),
        }
        name = (item.studentName or "").strip()
        if name:
            doc["studentName"] = name
        if item.mentorNotes is not None:
            doc["mentorNotes"] = item.mentorNotes
        if item.feedback is not None:
            doc["feedback"] = item.feedback
        if item.notes is not None:
            doc["notes"] = item.notes
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": doc},
            upsert=True,
        )
        upserted += 1

    await _rebuild_leaderboard(db)
    return {"ok": True, "students": upserted}


@router.post("/get")
async def get_dashboard_section(body: DashboardGetBody):
    action = str(body.action or "").strip()
    payload = body.payload if isinstance(body.payload, dict) else {}
    student_id = normalize_student_id(body.studentId or payload.get("studentId") or "")
    db = get_db()

    if action in SHARED_ACTIONS:
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
        if not shared or SHARED_ACTIONS[action] not in shared:
            return {"found": False}
        rows = shared.get(SHARED_ACTIONS[action]) or []
        if action == "getLeaderboard":
            rows = await _leaderboard_for_student(db, rows, student_id)
        elif action == "getAnnouncements":
            rows = await _visible_announcements(db, rows)
        return {"found": True, "result": rows}

    if action == "notes.listForStudent":
        student_doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id}) if student_id else None
        if student_doc and isinstance(student_doc.get("notes"), list):
            return {"found": True, "result": await _visible_materials(db, student_doc.get("notes") or [])}
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
        if not shared or "notes" not in shared:
            return {"found": False}
        account = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id}) if student_id else None
        return {"found": True, "result": _notes_for_student(await _visible_materials(db, shared.get("notes") or []), account)}

    field = PERSONAL_ACTIONS.get(action)
    if not field or not student_id:
        return {"found": False}
    doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id})
    if not doc:
        if field == "stats":
            return {"found": True, "result": {}}
        return {"found": True, "result": []}
    logs = _merge_logs(doc.get("studyLog") if isinstance(doc.get("studyLog"), list) else [], [])
    stats = doc.get("stats") if isinstance(doc.get("stats"), dict) else {}
    if field == "studyLog":
        raw = doc.get("studyLog") if isinstance(doc.get("studyLog"), list) else []
        if len(logs) != len(raw):
            stats = _recompute_stats(logs, stats)
            reports = _weekly_reports_from_logs(logs, stats)
            await db[DASHBOARD_STUDENTS].update_one(
                {"studentId": student_id},
                {"$set": {"studyLog": logs, "stats": stats, "reports": reports, "updatedAt": _now()}},
            )
            await _rebuild_leaderboard(db)
        return {"found": True, "result": logs}
    if field == "stats":
        if logs:
            stats = _recompute_stats(logs, stats)
        return {"found": True, "result": stats or {}}
    if field == "reports":
        generated = _weekly_reports_from_logs(logs, stats)
        return {"found": True, "result": generated or doc.get("reports") or []}
    if field not in doc:
        return {"found": False}
    return {"found": True, "result": doc.get(field) or []}


async def _student_doc(db, student_id: str) -> dict:
    doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id}) or {}
    doc.setdefault("studentId", student_id)
    doc.setdefault("stats", {})
    doc.setdefault("studyLog", [])
    doc.setdefault("reports", [])
    doc.setdefault("mentorNotes", [])
    doc.setdefault("feedback", [])
    return doc


async def apply_dashboard_write(action: str, payload: dict, result: Any = None) -> dict:
    payload = payload or {}
    db = get_db()
    now = _now()

    if action == "addStudyLog":
        sid = normalize_student_id(payload.get("studentId") or "")
        if not sid:
            return {"ok": False, "message": "Student ID missing."}
        hours = float(payload.get("hours") or 0)
        entry_date = str(payload.get("date") or _today())[:10]
        proof = ""
        if isinstance(result, dict):
            proof = str(result.get("proofUrl") or "")
        proof = proof or str(payload.get("proofUrl") or "")
        row = {
            "date": entry_date,
            "topic": str(payload.get("subjects") or payload.get("reason") or payload.get("topic") or ""),
            "hours": hours,
            "proof": proof,
        }
        doc = await _student_doc(db, sid)
        logs = _merge_logs(doc.get("studyLog") or [], [row])
        stats = _recompute_stats(logs, doc.get("stats") or {})
        reports = _weekly_reports_from_logs(logs, stats)
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "studyLog": logs, "stats": stats, "reports": reports, "updatedAt": now}},
            upsert=True,
        )
        await _rebuild_leaderboard(db)
        return {"ok": True, "success": True, "proofUrl": proof, "stats": stats}

    if action == "deleteStudyLog":
        sid = normalize_student_id(payload.get("studentId") or "")
        date = str(payload.get("date") or "")[:10]
        topic = str(payload.get("topic") or payload.get("subjects") or "")
        try:
            hours = round(float(payload.get("hours") or 0), 2)
        except (TypeError, ValueError):
            hours = 0.0
        if not sid or not date:
            return {"ok": False, "message": "Date missing."}
        doc = await _student_doc(db, sid)
        logs = []
        removed = False
        for row in list(doc.get("studyLog") or []):
            if not isinstance(row, dict):
                continue
            try:
                row_hours = round(float(row.get("hours") or 0), 2)
            except (TypeError, ValueError):
                row_hours = 0.0
            same = (
                str(row.get("date") or "")[:10] == date
                and row_hours == hours
                and (not topic or str(row.get("topic") or "") == topic)
            )
            if same and not removed:
                removed = True
                continue
            logs.append(row)
        logs = _merge_logs(logs, [])
        stats = _recompute_stats(logs, doc.get("stats") or {})
        reports = _weekly_reports_from_logs(logs, stats)
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "studyLog": logs, "stats": stats, "reports": reports, "updatedAt": now}},
            upsert=True,
        )
        await _rebuild_leaderboard(db)
        return {"ok": True, "success": True, "removed": removed, "stats": stats}

    if action == "announcements.create":
        created = result if isinstance(result, dict) else {}
        item = {
            "id": created.get("id") or f"ANN-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "title": created.get("title") or payload.get("title") or "",
            "message": created.get("body") or created.get("message") or payload.get("body") or payload.get("message") or "",
            "audience": created.get("audience") or payload.get("audience") or "All Batches",
            "date": created.get("date") or _today(),
            "pinned": bool(created.get("pinned")),
            "author": created.get("author") or "Ujjwal Pathak",
        }
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        announcements = await _visible_announcements(db, [item] + list(shared.get("announcements") or []))
        await db[DASHBOARD_SHARED].update_one(
            {"_id": "shared"},
            {"$set": {"announcements": announcements[:200], "updatedAt": now}},
            upsert=True,
        )
        return {"ok": True, "result": item}

    if action in {"notes.create", "notes.finalizeUpload"}:
        created = result if isinstance(result, dict) else {}
        item = {
            "id": created.get("id") or payload.get("id") or f"NOTE-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "title": payload.get("title") or created.get("title") or "",
            "description": payload.get("description") or "",
            "subject": payload.get("subject") or "",
            "audience": payload.get("audience") or "All Batches",
            "group": payload.get("group") or "Both Groups",
            "fileName": payload.get("fileName") or "",
            "fileId": created.get("fileId") or payload.get("fileId") or "",
            "fileUrl": payload.get("fileUrl") or created.get("fileUrl") or "",
            "uploadedBy": "Ujjwal Pathak",
            "date": _today(),
            "category": payload.get("category") or "",
        }
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        notes = await _visible_materials(db, [item] + list(shared.get("notes") or []))
        await db[DASHBOARD_SHARED].update_one(
            {"_id": "shared"},
            {"$set": {"notes": notes[:400], "updatedAt": now}},
            upsert=True,
        )
        return {"ok": True, "result": item}

    if action == "students.addNote":
        sid = normalize_student_id(payload.get("id") or payload.get("studentId") or "")
        note = str(payload.get("note") or "").strip()
        if not sid or not note:
            return {"ok": False, "message": "Note missing."}
        doc = await _student_doc(db, sid)
        notes = [{"date": _today(), "note": note}] + list(doc.get("mentorNotes") or [])
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "mentorNotes": notes[:200], "updatedAt": now}},
            upsert=True,
        )
        return {"ok": True}

    if action == "feedback.send":
        sid = normalize_student_id(payload.get("studentId") or "")
        message = str(payload.get("message") or "").strip()
        if not sid or not message:
            return {"ok": False, "message": "Feedback missing."}
        doc = await _student_doc(db, sid)
        item = {
            "id": f"FB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "studentId": sid,
            "date": _today(),
            "mentor": payload.get("mentor") or "Ujjwal Pathak",
            "message": message,
        }
        feedback = [item] + list(doc.get("feedback") or [])
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "feedback": feedback[:200], "updatedAt": now}},
            upsert=True,
        )
        return {"ok": True}

    if action == "feedback.read":
        fid = str(payload.get("id") or "")
        sid = normalize_student_id(payload.get("studentId") or "")
        if sid:
            doc = await _student_doc(db, sid)
            feedback = [x for x in (doc.get("feedback") or []) if str(x.get("id")) != fid]
            await db[DASHBOARD_STUDENTS].update_one(
                {"studentId": sid},
                {"$set": {"feedback": feedback, "updatedAt": now}},
                upsert=True,
            )
        return {"ok": True, "success": True}

    return {"ok": False, "message": f"Unsupported write: {action}"}


@router.post("/write")
async def write_dashboard_section(body: DashboardWriteBody):
    action = str(body.action or "").strip()
    payload = body.payload if isinstance(body.payload, dict) else {}
    applied = await apply_dashboard_write(action, payload, body.result)
    if not applied.get("ok"):
        return {"ok": False, "result": {"success": False, "message": applied.get("message") or "Write failed"}}
    return {"ok": True, "result": applied.get("result") or {"success": True, "proofUrl": applied.get("proofUrl"), "stats": applied.get("stats")}}
