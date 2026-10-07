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
from db import (
    DASHBOARD_SHARED,
    DASHBOARD_STUDENTS,
    STUDENT_ACCOUNTS,
    STUDENT_MCQ_ATTEMPTS,
    get_db,
)
from routers import ranking as ranking_lib
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
# Leaderboard freshness. Students read a stored snapshot through the frozen app,
# which cannot ask for a refresh, so freshness must not depend on a submission
# happening or on anyone pressing a button: any read that finds the snapshot older
# than this rebuilds it, at most one rebuild at a time.
LEADERBOARD_MAX_AGE_SECONDS = int(os.environ.get("LEADERBOARD_MAX_AGE_SECONDS", "90"))
LEADERBOARD_REBUILD_LOCK_SECONDS = int(os.environ.get("LEADERBOARD_REBUILD_LOCK_SECONDS", "30"))
LEADERBOARD_REBUILD_CLAIM = "leaderboard_rebuild_claim"

TRACKER_HISTORY_FLOOR = date.fromisoformat(
    os.environ.get("TRACKER_HISTORY_FLOOR", "2026-09-28").strip()
)


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

    def column(*aliases: str) -> Optional[str]:
        for alias in aliases:
            match = by_key.get(_header_key(alias))
            if match:
                return match
        return None

    id_col = column("Student ID", "StudentId")
    timestamp_col = column("Timestamp")
    study_date_col = column("Study Date")
    hours_col = column("Total Study Hours", "Study Hours", "Hours")
    reason_col = column("What was the main reason you couldn't study today?", "Reason")
    subjects_col = column("Which subjects did you study today?", "Subjects")
    tomorrow_col = column("What is your target for tomorrow?", "Tomorrow Target")
    support_col = column("Do you need mentor support?", "Mentor Support")
    proof_col = column("Upload today's study proof", "Study Proof", "Proof")
    if not id_col or not timestamp_col:
        raise RuntimeError("Tracker sheet columns could not be identified.")

    submissions = []
    for row in reader:
        sid = normalize_student_id(row.get(id_col) or "")
        timestamp = str(row.get(timestamp_col) or "").strip()
        day = _tracker_submission_day(
            row.get(study_date_col) if study_date_col else "",
            timestamp,
        )
        if not sid or not day:
            continue
        try:
            hours = float(re.sub(r"[^0-9.]+", "", str(row.get(hours_col) or ""))) if hours_col else 0.0
        except ValueError:
            hours = 0.0
        submissions.append({
            "studentId": sid,
            "date": day,
            "hours": max(0.0, hours),
            "subjects": str(row.get(subjects_col) or "").strip() if subjects_col else "",
            "tomorrowTarget": str(row.get(tomorrow_col) or "").strip() if tomorrow_col else "",
            "reason": str(row.get(reason_col) or "").strip() if reason_col else "",
            "mentorSupport": str(row.get(support_col) or "").strip() if support_col else "",
            "proofUrl": str(row.get(proof_col) or "").strip() if proof_col else "",
            "submissionTime": timestamp,
            "source": "form",
        })
    return submissions


async def _fetch_mongo_tracker_submissions(db) -> list[dict]:
    """Read app tracker/study-log rows already persisted in Mongo."""
    submissions = []
    async for doc in db[DASHBOARD_STUDENTS].find({}, {"studentId": 1, "studyLog": 1}):
        sid = normalize_student_id(doc.get("studentId") or "")
        if not sid:
            continue
        for row in doc.get("studyLog") or []:
            if not isinstance(row, dict):
                continue
            day = _parse_tracker_day(row.get("date") or "")
            if not day:
                continue
            try:
                hours = max(0.0, float(row.get("hours") or 0))
            except (TypeError, ValueError):
                hours = 0.0
            submissions.append({
                "studentId": sid,
                "date": day,
                "hours": hours,
                "subjects": str(row.get("topic") or "").strip(),
                "tomorrowTarget": "",
                "reason": "",
                "mentorSupport": "",
                "proofUrl": str(row.get("proof") or "").strip(),
                "submissionTime": "",
                "source": "mongo",
            })
    return submissions


def _fetch_tracker_roster_sync() -> list[dict]:
    """Read only non-sensitive roster columns from the authoritative Students sheet."""
    if not TRACKER_SHEET_ID:
        raise RuntimeError("Tracker sheet is not configured.")
    url = f"https://docs.google.com/spreadsheets/d/{TRACKER_SHEET_ID}/gviz/tq"
    response = requests.get(
        url,
        params={
            "tqx": "out:csv",
            "sheet": "Students",
            # Never fetch email, password or access-control columns.
            "tq": "select A,B,E,F,G",
            "_": str(int(datetime.now().timestamp())),
        },
        headers={"User-Agent": "UPM-mentor-tracker-roster/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    rows = []
    for row in reader:
        sid = normalize_student_id(row.get("Student ID") or "")
        if not sid:
            continue
        rows.append({
            "studentId": sid,
            "studentName": str(row.get("Student Name") or sid).strip() or sid,
            "group": str(row.get("Group") or "Unassigned").strip() or "Unassigned",
            "attempt": str(row.get("Attempt") or "").strip(),
            "batch": str(row.get("Batch") or "Unassigned").strip() or "Unassigned",
        })
    return rows


def _merge_tracker_roster(accounts: list[dict], sheet_rows: list[dict]) -> list[dict]:
    """Use Sheet ID/name/cohort metadata while retaining Mongo joining dates."""
    if not sheet_rows:
        return accounts
    mongo_by_id = {
        normalize_student_id(account.get("studentId") or ""): account
        for account in accounts
        if normalize_student_id(account.get("studentId") or "")
    }
    merged = []
    for sheet_row in sheet_rows:
        sid = normalize_student_id(sheet_row.get("studentId") or "")
        base = dict(mongo_by_id.get(sid) or {})
        base.update(sheet_row)
        base["studentId"] = sid
        merged.append(base)
    return merged


async def _tracker_roster(accounts: list[dict]) -> tuple[list[dict], str]:
    try:
        sheet_rows = await asyncio.to_thread(_fetch_tracker_roster_sync)
    except Exception:
        return accounts, "Mongo fallback"
    return _merge_tracker_roster(accounts, sheet_rows), "Students Sheet"


def _full_tracker_history_start(
    accounts: list[dict],
    submissions: list[dict],
    today: date,
) -> date:
    """Earliest genuine joining/submission date for the Jan 2027 roster.

    Students with a valid joinedOn still begin on their own date in the report.
    A submission date is also considered so rows with missing joinedOn do not
    lose genuine tracker history from before the earliest known joining date.
    """
    roster_ids = {
        normalize_student_id(account.get("studentId") or "")
        for account in accounts
        if not account.get("master")
        and _attempt_ym(account.get("attempt") or "", account.get("batch") or "") == (2027, 1)
    }
    roster_ids.discard("")
    candidates = []
    for account in accounts:
        sid = normalize_student_id(account.get("studentId") or "")
        if sid not in roster_ids:
            continue
        joined = _parse_tracker_day(account.get("joinedOn") or "")
        if joined and joined <= today:
            candidates.append(joined)
    for row in submissions:
        sid = normalize_student_id(row.get("studentId") or "")
        day = row.get("date")
        if sid in roster_ids and isinstance(day, date) and day <= today:
            candidates.append(day)
    return min(candidates) if candidates else today


def _ist_day_from_ms(value: Any) -> Optional[date]:
    """Epoch milliseconds from an app client -> IST calendar date."""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    if ms > 1e12:  # already milliseconds; guard against seconds being passed
        ms = ms
    try:
        stamp = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.astimezone(IST).date()


async def _mcq_days_by_student(db) -> dict:
    """Real MCQ performance per student, keyed by IST day.

    Uses the attempts the app already syncs (``student_mcq_attempts``), so the MCQ
    component of the composite score is genuine data rather than a guess.
    """
    totals: dict = {}
    async for row in db[STUDENT_MCQ_ATTEMPTS].find(
        {}, {"studentId": 1, "completedAt": 1, "score": 1, "total": 1}
    ):
        sid = normalize_student_id(row.get("studentId") or "")
        day = _ist_day_from_ms(row.get("completedAt"))
        if not sid or not day:
            continue
        try:
            total = int(row.get("total") or 0)
            score = int(row.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        by_day = totals.setdefault(sid, {})
        bucket = by_day.setdefault(day, [0, 0])
        bucket[0] += max(0, total)
        bucket[1] += max(0, min(score, total))
    return totals


def _tracker_cohort_accounts(accounts: list) -> list:
    """Jan 2027 cohort, master accounts excluded. Same rule as the tracker."""
    return [
        account for account in accounts
        if not account.get("master")
        and _attempt_ym(account.get("attempt") or "", account.get("batch") or "") == (2027, 1)
    ]


async def _ranking_activities(db, accounts: list, include_sheets: bool = False) -> tuple[list, dict]:
    """Build per-student ranking inputs.

    Hours: the greater of the Mongo study-log total and the legacy Form total for
    each student/day, mirroring the day view so the same submission is never
    counted twice. Submissions: a day counts if either source has a row.

    ``include_sheets`` is False for the stored rebuild that runs inside student
    writes: that path must stay Mongo-only so a slow or unavailable Google Sheets
    can never slow down a student submitting their study log. The mentor endpoint
    passes True, where authoritative Sheet names and full legacy history matter.
    """
    cohort = _tracker_cohort_accounts(accounts)
    mongo_rows = await _fetch_mongo_tracker_submissions(db)
    if include_sheets:
        try:
            form_rows = await asyncio.to_thread(_fetch_tracker_submissions_sync)
            form_ok = True
        except Exception:
            form_rows = []
            form_ok = False
    else:
        form_rows = []
        form_ok = False

    hours: dict = {}
    submitted: dict = {}
    for row in list(mongo_rows) + list(form_rows):
        sid = normalize_student_id(row.get("studentId") or "")
        day = row.get("date")
        if not sid or not isinstance(day, date):
            continue
        try:
            value = max(0.0, float(row.get("hours") or 0))
        except (TypeError, ValueError):
            value = 0.0
        submitted.setdefault(sid, set()).add(day)
        per_student = hours.setdefault(sid, {})
        source = row.get("source") or "form"
        bucket = per_student.setdefault(day, {})
        bucket[source] = max(bucket.get(source, 0.0), value)

    mcq = await _mcq_days_by_student(db)

    activities = []
    for account in cohort:
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        hours_by_date = {}
        for day, by_source in (hours.get(sid) or {}).items():
            hours_by_date[day] = max(by_source.values()) if by_source else 0.0
        attempted = 0
        correct = 0
        for _, (total, score) in (mcq.get(sid) or {}).items():
            attempted += total
            correct += score
        activities.append(ranking_lib.StudentActivity(
            student_id=sid,
            name=str(account.get("studentName") or "").strip() or sid,
            batch=str(account.get("batch") or "").strip(),
            group=str(account.get("group") or "").strip(),
            attempt=str(account.get("attempt") or "").strip(),
            joined_on=_parse_tracker_day(account.get("joinedOn") or ""),
            hours_by_date=hours_by_date,
            submitted_dates=set(submitted.get(sid) or set()),
            questions_attempted=attempted,
            questions_correct=correct,
        ))
    return activities, {
        "mongoRows": len(mongo_rows),
        "formRows": len(form_rows),
        "formRead": form_ok,
        "cohort": len(activities),
    }


def _ranking_row(ranking, display: dict) -> dict:
    """One leaderboard row.

    ``display`` carries the period-independent figures the shipped app/APK always
    renders (weekly hours, total hours, streak); ``ranking`` supplies the rank and
    score for the period being requested.
    """
    return {
        # --- keys the shipped app/APK already reads: keep names and meanings ---
        "studentId": ranking.student_id,
        "studentName": ranking.name,
        "weeklyHours": round(float(display.get("weeklyHours") or 0), 1),
        "totalHours": round(float(display.get("totalHours") or 0), 2),
        "streak": int(display.get("streak") or 0),
        "status": "Active" if display.get("active") else "Inactive",
        # --- ranking fields ---
        "rank": ranking.rank,
        "score": ranking.score,
        "hours": round(ranking.hours, 2),
        "hoursPerDay": ranking.hours_per_day,
        "mcqAccuracy": ranking.accuracy,
        "attendance": round(ranking.attendance_rate * 100),
        "submittedDays": ranking.submitted_days,
        "expectedDays": ranking.expected_days,
        "batch": ranking.batch,
        "group": ranking.group,
        "breakdown": ranking.breakdown,
        "mcqUsed": ranking.mcq_used,
        "components": list(ranking.components or []),
        "notRankedReason": ranking.not_ranked_reason,
    }


def _global_positions(segments: dict) -> dict:
    """student_id -> position when every segment is merged into one list.

    The student app reads a single cross-batch list with a rank column and no batch
    column, so the student-facing number has to be unique across the whole cohort.
    Per-batch ranks would print the same number twice in that list.
    """
    flat = [row for rows in segments.values() for row in rows]
    flat.sort(key=ranking_lib.sort_key)
    return {row.student_id: index for index, row in enumerate(flat, start=1)}


def _ranked_segments(activities: list, period: str, segment_by: str, today: date) -> dict:
    start, end = ranking_lib.period_window(period, today, TRACKER_HISTORY_FLOOR)
    return ranking_lib.rank_segments(
        activities, start, end, period, segment_by, TRACKER_HISTORY_FLOOR
    )


def _display_fields(activities: list, today: date, streaks: dict) -> dict:
    """Weekly/total hours per student, for the columns the clients always show."""
    weekly = ranking_lib.period_window("weekly", today, TRACKER_HISTORY_FLOOR)
    overall = ranking_lib.period_window("overall", today, TRACKER_HISTORY_FLOOR)
    display = {}
    for activity in activities:
        weekly_row = ranking_lib.score_student(activity, *weekly, "weekly", TRACKER_HISTORY_FLOOR)
        overall_row = ranking_lib.score_student(activity, *overall, "overall", TRACKER_HISTORY_FLOOR)
        display[activity.student_id] = {
            "weeklyHours": weekly_row.hours,
            "totalHours": overall_row.hours,
            "streak": int(streaks.get(activity.student_id) or 0),
            "active": weekly_row.is_active,
        }
    return display


def _build_missed_tracker_report(
    accounts: list[dict],
    submissions: list[dict],
    from_day: date,
    to_day: date,
    use_submission_start_for_missing_joined: bool = False,
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
        if joined:
            expected_from = max(from_day, joined)
        elif use_submission_start_for_missing_joined:
            expected_from = min(submitted_by_student.get(sid, set()), default=from_day)
        else:
            expected_from = from_day
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


def _tracker_days_through(today: date, count: int = 14) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


def _tracker_day_entry(form_rows: list[dict], mongo_rows: list[dict], selected: date) -> dict:
    submitted = bool(form_rows or mongo_rows)
    form_hours = sum(float(row.get("hours") or 0) for row in form_rows)
    mongo_hours = sum(float(row.get("hours") or 0) for row in mongo_rows)

    def latest_value(field: str) -> str:
        for row in reversed(form_rows + mongo_rows):
            value = str(row.get(field) or "").strip()
            if value:
                return value
        return ""

    subjects = []
    for row in form_rows + mongo_rows:
        value = str(row.get("subjects") or "").strip()
        if value and value not in subjects:
            subjects.append(value)
    return {
        "date": selected.isoformat(),
        "submitted": submitted,
        # The same app submission can be mirrored into both stores. Taking the
        # larger source total avoids double-counting while still showing all
        # same-day entries from the authoritative source.
        "hours": round(max(form_hours, mongo_hours), 2),
        "subjects": ", ".join(subjects),
        "tomorrowTarget": latest_value("tomorrowTarget"),
        "reason": latest_value("reason"),
        "mentorSupport": latest_value("mentorSupport"),
        "submissionTime": latest_value("submissionTime"),
        "proofUrl": latest_value("proofUrl"),
        "sources": sorted({str(row.get("source") or "") for row in form_rows + mongo_rows if row.get("source")}),
    }


@router.get("/leaderboard")
async def mentor_leaderboard(
    period: str = Query("overall"),
    segment: str = Query("batch"),
    batch: Optional[str] = Query(None),
    group: Optional[str] = Query(None),
    attempt: Optional[str] = Query(None),
    refresh: int = Query(0),
    _mentor=Depends(require_mentor),
):
    """Ranked leaderboard computed from live Mongo data.

    Replaces the legacy Apps Script ``leaderboard.list`` call, which returned
    every student with zero stats and no rank at all.
    """
    period = (period or "overall").strip().lower()
    if period not in ranking_lib.PERIODS:
        raise HTTPException(status_code=400, detail="period must be overall, weekly or monthly")
    segment = (segment or "batch").strip().lower()
    if segment not in ("batch", "group"):
        raise HTTPException(status_code=400, detail="segment must be batch or group")

    db = get_db()
    if refresh:
        # Push corrected ranks into the stored leaderboard and each student's
        # stats straight away, so installed app clients are fixed without waiting
        # for the next student submission to trigger a rebuild. Mongo-only.
        await _rebuild_leaderboard(db)
    accounts = [account async for account in db[STUDENT_ACCOUNTS].find({})]
    roster, roster_source = await _tracker_roster(accounts)
    activities, sources = await _ranking_activities(db, roster, include_sheets=True)

    def keep(activity) -> bool:
        if batch and activity.batch != batch:
            return False
        if group and activity.group != group:
            return False
        if attempt and activity.attempt != attempt:
            return False
        return True

    activities = [a for a in activities if keep(a)]
    today = datetime.now(IST).date()
    streaks = {}
    student_stats = {}
    async for doc in db[DASHBOARD_STUDENTS].find({}, {"studentId": 1, "stats": 1}):
        sid = normalize_student_id(doc.get("studentId") or "")
        if sid:
            stats = doc.get("stats") if isinstance(doc.get("stats"), dict) else {}
            student_stats[sid] = stats
            streaks[sid] = int(stats.get("streak") or 0)
    display = _display_fields(activities, today, streaks)

    start, end = ranking_lib.period_window(period, today, TRACKER_HISTORY_FLOOR)
    segments = _ranked_segments(activities, period, segment, today)

    payload = []
    members_by_key = {}
    for activity in activities:
        bucket = (getattr(activity, segment, "") or "").strip() or "(unassigned)"
        members_by_key.setdefault(bucket, []).append(activity)

    for key, rankings in segments.items():
        members = members_by_key.get(key) or []
        coverage = ranking_lib.mcq_coverage(members, start, end, TRACKER_HISTORY_FLOOR)
        payload.append({
            "key": key,
            "label": key,
            "studentCount": len(rankings),
            "mcqUsed": ranking_lib.mcq_enabled(members, start, end, TRACKER_HISTORY_FLOOR),
            "mcqCoverage": round(coverage, 3),
            "entries": [_ranking_row(r, display.get(r.student_id) or {}) for r in rankings],
        })

    return JSONResponse(
        {
            "period": period,
            "segment": segment,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "historyFloor": TRACKER_HISTORY_FLOOR.isoformat(),
            "generatedAt": _now(),
            "source": {"roster": roster_source, "scoring": "mongo", **sources},
            "weights": {
                "hours": ranking_lib.W_HOURS,
                "mcq": ranking_lib.W_MCQ,
                "attendance": ranking_lib.W_ATTENDANCE,
                "mcqMode": ranking_lib.MCQ_MODE,
                "mcqMinCoverage": ranking_lib.MCQ_MIN_COVERAGE,
            },
            "segments": payload,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/tracker-day")
async def tracker_day(
    day_index: int = Query(default=13, alias="dayIndex", ge=0, le=13),
    batch: str = Query(default="All Batches"),
    _mentor=Depends(require_mentor),
):
    """Live day view merged from app/Mongo logs and legacy Form responses."""
    today = datetime.now(IST).date()
    days = _tracker_days_through(today)
    selected = days[max(0, min(len(days) - 1, day_index))]
    db = get_db()
    accounts = await db[STUDENT_ACCOUNTS].find(
        {},
        {
            "_id": 0,
            "studentId": 1,
            "studentName": 1,
            "attempt": 1,
            "batch": 1,
            "group": 1,
            "joinedOn": 1,
            "master": 1,
        },
    ).to_list(length=5000)
    accounts, roster_source = await _tracker_roster(accounts)
    mongo_rows = await _fetch_mongo_tracker_submissions(db)
    form_error = ""
    try:
        form_rows = await asyncio.to_thread(_fetch_tracker_submissions_sync)
    except Exception as exc:
        # Current app submissions are already in Mongo. Keep the live day view
        # usable during a temporary public-Sheet read outage and surface source
        # health in metadata instead of silently marking everyone missed.
        form_rows = []
        form_error = type(exc).__name__

    form_by_student: dict[str, list[dict]] = {}
    mongo_by_student: dict[str, list[dict]] = {}
    for row in form_rows:
        if row.get("date") == selected:
            form_by_student.setdefault(normalize_student_id(row.get("studentId") or ""), []).append(row)
    for row in mongo_rows:
        if row.get("date") == selected:
            mongo_by_student.setdefault(normalize_student_id(row.get("studentId") or ""), []).append(row)

    requested_batch = str(batch or "All Batches").strip()
    items = []
    for account in accounts:
        if account.get("master") or _attempt_ym(account.get("attempt") or "", account.get("batch") or "") != (2027, 1):
            continue
        account_batch = str(account.get("batch") or "Unassigned").strip() or "Unassigned"
        if requested_batch not in {"", "All Batches"} and account_batch != requested_batch:
            continue
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        name = str(account.get("studentName") or sid).strip() or sid
        items.append({
            "id": sid,
            "name": name,
            "avatar": f"https://ui-avatars.com/api/?background=2563EB&color=fff&size=200&name={sid}",
            "batch": account_batch,
            "group": str(account.get("group") or "Unassigned").strip() or "Unassigned",
            "entry": _tracker_day_entry(
                form_by_student.get(sid, []),
                mongo_by_student.get(sid, []),
                selected,
            ),
        })
    items.sort(key=lambda row: (not row["entry"]["submitted"], row["name"].lower(), row["id"]))
    submitted = sum(1 for row in items if row["entry"]["submitted"])
    return {
        "list": items,
        "submitted": submitted,
        "missed": max(0, len(items) - submitted),
        "rate": round((submitted / len(items)) * 100) if items else 0,
        "days": [day.isoformat() for day in days],
        "selectedDay": selected.isoformat(),
        "sources": {
            "formRows": len(form_rows),
            "mongoRows": len(mongo_rows),
            "formReadOk": not bool(form_error),
            "roster": roster_source,
        },
        "generatedAt": _now(),
    }


@router.get("/tracker-missed-report")
async def tracker_missed_report(
    from_value: Optional[str] = Query(default=None, alias="from"),
    to_value: Optional[str] = Query(default=None, alias="to"),
    scope: str = Query(default="range"),
    _mentor=Depends(require_mentor),
):
    normalized_scope = str(scope or "range").strip().lower()
    full_history = normalized_scope in {"full", "joined-to-date", "joined_to_date"}
    if not full_history and normalized_scope != "range":
        raise HTTPException(status_code=400, detail="Scope must be range or joined-to-date.")

    today = datetime.now(IST).date()
    if full_history:
        # The exact start is resolved after loading the roster and complete
        # tracker history. The end is deliberately always today in India.
        from_day = None
        to_day = today
    else:
        from_day = _parse_tracker_day(from_value)
        to_day = _parse_tracker_day(to_value)
        if not from_day or not to_day:
            raise HTTPException(status_code=400, detail="From and To must be valid YYYY-MM-DD dates.")
        if from_day > to_day:
            raise HTTPException(status_code=400, detail="From date cannot be after To date.")
        if (to_day - from_day).days > 365:
            raise HTTPException(status_code=400, detail="Choose a date range of 366 days or fewer.")
        if to_day > today:
            raise HTTPException(status_code=400, detail="To date cannot be in the future.")
        history_floor = min(TRACKER_HISTORY_FLOOR, today)
        if to_day < history_floor:
            raise HTTPException(status_code=400, detail=f"Tracker attendance is available from {history_floor.isoformat()}.")
        from_day = max(from_day, history_floor)

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
    accounts, roster_source = await _tracker_roster(accounts)
    try:
        form_submissions = await asyncio.to_thread(_fetch_tracker_submissions_sync)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Tracker form data could not be loaded. No report was calculated.") from exc
    mongo_submissions = await _fetch_mongo_tracker_submissions(db)
    submissions = form_submissions + mongo_submissions

    if full_history:
        resolved_start = _full_tracker_history_start(accounts, submissions, today)
        from_day = max(resolved_start, min(TRACKER_HISTORY_FLOOR, today))
        if (to_day - from_day).days > 1095:
            raise HTTPException(status_code=400, detail="Full tracker history exceeds the supported three-year window.")

    report = _build_missed_tracker_report(
        accounts,
        submissions,
        from_day,
        to_day,
        use_submission_start_for_missing_joined=full_history,
    )
    report["scope"] = "joined-to-date" if full_history else "range"
    report["source"] = "Form responses 1 + Mongo study logs"
    report["sourceSubmissionRows"] = len(form_submissions)
    report["sourceMongoRows"] = len(mongo_submissions)
    report["rosterSource"] = roster_source
    report["historyFloor"] = min(TRACKER_HISTORY_FLOOR, today).isoformat()
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
        # Rank fields are written by _rebuild_leaderboard and carried through here,
        # so recomputing hours never silently drops a student's ranking.
        "rank": int(prev.get("rank") or 0),
        "weeklyRank": int(prev.get("weeklyRank") or 0),
        "monthlyRank": int(prev.get("monthlyRank") or 0),
        "rankInBatch": int(prev.get("rankInBatch") or 0),
        "rankBatch": str(prev.get("rankBatch") or ""),
        "score": prev.get("score") or 0,
    }


def _weekly_reports_from_logs(logs: list, stats: Optional[dict] = None,
                              weekly_ranks: Optional[dict] = None) -> list:
    """Weekly reports. `weekly_ranks` maps week key -> ranked-for-that-week value.

    A week with no known rank reports ``None`` rather than 0, so clients stop
    showing "Rank #0" for history the backend cannot rank.
    """
    stats = dict(stats or {})
    weekly_ranks = dict(weekly_ranks or {})
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
            "rank": (int(stats.get("weeklyRank") or stats.get("rank") or 0) if key == this_week
                     else weekly_ranks.get(key)),
            "level": level,
        }
        out.append(item)
    return out[:12]


async def _rebuild_leaderboard(db) -> None:
    """Recompute the stored leaderboard from live Mongo data.

    Rank is per Batch segment (owner decision), unique, and composite-scored. The
    stored rows keep every key the shipped app/APK reads, so installed clients get
    corrected ranks without a new build.
    """
    accounts = [account async for account in db[STUDENT_ACCOUNTS].find({})]
    # Mongo-only on purpose: this runs inside student write requests, so it must
    # never wait on Google Sheets. The mentor endpoint merges the Sheet roster.
    roster_source = "Mongo"
    activities, sources = await _ranking_activities(db, accounts, include_sheets=False)
    today = datetime.now(IST).date()

    streaks = {}
    student_stats = {}
    async for doc in db[DASHBOARD_STUDENTS].find({}, {"studentId": 1, "stats": 1}):
        sid = normalize_student_id(doc.get("studentId") or "")
        if sid:
            stats = doc.get("stats") if isinstance(doc.get("stats"), dict) else {}
            student_stats[sid] = stats
            streaks[sid] = int(stats.get("streak") or 0)
    display = _display_fields(activities, today, streaks)

    by_batch = _ranked_segments(activities, "overall", "batch", today)
    by_batch_weekly = _ranked_segments(activities, "weekly", "batch", today)
    by_batch_monthly = _ranked_segments(activities, "monthly", "batch", today)

    # Two views of the same computation:
    #   batch_rank  -> position inside the student's own batch. The mentor
    #                  dashboard ranks this way (owner decision).
    #   global_rank -> position in the merged cohort list. This is what students
    #                  see, because the app renders one cross-batch table whose
    #                  rank column would otherwise repeat the same number.
    batch_rank = {r.student_id: r.rank for rows in by_batch.values() for r in rows}
    global_rank = _global_positions(by_batch)
    weekly_rank = _global_positions(by_batch_weekly)
    monthly_rank = _global_positions(by_batch_monthly)

    flat = [r for rows in by_batch.values() for r in rows]
    flat.sort(key=ranking_lib.sort_key)

    rows = []
    for ranking in flat:
        row = _ranking_row(ranking, display.get(ranking.student_id) or {})
        sid = ranking.student_id
        # `rank` is the rank within the student's own batch (owner decision).
        # The overall position is carried alongside so a flat client list can still
        # be ordered coherently.
        row["rank"] = int(global_rank.get(sid) or 0)
        row["rankOverall"] = int(global_rank.get(sid) or 0)
        row["rankInBatch"] = int(batch_rank.get(sid) or 0)
        rows.append(row)

    # Push the period ranks onto each student's stats — but only when a value
    # actually changed, so a routinely-refreshing snapshot costs almost no writes.
    existing = {sid: (stats or {}) for sid, stats in student_stats.items()}
    for row in rows:
        sid = row["studentId"]
        target = {
            # `rank` must equal the student's position in the list they are shown,
            # otherwise the tile and the table disagree on the same screen.
            "rank": int(global_rank.get(sid) or 0),
            "weeklyRank": int(weekly_rank.get(sid) or 0),
            "monthlyRank": int(monthly_rank.get(sid) or 0),
            "rankInBatch": int(batch_rank.get(sid) or 0),
            "score": row.get("score"),
            "rankBatch": row.get("batch") or "",
        }
        current = existing.get(sid) or {}
        if all(current.get(key) == value for key, value in target.items()):
            continue
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {f"stats.{key}": value for key, value in target.items()}},
        )

    await db[DASHBOARD_SHARED].update_one(
        {"_id": "shared"},
        {"$set": {
            "leaderboard": rows,
            "leaderboardMeta": {
                "generatedAt": _now(),
                "segment": "batch",
                "historyFloor": TRACKER_HISTORY_FLOOR.isoformat(),
                "rosterSource": roster_source,
                **sources,
            },
        }},
        upsert=True,
    )


def _seconds_since(iso_value: str, now: datetime) -> Optional[float]:
    raw = str(iso_value or "").strip()
    if not raw:
        return None
    try:
        return (now - datetime.fromisoformat(raw)).total_seconds()
    except (TypeError, ValueError):
        return None


async def _claim_rebuild(db, now: datetime) -> bool:
    """Atomically claim the right to rebuild, so concurrent readers cannot stampede.

    A conditional upsert would be one round trip, but a failed condition turns into
    an insert and raises a duplicate-key error, which mongomock does not raise
    identically. This read-then-claim form behaves the same on both.
    """
    cutoff = (now - timedelta(seconds=LEADERBOARD_REBUILD_LOCK_SECONDS)).isoformat()
    claim = await db[DASHBOARD_SHARED].find_one({"_id": LEADERBOARD_REBUILD_CLAIM})
    if claim and str(claim.get("at") or "") > cutoff:
        return False            # someone rebuilt very recently
    try:
        if claim:
            result = await db[DASHBOARD_SHARED].update_one(
                {"_id": LEADERBOARD_REBUILD_CLAIM, "at": {"$lte": cutoff}},
                {"$set": {"at": now.isoformat()}},
            )
            return bool(result.modified_count)
        await db[DASHBOARD_SHARED].insert_one({"_id": LEADERBOARD_REBUILD_CLAIM, "at": now.isoformat()})
        return True
    except Exception:
        return False            # lost the race; the other caller is rebuilding


async def _leaderboard_snapshot(db, force: bool = False) -> dict:
    """The stored leaderboard, rebuilt automatically when it has gone stale.

    This is what makes ranks update by themselves. The installed app cannot request
    a refresh and there is no scheduler, so freshness is driven by reads: whichever
    request first finds the snapshot older than LEADERBOARD_MAX_AGE_SECONDS
    rebuilds it, everyone else keeps serving the existing rows. That also covers
    the case nobody submits anything — ranks still roll over correctly when the
    weekly window moves.
    """
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    now = datetime.now(timezone.utc)

    if not force:
        # The snapshot's own timestamp is the single source of truth for freshness.
        # A missing timestamp means it has never been built (first run on a fresh
        # database), which is the only case that forces one.
        age = _seconds_since(((shared.get("leaderboardMeta") or {}).get("generatedAt")), now)
        if age is not None and age < LEADERBOARD_MAX_AGE_SECONDS:
            return shared

    if not await _claim_rebuild(db, now):
        return shared           # another request is already rebuilding

    await _rebuild_leaderboard(db)
    return await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or shared


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
    """Student-safe leaderboard: the caller's own batch segment, ranked.

    Ranking is per Batch (owner decision), so a student sees how they stand among
    their own batch rather than against the whole cohort. Closed/unknown cohorts
    stay hidden at read time without deleting stored history.
    """
    allowed = {(2027, 1): "Jan 2027", (2027, 5): "May 2027"}
    attempts = {}
    batches = {}
    async for account in db[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "attempt": 1, "batch": 1}):
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        attempts[sid] = _attempt_ym(account.get("attempt") or "", "")
        batches[sid] = str(account.get("batch") or "").strip()

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
        # Deliberately NOT filtered to the caller's batch. The app renders one
        # table with a rank column and no batch column, and older clients send no
        # studentId at all, so a batch-restricted list would give different
        # students different numbers for the same rank (a web caller sees a
        # cohort-wide #78 while the tile says #11). One meaning, every client.
        # Per-batch ranking lives on the mentor dashboard, which can see batches.
        seen.add(sid)
        item = dict(row)
        item["studentId"] = sid
        item["attempt"] = allowed[attempt]
        item["rankInBatch"] = int(row.get("rankInBatch") or row.get("rank") or 0)
        item["rankOverall"] = int(row.get("rankOverall") or row.get("rank") or 0)
        # `rank` is the cohort-wide position for every caller, so the value a
        # student sees is identical whether they identify themselves or not, and a
        # flat table can never show the same number twice.
        item["rank"] = item["rankOverall"]
        # Never ship contact details to a student client.
        for secret in ("email", "phone", "proof", "proofUrl"):
            item.pop(secret, None)
        result.append(item)
    result.sort(key=lambda r: (int(r.get("rankOverall") or 0), str(r.get("studentId"))))
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
        # getLeaderboard carries the rank snapshot, so refresh it automatically
        # before serving. Announcements do not need a rebuild.
        if action == "getLeaderboard":
            shared = await _leaderboard_snapshot(db)
        else:
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
    if field == "stats":
        # Rank fields live on the student document; refresh the snapshot first so
        # the rank a student sees is never stale.
        await _leaderboard_snapshot(db)
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
