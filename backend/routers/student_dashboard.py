"""Student dashboard reads/writes on Mongo, with sheet import merge."""
import asyncio
import csv
import logging
import io
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from routers.dashboard_access import dashboard_student, own_payload, READ_ACTIONS, WRITE_ACTIONS, deny
from auth import require_mentor
from config import settings
import push as push_service
from db import (
    DASHBOARD_SHARED,
    DASHBOARD_STUDENTS,
    STUDENT_ACCOUNTS,
    STUDENT_MCQ_ATTEMPTS,
    get_db,
)
from routers import attendance as attendance_lib
from routers import access_events as access_lib
from routers import ranking as ranking_lib
# Sunday..Saturday calendar week; `week_start_of` (not `week_start`) because several
# functions here keep a local `week_start` for their rolling 7-day window.
from week_window import week_start as week_start_of
from routers.student_auth import _attempt_access_allowed
from routers.student_auth import normalize_student_id, _attempt_ym

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/student-dashboard", tags=["student-dashboard"])

# Durable tombstones are kept outside the sheet-imported shared document.
# An old sheet sync can never make a mentor-deleted announcement visible again.
ANNOUNCEMENT_DELETIONS = "announcement_deletions"


async def _deleted_announcement_ids(db) -> set:
    return {str(row["_id"]) async for row in db[ANNOUNCEMENT_DELETIONS].find({}, {"_id": 1})}


def _is_removed(account: dict) -> bool:
    """Soft-removed students are out of every roster view but keep their data.

    The mentor removes students who stop studying (owner flow, 2026-10-13):
    removal blocks app login, tracker rows, leaderboards and pushes; a Restore
    brings the student back with everything intact.
    """
    if not isinstance(account, dict):
        return False
    if account.get("removedAt"):
        return True
    return str(account.get("status") or "").strip().lower() == "removed"


def _access_blocked(account: dict) -> bool:
    """True when the mentor switched this student's app access OFF.

    A blocked student cannot log in or submit anything, so keeping them in the
    tracker showed them as "missed" every single day and buried the students who
    actually needed a follow-up. Owner decision (14 Oct 2026): tracker views
    skip blocked students entirely. Turning access back ON brings them straight
    back into the tracker.
    """
    if not isinstance(account, dict):
        return False
    return account.get("accessEnabled") is False


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


class AnnouncementNotifyBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=500)
    audience: str = Field(default="All Batches", max_length=120)
    # Testing hook: when set, the push goes ONLY to this student — the mentor
    # can verify the announcement push end-to-end before a real broadcast.
    testStudentId: str = Field(default="", max_length=64)


@router.post("/announcements/notify")
async def notify_announcement(payload: AnnouncementNotifyBody, _mentor=Depends(require_mentor)):
    """Push a just-published announcement to the targeted students' devices.

    Independent of the behavior-notification caps: mentor broadcasts are
    official comms, not behavior nudges. Audience matches the announcement row —
    "All Batches" reaches every student with a registered device, a batch name
    narrows it to that batch. Best-effort: the announcement is already published
    in-app either way, so a failed send never blocks the mentor.
    """
    title = payload.title.strip()
    text = payload.body.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Announcement title is required.")
    audience = (payload.audience or "").strip()
    batch = "" if audience.lower() in ("", "all batches", "all") else audience
    tag = "ann-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    title_text = "\U0001f4e3 New announcement: " + title
    body_text = (text or "Open the app to read the full announcement.")[:180]
    test_sid = normalize_student_id(payload.testStudentId or "")
    if test_sid:
        sent = await push_service.push_to_student(
            test_sid, title_text, body_text, link="home", tag=tag
        )
        return {"ok": True, "sent": sent, "audience": f"test:{test_sid}"}
    sent = await push_service.push_to_all(
        title_text,
        body_text,
        link="home",
        tag=tag,
        batch=batch,
    )
    return {"ok": True, "sent": sent, "audience": audience or "All Batches"}


class RemoveStudentBody(BaseModel):
    confirm: str = ""


@router.post("/students/{student_id}/remove")
async def remove_student(
    student_id: str,
    body: RemoveStudentBody,
    mentor=Depends(require_mentor),
):
    """Soft-remove a student from the program (owner flow: non-studious students
    are removed). Blocks app login and drops the student from tracker views,
    leaderboards and pushes. Data is kept so a Restore brings everything back."""
    sid = normalize_student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="A valid student ID is required.")
    if body.confirm.strip() and body.confirm.strip().upper() != sid:
        raise HTTPException(status_code=400, detail="Confirmation does not match the student ID.")
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found.")
    now = _now()
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {"$set": {"status": "removed", "removedAt": now, "removedBy": mentor.get("sub") or "mentor", "updatedAt": now}},
    )
    return {"ok": True, "studentId": sid, "status": "removed"}


@router.post("/students/{student_id}/restore")
async def restore_student(student_id: str, mentor=Depends(require_mentor)):
    """Undo a soft-remove: the student returns with all data intact."""
    sid = normalize_student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="A valid student ID is required.")
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found.")
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": {"status": "Active", "updatedAt": _now()},
            "$unset": {"removedAt": "", "removedBy": ""},
        },
    )
    return {"ok": True, "studentId": sid, "status": "Active"}


@router.get("/students/removed")
async def list_removed_students(_mentor=Depends(require_mentor)):
    """Removed students so the mentor can review or restore them."""
    db = get_db()
    rows = await db[STUDENT_ACCOUNTS].find(
        {"$or": [{"status": "removed"}, {"removedAt": {"$exists": True}}]},
        {"_id": 0, "studentId": 1, "studentName": 1, "batch": 1, "group": 1, "removedAt": 1},
    ).to_list(length=2000)
    return JSONResponse({"removed": rows}, headers={"Cache-Control": "no-store"})


def _col_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


async def _mirror_access_to_sheet(sid: str, enabled: bool, reason: str) -> bool:
    """Best-effort mirror of the access toggle into the authoritative Students
    sheet (Access / AccessReason / AccessUpdatedAt columns — the same schema the
    mentor's original access tool used). First tries the protected student-admin
    script; then the Sheets API with the mounted Drive service account. Failure
    here never blocks the Mongo-side enforcement."""
    label = "ON" if enabled else "OFF"
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    url = (getattr(settings, "student_admin_script_url", "") or "").strip()
    key = (getattr(settings, "student_import_key", "") or "").strip()
    if url and key:
        # The old access writer lived behind this protected script. Its action
        # name is gone with that UI, so try the likely names in order — the
        # payload shape matches the known mentorChangeBatch envelope.
        for action_name in ("mentorSetAccess", "setAccess", "mentorSetStudentAccess"):
            try:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    response = await client.post(
                        url,
                        json={
                            "action": action_name,
                            "payload": {
                                "studentId": sid,
                                "access": label,
                                "reason": reason,
                                "adminKey": key,
                            },
                        },
                    )
                envelope = response.json()
                result = envelope.get("result") if isinstance(envelope, dict) else None
                if isinstance(result, dict) and result.get("success"):
                    return True
            except Exception:
                continue

    try:
        from routers.notes_inbox import _google_token

        token = _google_token()
    except Exception:
        return False
    try:
        read_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{TRACKER_SHEET_ID}"
            f"/values/Students!A1:Q2000"
        )
        resp = await asyncio.to_thread(
            requests.get, read_url, headers={"Authorization": f"Bearer {token}"}, timeout=20
        )
        if resp.status_code >= 400:
            return False
        values = resp.json().get("values") or []
        if not values:
            return False
        header = [str(c or "").strip().lower() for c in values[0]]

        def _col(name: str):
            return header.index(name) + 1 if name in header else None

        c_access = _col("access")
        c_reason = _col("accessreason")
        c_at = _col("accessupdatedat")
        if not c_access:
            return False
        row_idx = None
        for i, row in enumerate(values[1:], start=2):
            if str((row[0] if row else "") or "").strip().upper() == sid:
                row_idx = i
                break
        if not row_idx:
            return False
        cells = [(c_access, label), (c_at, stamp)]
        if c_reason:
            cells.append((c_reason, reason if not enabled else ""))
        ok = True
        for col_idx, value in cells:
            put_url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{TRACKER_SHEET_ID}"
                f"/values/Students!{_col_letter(col_idx)}{row_idx}?valueInputOption=USER_ENTERED"
            )
            put = await asyncio.to_thread(
                requests.put,
                put_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                data=json.dumps({"values": [[value]]}),
                timeout=20,
            )
            if put.status_code >= 400:
                ok = False
        return ok
    except Exception:
        return False


class StudentAccessBody(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=300)


@router.post("/students/{student_id}/access")
async def set_student_access(
    student_id: str,
    body: StudentAccessBody,
    mentor=Depends(require_mentor),
):
    """Mentor-controlled access ON/OFF (owner flow: block students who stop
    studying, with a visible reason; turning access back on restores them).

    Writes Mongo (the app login layer enforces) and best-effort mirrors the
    Students sheet's Access columns so the legacy sheet-based login layer and
    the sheet itself stay in sync."""
    sid = normalize_student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="A valid student ID is required.")
    reason = (body.reason or "").strip()
    if not body.enabled and not reason:
        raise HTTPException(status_code=400, detail="A reason is required when turning access off.")
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid},
        {"_id": 0, "accessEnabled": 1, "accessUpdatedAt": 1,
         "studentName": 1, "batch": 1, "group": 1, "attempt": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found.")
    now = _now()
    # `accessEnabled` is absent for every account created before this switch existed,
    # and absent means ON - so the first OFF is a real change, a repeat ON is not.
    prev_off = doc.get("accessEnabled") is False
    now_off = not bool(body.enabled)
    changed = prev_off != now_off
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": {
                "accessEnabled": bool(body.enabled),
                "accessReason": "" if body.enabled else reason,
                "accessUpdatedAt": now,
                "accessUpdatedBy": mentor.get("sub") or "mentor",
                "updatedAt": now,
            }
        },
    )
    sheet_synced = await _mirror_access_to_sheet(sid, bool(body.enabled), reason)

    notice_sent = 0
    if changed:
        # The lockout timeline is what makes a student's makeup time computable at
        # all, so it is written even if the notice below fails. The toggle never
        # depends on either one.
        await access_lib.log_access_event(
            db, sid, bool(body.enabled), reason="" if body.enabled else reason,
            by=mentor.get("sub") or "mentor", at=now,
        )
        if not now_off:
            # "Access on karte hi unhe dikhna chahiye": tell them what they missed,
            # because they will not have seen any of the pushes sent while locked out.
            try:
                account = dict(doc)
                account["studentId"] = sid
                counts = await access_lib.pending_after_restore(db, account, doc.get("accessUpdatedAt"))
                title, text = access_lib.restore_message(counts)
                # awaited, not spawned: one student's device list is a couple of
                # requests, and the mentor's toggle response can then say honestly
                # whether the "you missed this" notice went out.
                notice_sent = await push_service.push_to_student(
                    sid, title, text, link="tests", tag="access-restored",
                )
            except Exception as exc:  # noqa: BLE001 - best effort by design
                logger.warning("access restore notice for %s failed: %s", sid, exc)
                notice_sent = 0

    return {
        "ok": True,
        "studentId": sid,
        "accessEnabled": bool(body.enabled),
        "reason": "" if body.enabled else reason,
        "sheetSynced": sheet_synced,
        "accessChanged": changed,
        "restoreNoticeSent": notice_sent,
    }


def _slug_avatar(name: str, sid: str) -> str:
    """Inline SVG avatar so the profile never renders a broken image."""
    initials = "".join(part[0] for part in str(name or sid or "S").split()[:2]).upper() or "S"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">'
        '<rect width="96" height="96" rx="20" fill="#DBEAFE"/>'
        '<text x="50%" y="54%" font-family="Arial,Helvetica,sans-serif" font-size="38" '
        'font-weight="700" fill="#2563EB" text-anchor="middle" dominant-baseline="middle">'
        + initials +
        "</text></svg>"
    )
    return "data:image/svg+xml;utf8," + svg.replace("#", "%23").replace('"', "'")


def _log_days(study_log: list) -> dict:
    """date-string -> total hours, from the dashboard's study log entries."""
    days: dict[str, float] = {}
    for entry in study_log or []:
        day = str((entry or {}).get("date") or "")[:10]
        if not day:
            continue
        try:
            hours = float((entry or {}).get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        days[day] = days.get(day, 0.0) + hours
    return days


@router.get("/students/directory")
async def mentor_student_directory(_mentor=Depends(require_mentor)):
    """Students page + tracker links — Mongo is the source of truth.

    Before this endpoint the list came through the legacy Apps Script bridge.
    The mentor build has no Apps Script URL configured, so that bridge served
    mock rows: a real student clicked in the Daily Tracker opened
    "Student not found" because their ID only exists in Mongo.
    """
    db = get_db()
    accounts = await db[STUDENT_ACCOUNTS].find(
        {},
        {"_id": 0, "studentId": 1, "studentName": 1, "email": 1, "phone": 1,
         "address": 1, "batch": 1, "group": 1, "attempt": 1, "caLevel": 1,
         "joinedOn": 1, "master": 1, "status": 1, "removedAt": 1,
         "accessEnabled": 1, "accessReason": 1},
    ).to_list(length=5000)
    stats_by_id: dict[str, dict] = {}
    async for doc in db[DASHBOARD_STUDENTS].find({}, {"_id": 0, "studentId": 1, "stats": 1}):
        stats_by_id[str(doc.get("studentId") or "").upper()] = doc.get("stats") or {}

    students = []
    batch_options, group_options, attempt_options = set(), set(), set()
    for acc in accounts:
        sid = str(acc.get("studentId") or "").strip().upper()
        if not sid:
            continue
        stats = stats_by_id.get(sid, {})
        if acc.get("batch"):
            batch_options.add(acc["batch"])
        if acc.get("group"):
            group_options.add(acc["group"])
        if acc.get("attempt"):
            attempt_options.add(acc["attempt"])
        removed = bool(acc.get("removedAt")) or str(acc.get("status") or "").lower() == "removed"
        students.append({
            "id": sid,
            "studentId": sid,
            "name": acc.get("studentName") or sid,
            "email": acc.get("email") or "",
            "phone": acc.get("phone") or "",
            "city": acc.get("address") or "",
            "batch": acc.get("batch") or "",
            "group": acc.get("group") or "",
            "attempt": acc.get("attempt") or "",
            "level": acc.get("caLevel") or "",
            "joinedOn": str(acc.get("joinedOn") or "")[:10],
            "master": bool(acc.get("master")),
            "status": "Removed" if removed else "Active",
            "risk": "Low" if (stats.get("weeklyHours") or 0) > 0 else "High",
            "accessEnabled": acc.get("accessEnabled") is not False,
            "accessReason": acc.get("accessReason") or "",
            "attendance": 0,
            "studyHours": float(stats.get("averageHours") or 0),
            "submissionRate": 0,
            "lastSubmission": stats.get("lastSubmission"),
        })
    students.sort(key=lambda row: row["id"])
    return {
        "students": students,
        "options": {
            "batchOptions": ["All Batches", *sorted(batch_options)],
            "groupOptions": ["All Groups", *sorted(group_options)],
            "attemptOptions": ["All Attempts", *sorted(attempt_options)],
            "statusOptions": ["All Status", "Active", "Removed"],
        },
        "source": "mongo",
        "generatedAt": _now(),
    }


@router.get("/students/{student_id}/profile")
async def mentor_student_profile(student_id: str, _mentor=Depends(require_mentor)):
    """One student's profile for the mentor dashboard, straight from Mongo.

    Shapes match what StudentProfile.jsx renders (weekly/monthly/tracker arrays,
    mentor notes) so the page no longer depends on the legacy sheet bridge.
    """
    sid = normalize_student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="A valid student ID is required.")
    db = get_db()
    acc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not acc:
        raise HTTPException(status_code=404, detail="Student not found.")
    dash = await db[DASHBOARD_STUDENTS].find_one({"studentId": sid}) or {}
    stats = dash.get("stats") or {}
    study_log = dash.get("studyLog") or []
    days = _log_days(study_log)
    today = datetime.now(IST).date()

    window = [today - timedelta(days=offset) for offset in range(29, -1, -1)]
    logged_30 = sum(1 for day in window if day.isoformat() in days)
    attendance = round(logged_30 / 30 * 100)
    last7 = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    logged_7 = sum(1 for day in last7 if day.isoformat() in days)
    submission_rate = round(logged_7 / 7 * 100)

    weekly = [
        {"day": day.strftime("%a"), "hours": round(days.get(day.isoformat(), 0.0), 2)}
        for day in last7
    ]
    monthly = []
    for report in (dash.get("reports") or [])[-6:]:
        week_label = str((report or {}).get("weekOf") or "")
        hours = float((report or {}).get("weeklyHours") or 0)
        monthly.append({
            "week": week_label,
            "hours": round(hours, 2),
            "attendance": min(100, round(hours / 7 / 8 * 100)) if hours else 0,
        })
    tracker = [
        {
            "date": day.isoformat(),
            "hours": round(days.get(day.isoformat(), 0.0), 2),
            "submitted": day.isoformat() in days,
        }
        for day in [today - timedelta(days=offset) for offset in range(4, -1, -1)]
    ]
    removed = bool(acc.get("removedAt")) or str(acc.get("status") or "").lower() == "removed"
    name = acc.get("studentName") or sid
    return {
        "id": sid,
        "studentId": sid,
        "name": name,
        "avatar": _slug_avatar(name, sid),
        "email": acc.get("email") or "",
        "phone": acc.get("phone") or "",
        "city": acc.get("address") or "",
        "joinedOn": str(acc.get("joinedOn") or "")[:10],
        "batch": acc.get("batch") or "",
        "group": acc.get("group") or "",
        "attempt": acc.get("attempt") or "",
        "level": acc.get("caLevel") or "",
        "status": "Removed" if removed else "Active",
        "risk": "Low" if (stats.get("weeklyHours") or 0) > 0 else "High",
        "attendance": attendance,
        "studyHours": float(stats.get("averageHours") or 0),
        "submissionRate": submission_rate,
        "totalHours": float(stats.get("totalHours") or 0),
        "streak": int(stats.get("streak") or 0),
        "lastSubmission": stats.get("lastSubmission"),
        "accessEnabled": acc.get("accessEnabled") is not False,
        "accessReason": acc.get("accessReason") or "",
        "weekly": weekly,
        "monthly": monthly,
        "tracker": tracker,
        "mentorNotes": [
            {"id": note.get("id") or "", "date": str(note.get("date") or "")[:10], "note": note.get("note") or ""}
            for note in (dash.get("mentorNotes") or [])
        ],
        "feedback": dash.get("feedback") or [],
        "source": "mongo",
    }


class MentorNoteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    note: str = ""


@router.post("/students/{student_id}/note")
async def add_mentor_note_mentor(student_id: str, body: MentorNoteBody, mentor=Depends(require_mentor)):
    """Append a mentor note to the student's Mongo dashboard document."""
    sid = normalize_student_id(student_id)
    note = (body.note or "").strip()
    if not sid or not note:
        raise HTTPException(status_code=400, detail="A student ID and a note are required.")
    db = get_db()
    if not await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Student not found.")
    entry = {
        "id": f"NOTE-{uuid.uuid4().hex[:8]}",
        "date": datetime.now(IST).date().isoformat(),
        "note": note,
        "by": mentor.get("sub") or "mentor",
        "at": _now(),
    }
    await db[DASHBOARD_STUDENTS].update_one(
        {"studentId": sid},
        {"$push": {"mentorNotes": {"$each": [entry], "$position": 0}}, "$set": {"updatedAt": _now()}},
        upsert=True,
    )
    return {"ok": True, "studentId": sid, "note": entry}


@router.get("/students/{student_id}/admin-state")
async def student_admin_state(student_id: str, _mentor=Depends(require_mentor)):
    """Admin card data for the student profile: access + removal state."""
    sid = normalize_student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="A valid student ID is required.")
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid},
        {
            "_id": 0,
            "studentId": 1,
            "studentName": 1,
            "batch": 1,
            "group": 1,
            "joinedOn": 1,
            "status": 1,
            "removedAt": 1,
            "removedBy": 1,
            "accessEnabled": 1,
            "accessReason": 1,
            "accessUpdatedAt": 1,
            "accessUpdatedBy": 1,
        },
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found.")
    removed = bool(doc.get("removedAt")) or str(doc.get("status") or "").strip().lower() == "removed"
    return JSONResponse(
        {
            "studentId": doc.get("studentId"),
            "studentName": doc.get("studentName") or "",
            "batch": doc.get("batch") or "",
            "group": doc.get("group") or "",
            "joinedOn": doc.get("joinedOn") or "",
            "removed": removed,
            "removedAt": doc.get("removedAt") or "",
            "accessEnabled": doc.get("accessEnabled") is not False,
            "accessReason": doc.get("accessReason") or "",
            "accessUpdatedAt": doc.get("accessUpdatedAt") or "",
            "accessUpdatedBy": doc.get("accessUpdatedBy") or "",
        },
        headers={"Cache-Control": "no-store"},
    )


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


def _note_merge_key(row) -> str:
    """Identity of "the same note row" for the sheet->Mongo merge.

    Same PDF published to two batches is TWO notes (one row per batch), so the
    batch (audience) and group must stay part of the key. Falls back to the id
    when there is no fileId (hand-uploaded rows).
    """
    if not isinstance(row, dict):
        return ""
    file_id = str(row.get("fileId") or "").strip()
    if not file_id:
        return "id:" + str(row.get("id") or "").strip()
    return "|".join(
        [
            file_id,
            str(row.get("audience") or "").strip().lower(),
            str(row.get("group") or "").strip().lower(),
        ]
    )


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
    # An empty/malformed Sheet response also retains Mongo accounts in the
    # merger. Report that fallback honestly instead of claiming Sheet truth.
    if not sheet_rows:
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
        and not _is_removed(account)
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
    """Jan 2027 cohort, master and removed accounts excluded. Same rule as the tracker."""
    return [
        account for account in accounts
        if not account.get("master")
        and not _is_removed(account)
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
    verified_mcq = await _verified_daily_days(db)

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
            verified_mcq_by_date=verified_mcq.get(sid, {}),
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


def _activity_streak(activity, today: date) -> int:
    """Consecutive days with a submitted tracker row, ending today or yesterday.

    Computed live from the activity so a student who stops submitting sees their
    streak decay instead of freezing at whatever their last write left behind.
    """
    days = getattr(activity, "submitted_dates", None) or set()
    if not days:
        return 0
    day = today if today in days else today - timedelta(days=1)
    if day not in days:
        return 0
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


def _week_dates(today: date) -> tuple[str, str]:
    """Current calendar week as display dates: Sunday..Saturday (ISO).

    Anchored in week_window so the board, the Reports tab and the mentor's export
    cannot drift to different weeks.
    """
    start = week_start_of(today)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def _display_fields(activities: list, today: date, streaks: dict) -> dict:
    """Weekly/total hours per student, for the columns the clients always show."""
    weekly = ranking_lib.period_window("weekly", today, TRACKER_HISTORY_FLOOR)
    overall = ranking_lib.period_window("overall", today, TRACKER_HISTORY_FLOOR)
    display = {}
    for activity in activities:
        weekly_row = ranking_lib.score_student(activity, *weekly, "weekly", TRACKER_HISTORY_FLOOR)
        overall_row = ranking_lib.score_student(activity, *overall, "overall", TRACKER_HISTORY_FLOOR)
        streak = _activity_streak(activity, today)
        if weekly_row.is_active:
            # Active students keep the larger of the two: the activity-based count
            # misses legacy Google-Form-only days, and their own writes keep the
            # stored streak fresh anyway. Inactive students fall to the computed
            # value so a stale streak cannot linger forever on the board.
            streak = max(streak, int(streaks.get(activity.student_id) or 0))
        display[activity.student_id] = {
            "weeklyHours": weekly_row.hours,
            "totalHours": overall_row.hours,
            "streak": streak,
            "active": weekly_row.is_active,
        }
    return display


TRACKER_CONFIG = "tracker_config"
# Batch 2 coaching began 5 Oct 2026 (owner-confirmed). Other batches stay unset
# until the mentor configures them; per-student joinedOn/override still applies.
DEFAULT_BATCH_STARTS = {"Before Result Batch 2": "2026-10-05"}


async def backfill_missing_joined_on(db=None) -> dict:
    """Fill missing joinedOn so recent joiners don't inherit the batch start.

    The Students sheet has no join-date column, so joinedOn lives only in Mongo
    and older imports left it blank. Evidence, in order of reliability:
    * the account's createdAt (IST day the student was added to the app), and
    * any tracker activity that predates it (bulk-imported rosters keep their
      first activity day visible).
    The +1-day tracker rule then starts the student the day after the derived
    join date. Idempotent: only accounts with an empty/missing joinedOn change.
    """
    db = db or get_db()
    rows = await db[STUDENT_ACCOUNTS].find(
        {}, {"_id": 0, "studentId": 1, "createdAt": 1, "joinedOn": 1}
    ).to_list(length=5000)
    blank = [a for a in rows if not str(a.get("joinedOn") or "").strip()]
    if not blank:
        return {"fixed": 0, "candidates": 0}

    first_activity: dict[str, date] = {}

    def _note(sid, day):
        if sid and day and (sid not in first_activity or day < first_activity[sid]):
            first_activity[sid] = day

    async for doc in db[DASHBOARD_STUDENTS].find({}, {"studentId": 1, "studyLog": 1}):
        sid = normalize_student_id(doc.get("studentId") or "")
        for row in doc.get("studyLog") or []:
            if isinstance(row, dict):
                _note(sid, _parse_tracker_day(row.get("date") or ""))
    try:
        form_rows = await asyncio.to_thread(_fetch_tracker_submissions_sync)
    except Exception:
        form_rows = []
    for row in form_rows:
        _note(normalize_student_id(row.get("studentId") or ""), row.get("date"))

    fixed = 0
    today = datetime.now(IST).date()
    for account in blank:
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        created = account.get("createdAt")
        created_day = None
        if isinstance(created, datetime):
            stamp = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            created_day = stamp.astimezone(IST).date()
        elif created:
            created_day = _parse_tracker_day(created)
        if created_day and created_day > today:
            created_day = today
        activity = first_activity.get(sid)
        if activity and created_day and activity < created_day:
            # Bulk-import artifact: they were active before this account row
            # existed. The +1 rule skips the join day, so derive the join day as
            # the day before their first activity to keep that day visible.
            joined = activity - timedelta(days=1)
        elif created_day:
            joined = created_day
        else:
            continue
        await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid},
            {"$set": {"joinedOn": joined.isoformat()}},
        )
        fixed += 1
    return {"fixed": fixed, "candidates": len(blank)}


async def _tracker_start_config(db, create_if_missing: bool = True) -> dict:
    """Read (and lazily create) the tracker start-date configuration."""
    cfg = await db[TRACKER_CONFIG].find_one({"_id": "config"})
    if not cfg:
        cfg = {"_id": "config", "batchStarts": dict(DEFAULT_BATCH_STARTS), "overrides": {}}
        if create_if_missing:
            await db[TRACKER_CONFIG].update_one({"_id": "config"}, {"$set": cfg}, upsert=True)
    return {
        "batchStarts": cfg.get("batchStarts") or {},
        "overrides": cfg.get("overrides") or {},
    }


def _effective_tracker_start(account: dict, cfg: dict) -> tuple:
    """Per-student tracker start = manual override > max(joinedOn + 1, batch start).

    Owner rule (2026-10-13): the day a student joins is never tracked — their
    tracker shows from the NEXT day. Students who were already in the cohort
    when their batch started always begin on the batch start day, so a joining
    date earlier than the batch start never pulls the grid forward.

    Returns (start_date|None, source|None) where source is one of
    "override" / "joined" / "batch".
    """
    sid = normalize_student_id(account.get("studentId") or "")
    override = _parse_tracker_day((cfg.get("overrides") or {}).get(sid) or "")
    if override:
        return override, "override"
    joined = _parse_tracker_day(account.get("joinedOn") or "")
    batch = str(account.get("batch") or "").strip()
    batch_start = _parse_tracker_day((cfg.get("batchStarts") or {}).get(batch) or "")
    joined_start = joined + timedelta(days=1) if joined else None
    candidates = [day for day in (joined_start, batch_start) if day]
    if not candidates:
        return None, None
    start = max(candidates)
    from_join = bool(joined_start) and (not batch_start or joined_start > batch_start)
    return start, ("joined" if from_join else "batch")


def _build_missed_tracker_report(
    accounts: list[dict],
    submissions: list[dict],
    from_day: date,
    to_day: date,
    use_submission_start_for_missing_joined: bool = False,
    cfg: dict | None = None,
    attendance: dict | None = None,
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
        # Access-off students are skipped: they cannot log in or submit, so
        # keeping them here showed "missed" every day (owner, 14 Oct 2026).
        if account.get("master") or _is_removed(account) or _access_blocked(account) or _attempt_ym(account.get("attempt") or "", account.get("batch") or "") != (2027, 1):
            continue
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        roster_count += 1
        joined = _parse_tracker_day(account.get("joinedOn") or "")
        effective_start, start_source = _effective_tracker_start(account, cfg or {})
        if effective_start:
            # A student is never expected before their own start date, which is
            # the later of their joining date and their batch's start date
            # (or a manual mentor override).
            expected_from = max(from_day, effective_start)
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
        # Leave / absent days are excluded from "missed" but still listed, so the
        # mentor sees a reason instead of an unexplained gap.
        leave_dates = [
            day
            for day in expected_dates
            if day not in submitted
            and str((attendance or {}).get((sid, day), {}).get("kind") or "") == "leave"
        ]
        absent_dates = [
            day
            for day in expected_dates
            if day not in submitted
            and str((attendance or {}).get((sid, day), {}).get("kind") or "") == "absent"
        ]
        excused_dates = set(leave_dates) | set(absent_dates)
        missed_dates = [
            day for day in expected_dates if day not in submitted and day not in excused_dates
        ]
        items.append({
            "studentId": sid,
            "studentName": str(account.get("studentName") or sid).strip() or sid,
            # Access state per row so the batch/date grid can flip it inline.
            "accessEnabled": account.get("accessEnabled") is not False,
            "accessReason": account.get("accessReason") or "",
            "group": str(account.get("group") or "Unassigned").strip() or "Unassigned",
            "batch": str(account.get("batch") or "Unassigned").strip() or "Unassigned",
            "joinedOn": joined.isoformat() if joined else None,
            "effectiveStart": effective_start.isoformat() if effective_start else None,
            "startSource": start_source,
            "expectedFrom": expected_from.isoformat(),
            "expectedDays": len(expected_dates),
            "submittedDays": len(submitted_dates),
            "missedDays": len(missed_dates),
            "submittedDates": [day.isoformat() for day in submitted_dates],
            "missedDates": [day.isoformat() for day in missed_dates],
            "leaveDays": len(leave_dates),
            "absentDays": len(absent_dates),
            "leaveDates": [day.isoformat() for day in leave_dates],
            "absentDates": [day.isoformat() for day in absent_dates],
            # Per-day detail (kind + reason + record id) so the tracker grid can
            # show "A"/"L" with a reason tooltip and cancel straight from a cell.
            "excuseDetails": [
                {
                    "date": day.isoformat(),
                    "kind": str((attendance or {}).get((sid, day), {}).get("kind") or ""),
                    "reason": str((attendance or {}).get((sid, day), {}).get("reason") or ""),
                    "recordId": str((attendance or {}).get((sid, day), {}).get("recordId") or ""),
                }
                for day in sorted(excused_dates)
            ],
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


def _tracker_day_entry(
    form_rows: list[dict],
    mongo_rows: list[dict],
    selected: date,
    attendance: dict | None = None,
) -> dict:
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
    # present > leave/absent (a submitted log always wins) > missed.
    kind = str((attendance or {}).get("kind") or "")
    if submitted:
        status = "present"
    elif kind in {"leave", "absent"}:
        status = kind
    else:
        status = "missed"
    return {
        "date": selected.isoformat(),
        "submitted": submitted,
        "status": status,
        "excused": status in {"leave", "absent"},
        "attendanceReason": str((attendance or {}).get("reason") or ""),
        "attendanceId": str((attendance or {}).get("recordId") or ""),
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
    if segment not in ranking_lib.SEGMENT_MODES:
        raise HTTPException(status_code=400, detail="segment must be batch, group or batch_group")

    db = get_db()
    if refresh:
        # Push corrected ranks into the stored leaderboard and each student's
        # stats straight away, so installed app clients are fixed without waiting
        # for the next student submission to trigger a rebuild. Mongo-only.
        await _rebuild_leaderboard(db)
    accounts = [account async for account in db[STUDENT_ACCOUNTS].find({}) if not _is_removed(account)]
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
        # same key the ranking uses, so a member list and its board can never disagree
        members_by_key.setdefault(ranking_lib.segment_key(activity, segment), []).append(activity)

    overall_pos = _global_positions(_ranked_segments(activities, "overall", segment, today))
    weekly_pos = _global_positions(_ranked_segments(activities, "weekly", segment, today))
    week_start, week_end = _week_dates(today)

    for key, rankings in segments.items():
        members = members_by_key.get(key) or []
        coverage = ranking_lib.mcq_coverage(members, start, end, TRACKER_HISTORY_FLOOR)
        entries = []
        for r in rankings:
            entry = _ranking_row(r, display.get(r.student_id) or {})
            entry["rankOverall"] = int(overall_pos.get(r.student_id) or 0)
            entry["rankWeekly"] = int(weekly_pos.get(r.student_id) or 0)
            entry["weekStart"] = week_start
            entry["weekEnd"] = week_end
            entries.append(entry)
        payload.append({
            "key": key,
            "label": key,
            "studentCount": len(rankings),
            "mcqUsed": ranking_lib.mcq_enabled(members, start, end, TRACKER_HISTORY_FLOOR),
            "mcqCoverage": round(coverage, 3),
            "mcqPolicy": ranking_lib.mcq_policy_metadata(start, end)["mcqPolicy"],
            "effectiveWeights": dict(zip(
                ("hours", "mcq", "attendance"),
                ranking_lib.weights(ranking_lib.mcq_enabled(members, start, end, TRACKER_HISTORY_FLOOR)),
            )),
            "entries": entries,
        })

    return JSONResponse(
        {
            "period": period,
            "segment": segment,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "weekStart": week_start,
            "weekEnd": week_end,
            "historyFloor": TRACKER_HISTORY_FLOOR.isoformat(),
            "generatedAt": _now(),
            "source": {"roster": roster_source, "scoring": "mongo", **sources},
            "weights": {
                "hours": ranking_lib.W_HOURS,
                "mcq": ranking_lib.W_MCQ,
                "attendance": ranking_lib.W_ATTENDANCE,
                **ranking_lib.mcq_policy_metadata(start, end),
            },
            "segments": payload,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/leaderboard/weekly-tops")
async def mentor_weekly_tops(
    weeks: int = Query(6, ge=1, le=13),
    segment: str = Query("batch"),
    batch: Optional[str] = Query(None),
    group: Optional[str] = Query(None),
    _mentor=Depends(require_mentor),
):
    """Per-week Top 3 history (weekly composite), newest week first.

    Answers "kis week kaun top 3 tha" for the mentor dashboard: one entry per
    calendar week (Sun..Sat, see week_window) with the podium, so week-over-week
    movement is visible without switching period tabs. With segment=batch_group each
    week also carries `boards`: one podium per batch x group, which is how the weekly
    chocolates are decided.
    """
    segment = (segment or "batch").strip().lower()
    if segment not in ranking_lib.SEGMENT_MODES:
        raise HTTPException(status_code=400, detail="segment must be batch, group or batch_group")
    db = get_db()
    accounts = [account async for account in db[STUDENT_ACCOUNTS].find({}) if not _is_removed(account)]
    roster, roster_source = await _tracker_roster(accounts)
    activities, _ = await _ranking_activities(db, roster, include_sheets=True)

    def keep(activity) -> bool:
        if batch and activity.batch != batch:
            return False
        if group and activity.group != group:
            return False
        return True

    activities = [a for a in activities if keep(a)]
    today = datetime.now(IST).date()
    # Sunday opens the week (week_window), so the week that just closed is already a
    # finished entry at i=1 by the time this is read on Monday morning.
    anchor = week_start_of(today)
    out = []
    for i in range(weeks):
        start = anchor - timedelta(days=7 * i)
        end = min(start + timedelta(days=6), today)
        segs = ranking_lib.rank_segments(activities, start, end, "weekly", segment, TRACKER_HISTORY_FLOOR)
        merged = [r for rows in segs.values() for r in rows if not r.not_ranked_reason and r.rank > 0]
        merged.sort(key=ranking_lib.sort_key)
        top3 = [
            {
                "studentId": r.student_id,
                "studentName": r.name,
                "place": place,
                "hours": round(float(r.hours), 1),
                "score": round(float(r.score), 1),
                "batch": r.batch,
                "group": r.group,
            }
            for place, r in enumerate(merged[:3], start=1)
        ]
        entry = {
            "weekStart": start.isoformat(),
            "weekEnd": end.isoformat(),
            "isCurrent": i == 0,
            "studentCount": sum(len(rows) for rows in segs.values()),
            "top3": top3,
        }
        if segment == "batch_group":
            # One podium per batch x group board. The whole-audience podium above stays,
            # but the chocolate list is per group, and a student the sheet cannot place
            # is shown as a board of its own instead of being ranked inside a group.
            per_board = []
            for key, rows in segs.items():
                live = [r for r in rows if not r.not_ranked_reason and r.rank > 0]
                per_board.append({
                    "key": key,
                    "label": key,
                    "batch": key.split(" · ")[0],
                    "group": key.split(" · ")[1] if " · " in key else "",
                    "podiumEligible": "(no group set)" not in key,
                    "studentCount": len(rows),
                    "top3": [
                        {
                            "studentId": r.student_id,
                            "studentName": r.name,
                            "place": place,
                            "hours": round(float(r.hours), 1),
                            "score": round(float(r.score), 1),
                        }
                        for place, r in enumerate(live[:3], start=1)
                    ],
                })
            per_board.sort(key=lambda b: (not b["podiumEligible"], b["key"]))
            entry["boards"] = per_board
        out.append(entry)
    return JSONResponse(
        {
            "weeks": out,
            "segment": segment,
            "generatedAt": _now(),
            "source": roster_source,
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
    cfg = await _tracker_start_config(db)
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
            "status": 1,
            "removedAt": 1,
            "accessEnabled": 1,
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
    attendance_map = await attendance_lib.attendance_index(db, selected, selected)

    requested_batch = str(batch or "All Batches").strip()
    items = []
    for account in accounts:
        # Access-off students are skipped: they cannot log in or submit, so
        # keeping them here showed "missed" every day (owner, 14 Oct 2026).
        if account.get("master") or _is_removed(account) or _access_blocked(account) or _attempt_ym(account.get("attempt") or "", account.get("batch") or "") != (2027, 1):
            continue
        account_batch = str(account.get("batch") or "Unassigned").strip() or "Unassigned"
        if requested_batch not in {"", "All Batches"} and account_batch != requested_batch:
            continue
        sid = normalize_student_id(account.get("studentId") or "")
        if not sid:
            continue
        name = str(account.get("studentName") or sid).strip() or sid
        effective_start, _start_source = _effective_tracker_start(account, cfg)
        not_expected = bool(effective_start and selected < effective_start)
        items.append({
            "id": sid,
            "name": name,
            "avatar": f"https://ui-avatars.com/api/?background=2563EB&color=fff&size=200&name={sid}",
            "batch": account_batch,
            "group": str(account.get("group") or "Unassigned").strip() or "Unassigned",
            "notExpected": not_expected,
            "effectiveStart": effective_start.isoformat() if effective_start else None,
            # Access state travels with the row so the mentor can flip it right
            # in the day view (absent field means ON - accounts created before
            # the switch existed never stored a value).
            "accessEnabled": account.get("accessEnabled") is not False,
            "accessReason": account.get("accessReason") or "",
            "attendance": attendance_map.get((sid, selected)),
            "entry": _tracker_day_entry(
                form_by_student.get(sid, []),
                mongo_by_student.get(sid, []),
                selected,
                attendance_map.get((sid, selected)),
            ),
        })
    items.sort(
        key=lambda row: (
            row.get("notExpected", False),
            not row["entry"]["submitted"],
            row["name"].lower(),
            row["id"],
        )
    )
    expected_items = [row for row in items if not row.get("notExpected")]
    submitted = sum(1 for row in expected_items if row["entry"]["submitted"])
    on_leave = sum(1 for row in expected_items if row["entry"]["status"] == "leave")
    absent = sum(1 for row in expected_items if row["entry"]["status"] == "absent")
    missed = sum(1 for row in expected_items if row["entry"]["status"] == "missed")
    # Owner decision (14-Oct-2026): on-leave AND self-reported absent days both
    # sit outside the attendance % - they are reported separately instead.
    countable = max(0, len(expected_items) - on_leave - absent)
    return {
        "list": items,
        "submitted": submitted,
        "missed": missed,
        "onLeave": on_leave,
        "absent": absent,
        "excused": on_leave + absent,
        "countable": countable,
        "rate": round((submitted / countable) * 100) if countable else 0,
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
            "status": 1,
            "removedAt": 1,
            "accessEnabled": 1,
        },
    ).to_list(length=2000)
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

    cfg = await _tracker_start_config(db, create_if_missing=False)
    report = _build_missed_tracker_report(
        accounts,
        submissions,
        from_day,
        to_day,
        use_submission_start_for_missing_joined=full_history,
        cfg=cfg,
        attendance=await attendance_lib.attendance_index(db, from_day, to_day),
    )
    report["scope"] = "joined-to-date" if full_history else "range"
    report["source"] = "Form responses 1 + Mongo study logs"
    report["sourceSubmissionRows"] = len(form_submissions)
    report["sourceMongoRows"] = len(mongo_submissions)
    report["rosterSource"] = roster_source
    report["historyFloor"] = min(TRACKER_HISTORY_FLOOR, today).isoformat()
    report["generatedAt"] = _now()
    return JSONResponse(report, headers={"Cache-Control": "no-store"})


class TrackerStartConfigBody(BaseModel):
    batchStarts: dict = {}
    overrides: dict = {}


@router.get("/tracker-start-config")
async def get_tracker_start_config(_mentor=Depends(require_mentor)):
    """Mentor view of batch start dates + per-student tracker start overrides."""
    db = get_db()
    cfg = await _tracker_start_config(db)
    return {"ok": True, "batchStarts": cfg["batchStarts"], "overrides": cfg["overrides"]}


@router.post("/tracker-start-config")
async def set_tracker_start_config(body: TrackerStartConfigBody, _mentor=Depends(require_mentor)):
    """Set/clear batch start dates and per-student overrides (null clears)."""
    db = get_db()
    cfg = await _tracker_start_config(db)
    batch_starts = dict(cfg.get("batchStarts") or {})
    overrides = dict(cfg.get("overrides") or {})
    for key, value in (body.batchStarts or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        if value in (None, ""):
            batch_starts.pop(name, None)
        else:
            parsed = _parse_tracker_day(value)
            if not parsed:
                raise HTTPException(status_code=400, detail=f"Invalid batch start date for {name}.")
            batch_starts[name] = parsed.isoformat()
    for key, value in (body.overrides or {}).items():
        sid = normalize_student_id(key or "")
        if not sid:
            continue
        if value in (None, ""):
            overrides.pop(sid, None)
        else:
            parsed = _parse_tracker_day(value)
            if not parsed:
                raise HTTPException(status_code=400, detail=f"Invalid start date for {sid}.")
            overrides[sid] = parsed.isoformat()
    await db[TRACKER_CONFIG].update_one(
        {"_id": "config"},
        {"$set": {"batchStarts": batch_starts, "overrides": overrides, "updatedAt": _now()}},
        upsert=True,
    )
    return {"ok": True, "batchStarts": batch_starts, "overrides": overrides}


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
    students: list[DashboardStudentItem] = Field(default_factory=list, max_length=2000)


class DashboardGetBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str = ""
    studentId: Optional[str] = None
    payload: Optional[dict] = None


class DashboardWriteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    studentId: Optional[str] = None
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
        key = week_start_of(day).isoformat()
        bucket = buckets.setdefault(key, {"hours": 0.0, "days": set()})
        bucket["hours"] += hours
        bucket["days"].add(day)
    today = datetime.now(IST).date()
    this_week = week_start_of(today).isoformat()
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


RANK_DROP_COOLDOWN_HOURS = 24


async def _notify_rank_drops(db, rows: list, existing: dict) -> None:
    """Push to students who were just overtaken on the leaderboard.

    English, motivating, with a 24h per-student cooldown stored at
    ``stats.lastRankDropPush``. The named overtaker is the student who was
    ranked BELOW the victim before this rebuild and now sits directly ABOVE
    them. Best-effort: a no-op when FCM is not configured, and a rebuild must
    never fail because of it.
    """
    if not push_service.configured():
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cooldown_ms = RANK_DROP_COOLDOWN_HOURS * 3600 * 1000
    for row in rows:
        sid = str(row.get("studentId") or "")
        new_rank = int(row.get("rank") or 0)
        current = existing.get(sid) or {}
        old_rank = int(current.get("rank") or 0)
        if not sid or old_rank <= 0 or new_rank <= old_rank:
            continue  # newcomer, improved, or unchanged
        if now_ms - int(current.get("lastRankDropPush") or 0) < cooldown_ms:
            continue
        overtaker = None
        for other in rows:
            osid = str(other.get("studentId") or "")
            if not osid or osid == sid:
                continue
            o_new = int(other.get("rank") or 0)
            o_old = int((existing.get(osid) or {}).get("rank") or 0)
            # Was behind the victim before, is ahead of the victim now.
            if o_old > old_rank and 0 < o_new < new_rank:
                if overtaker is None or o_new > int(overtaker.get("rank") or 0):
                    overtaker = other
        if overtaker is None:
            continue  # window roll reshuffled ranks; nobody specifically overtook
        name = str(overtaker.get("studentName") or "").strip() or "Another student"
        # Reserve the cooldown BEFORE sending so a failed send can never turn
        # into repeat spam on the next rebuild.
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"stats.lastRankDropPush": now_ms}},
        )
        push_service.spawn(push_service.push_to_student(
            sid,
            f"{name} overtook you on the leaderboard",
            f"You slipped to #{new_rank}. Put in the hours and take your spot back!",
            link="leaderboard",
            tag=f"rank-drop-{sid}",
        ))


async def _rebuild_leaderboard(db) -> None:
    """Recompute the stored leaderboard from live Mongo data.

    Rank is per Batch segment (owner decision), unique, and composite-scored. The
    stored rows keep every key the shipped app/APK reads, so installed clients get
    corrected ranks without a new build.
    """
    accounts = [account async for account in db[STUDENT_ACCOUNTS].find({}) if not _is_removed(account)]
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
    batch_rank = {r.student_id: r.rank for rows in by_batch_weekly.values() for r in rows}
    batch_rank_overall = {r.student_id: r.rank for rows in by_batch.values() for r in rows}
    global_rank = _global_positions(by_batch)
    weekly_rank = _global_positions(by_batch_weekly)
    monthly_rank = _global_positions(by_batch_monthly)

    flat = [r for rows in by_batch_weekly.values() for r in rows]
    flat.sort(key=ranking_lib.sort_key)

    # The stored board is the WEEKLY board (owner decision, 2026-10-13): the card
    # shows this week's hours, so the rank badge and the list order follow the
    # same week. The overall position rides along on every row for clients that
    # show both.
    week_start, week_end = _week_dates(today)

    rows = []
    for ranking in flat:
        row = _ranking_row(ranking, display.get(ranking.student_id) or {})
        sid = ranking.student_id
        row["rank"] = int(weekly_rank.get(sid) or 0)
        row["rankWeekly"] = int(weekly_rank.get(sid) or 0)
        row["rankOverall"] = int(global_rank.get(sid) or 0)
        row["rankInBatch"] = int(batch_rank.get(sid) or 0)
        row["rankOverallInBatch"] = int(batch_rank_overall.get(sid) or 0)
        row["weekStart"] = week_start
        row["weekEnd"] = week_end
        rows.append(row)

    # Push the period ranks onto each student's stats — but only when a value
    # actually changed, so a routinely-refreshing snapshot costs almost no writes.
    existing = {sid: (stats or {}) for sid, stats in student_stats.items()}
    for row in rows:
        sid = row["studentId"]
        target = {
            # `rank` must equal the student's position in the list they are shown,
            # otherwise the tile and the table disagree on the same screen.
            "rank": int(weekly_rank.get(sid) or 0),
            "rankOverall": int(global_rank.get(sid) or 0),
            "weeklyRank": int(weekly_rank.get(sid) or 0),
            "monthlyRank": int(monthly_rank.get(sid) or 0),
            "rankInBatch": int(batch_rank.get(sid) or 0),
            "score": row.get("score"),
            "rankBatch": row.get("batch") or "",
            "streak": int(row.get("streak") or 0),
        }
        current = existing.get(sid) or {}
        if all(current.get(key) == value for key, value in target.items()):
            continue
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {f"stats.{key}": value for key, value in target.items()}},
        )

    # Tell students who were just overtaken (best-effort, cooldown-guarded).
    # `existing` still holds the PRE-rebuild ranks, which is the comparison base.
    # The first rebuild after the rank basis switched to weekly must not compare
    # apples to oranges (old overall ranks vs new weekly ranks) and spam pushes.
    try:
        prior = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}, {"leaderboardMeta": 1}) or {}
        prior_basis = str(((prior.get("leaderboardMeta") or {}).get("rankBasis")) or "")
        if prior_basis == "weekly":
            await _notify_rank_drops(db, rows, existing)
    except Exception:
        pass  # a push failure must never break the leaderboard rebuild

    await db[DASHBOARD_SHARED].update_one(
        {"_id": "shared"},
        {"$set": {
            "leaderboard": rows,
            "leaderboardMeta": {
                "generatedAt": _now(),
                "segment": "batch",
                "rankBasis": "weekly",
                "weekStart": week_start,
                "weekEnd": week_end,
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


def _all_groups(value: str) -> bool:
    """True when a group value means "every group".

    Students sheet stores their group as 'Group 1' / 'Group 2' / 'Both' — the
    string is 'Both', NOT 'Both Groups', so an exact match against the old
    label silently dropped Group 1/Group 2 notes for every Both student.
    """
    v = str(value or "").strip().lower()
    if not v:
        return True
    return (
        "both" in v
        or v == "all"
        or "combined" in v
        or "group 1 and 2" in v
        or "group i and ii" in v
    )


def _group_ok(note_group: str, student_group: str) -> bool:
    """Note visibility by CA group.

    - A note tagged both/all-groups (or untagged) reaches everyone.
    - A student in 'Both' (both groups) studies Group 1 and Group 2 subjects,
      so they see Group 1 and Group 2 notes too.
    - Otherwise the groups must match (case-insensitive).
    """
    if _all_groups(note_group) or _all_groups(student_group):
        return True
    return str(note_group or "").strip().lower() == str(student_group or "").strip().lower()


def _announcements_for_student(rows: list, account: Optional[dict]) -> list:
    """Shared announcements a student may read: their own batch, or "All Batches".

    An announcement published for one batch must not appear in another batch's
    app. The shared reader used to hand every shared row to every student, so a
    batch-targeted announcement leaked across the whole programme.
    """
    if not isinstance(rows, list):
        return []
    if not account:
        return rows
    batch = str(account.get("batch") or "").strip()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        audience = str(row.get("audience") or "All Batches").strip()
        if audience in ("", "All Batches", "All"):
            out.append(row)
            continue
        if batch and audience.lower() == batch.lower():
            out.append(row)
    return out


def _notes_for_student(notes: list, account: Optional[dict]) -> list:
    if not isinstance(notes, list):
        return []
    if not account:
        return notes
    batch = str(account.get("batch") or "")
    group = str(account.get("group") or "")
    # Sept 2026 attempt students (old cohort) see no material at all — the
    # program is open for Jan 2027 attempt onwards (same rule as login gate).
    # Master accounts keep full visibility for mentor testing.
    if not account.get("master") and not _attempt_access_allowed(
        str(account.get("attempt") or ""), batch
    ):
        return []
    out = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        audience = str(note.get("audience") or "All Batches")
        note_group = str(note.get("group") or "Both Groups")
        # "All Batches" means every batch in the programme, but a note can still
        # name batches that must not receive it (e.g. a note published for the four
        # CA batches is not for Super 30). Master accounts keep full visibility.
        excluded = {str(b or "").strip().lower() for b in (note.get("excludeBatches") or [])}
        if not account.get("master") and batch.strip().lower() in excluded:
            continue
        # A note published to several batches is ONE row with a batch list.
        listed = {str(b or "").strip().lower() for b in (note.get("batches") or [])}
        if listed:
            batch_ok = batch.strip().lower() in listed
        else:
            batch_ok = audience in ("", "All Batches") or audience == batch
        group_ok = _group_ok(note_group, group)
        if batch_ok and group_ok:
            out.append(note)
    # Folder-wise (series) + chapter-wise order: subject → series → Ch 1, 2, 3 …
    # App list ko isi order me dikhata hai, isliye series folder ke andar files
    # chapter order me aati hain (upload order me nahi).
    out.sort(key=_note_order_key)
    return out


_SUBJECT_ORDER = ["Accounts", "Law", "DT", "GST", "Costing", "Audit", "FM", "SM"]


def _note_order_key(note: dict):
    subject = str(note.get("subject") or "").strip()
    index = _SUBJECT_ORDER.index(subject) if subject in _SUBJECT_ORDER else len(_SUBJECT_ORDER)
    # App me folder = category (= SERIES: "Super 75"/teacher), aur us folder ke
    # andar notes chapter number se sorted ("Ch 2" → "Ch 10" → "Ch 11"). App
    # list ko isi order me dikhata hai, isliye sort yahan hota hai.
    folder = str(note.get("category") or note.get("series") or "").strip()
    chapter = str(note.get("chapter") or "").strip()
    number_match = re.search(r"\d+", chapter)
    number = int(number_match.group()) if number_match else 999
    return (
        index,
        subject.lower(),
        folder.lower(),
        number,
        str(note.get("title") or "").lower(),
    )


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
        # MERGE, not replace (14 Oct 2026). The Sheet "Notes" tab is only a
        # best-effort mirror of what mentors publish (the web Notes Inbox writes
        # straight to Mongo, and that sheet copy can silently fail). This import
        # runs every 10 minutes from the Apps Script sync; a replace here wiped
        # every Mongo-published note that had not reached the sheet, which is
        # exactly how students ended up with an empty/partial list. Publish wins
        # on (fileId, audience, group); Mongo-only notes are kept.
        incoming = await _visible_materials(db, body.notes)
        shared_doc = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        existing = [
            n for n in (shared_doc.get("notes") or []) if isinstance(n, dict)
        ]
        seen = set()
        merged: list = []
        for note in incoming + existing:
            key = _note_merge_key(note)
            if key in seen:
                continue
            seen.add(key)
            merged.append(note)
        shared_set["notes"] = merged[:400]
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
async def get_dashboard_section(body: DashboardGetBody, principal=Depends(dashboard_student)):
    action = str(body.action or "").strip()
    if action not in READ_ACTIONS:
        deny(403, "Student action denied.")
    payload = own_payload(principal, body.payload, body.studentId)
    student_id = principal["studentId"]
    db = get_db()

    # Access OFF (or removed) blocks every student-facing read — the same
    # behaviour as the mentor's original access tool.
    if student_id:
        account = await db[STUDENT_ACCOUNTS].find_one(
            {"studentId": student_id}, {"_id": 0, "accessEnabled": 1, "removedAt": 1, "status": 1}
        )
        if account and (
            account.get("accessEnabled") is False
            or account.get("removedAt")
            or str(account.get("status") or "").strip().lower() == "removed"
        ):
            deny(403, "Student access unavailable.")

    if action in SHARED_ACTIONS:
        # getLeaderboard carries the rank snapshot, so refresh it automatically
        # before serving. Announcements do not need a rebuild.
        if action == "getLeaderboard":
            shared = await _leaderboard_snapshot(db)
        else:
            shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
        # Workspace/private announcements use the authenticated student reader;
        # never expose them through this legacy ID-only read path.
        if not shared or SHARED_ACTIONS[action] not in shared:
            return {"found": False}
        rows = shared.get(SHARED_ACTIONS[action]) or []
        if action == "getLeaderboard":
            rows = await _leaderboard_for_student(db, rows, student_id)
        elif action == "getAnnouncements":
            rows = await _visible_announcements(db, rows)
            account = await db[STUDENT_ACCOUNTS].find_one(
                {"studentId": student_id}, {"_id": 0, "batch": 1, "group": 1}
            )
            rows = _announcements_for_student(rows, account)
        return {"found": True, "result": rows}

    if action == "notes.listForStudent":
        student_doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id}) if student_id else None
        if student_doc and isinstance(student_doc.get("notes"), list):
            account = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id})
            return {"found": True, "result": _notes_for_student(await _visible_materials(db, student_doc.get("notes") or []), account)}
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
        if not shared or "notes" not in shared:
            return {"found": False}
        account = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id}) if student_id else None
        return {"found": True, "result": _notes_for_student(await _visible_materials(db, shared.get("notes") or []), account)}

    if action == "attendance.status":
        if not student_id:
            return {"found": False}
        try:
            return {"found": True, "result": await attendance_lib.student_status(db, student_id)}
        except HTTPException as exc:
            return {"found": False, "message": str(exc.detail)}

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

    # Student self-reported leave / absent (owner spec 14-Oct-2026). Both are
    # shown in the mentor tracker and are excluded from the attendance %, but
    # the mentor can cancel them from the dashboard (mentor override wins).
    if action in {"attendance.markAbsent", "attendance.requestLeave", "attendance.cancelLeave"}:
        try:
            if action == "attendance.markAbsent":
                out = await attendance_lib.mark_absent(
                    db, payload.get("studentId"), payload.get("date"), payload.get("reason"), "student"
                )
            elif action == "attendance.requestLeave":
                out = await attendance_lib.request_leave(
                    db,
                    payload.get("studentId"),
                    payload.get("from") or payload.get("start"),
                    payload.get("to") or payload.get("end"),
                    payload.get("reason"),
                    "student",
                )
            else:
                out = await attendance_lib.cancel_leave(
                    db, payload.get("studentId"), payload.get("leaveId"), payload.get("date"), actor="student"
                )
        except HTTPException as exc:
            return {"ok": False, "success": False, "message": str(exc.detail)}
        return {"ok": True, "success": True, **out}

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
        push_service.spawn(push_service.push_to_all(
            f"📢 {item.get('title') or 'New announcement'}",
            str(item.get("message") or "")[:180] or "Open the app to read the full announcement.",
            link="home",
            tag=f"ann-{item.get('id')}",
            batch=str(item.get("audience") or ""),
        ))
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
        push_service.spawn(push_service.push_to_all(
            f"📚 New material: {item.get('title') or item.get('subject') or 'Study notes'}",
            str(item.get("description") or "")[:180] or "New study material is waiting in the Material tab.",
            link="notes",
            tag=f"note-{item.get('id')}",
            batch=str(item.get("audience") or ""),
            group=str(item.get("group") or ""),
        ))
        return {"ok": True, "result": item}

    if action == "notes.delete":
        # Apps Script ke sync/mirror se aata hai jab Drive se koi file hatti hai
        # (ya mentor row hataata hai). Pehle ye action support hi nahi tha —
        # isliye Mongo me hataya hua note pada reh jaata tha (BRB2 wala case).
        note_id = str(payload.get("id") or payload.get("noteId") or "").strip()
        file_id = str(payload.get("fileId") or "").strip()
        if not note_id and not file_id:
            return {"ok": False, "message": "Note id missing."}
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        current = list(shared.get("notes") or [])

        def _is_target(n: Any) -> bool:
            if not isinstance(n, dict):
                return False
            if note_id and str(n.get("id") or "") == note_id:
                return True
            if file_id and str(n.get("fileId") or "") == file_id:
                return True
            return False

        kept = [n for n in current if not _is_target(n)]
        removed = len(current) - len(kept)
        if removed:
            await db[DASHBOARD_SHARED].update_one(
                {"_id": "shared"},
                {"$set": {"notes": kept, "updatedAt": now}},
                upsert=True,
            )
        return {"ok": True, "success": True, "removed": removed}

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
        push_service.spawn(push_service.push_to_student(
            sid,
            "📝 New mentor guidance",
            note[:180],
            link="home",
            tag=f"mentor-note-{sid}",
        ))
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
        push_service.spawn(push_service.push_to_student(
            sid,
            f"💬 Message from {item.get('mentor') or 'your mentor'}",
            message[:180],
            link="message",
            tag=f"feedback-{sid}",
        ))
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


@router.post("/session-check")
async def session_check(principal=Depends(dashboard_student)):
    """Cheap "is this session still good?" for the gateway's proof upload.

    dashboard_student already re-reads the account and access state on every
    call, and its bcrypt proof is cached, so this costs one small DB read instead
    of a fresh password hash. The proof upload used to call /api/student-auth/login
    (full bcrypt, 25 s budget) before every file and failed with 503 when that
    service was busy.
    """
    return {"ok": True, "studentId": principal["studentId"]}


@router.post("/write")
async def write_dashboard_section(body: DashboardWriteBody, principal=Depends(dashboard_student)):
    action = str(body.action or "").strip()
    if action not in WRITE_ACTIONS:
        # Mentor actions need verified assignment/global policy; this student
        # endpoint must not infer it from a mentor token or an arbitrary ID.
        deny(403, "Student action denied.")
    payload = own_payload(principal, body.payload, body.studentId)
    if body.result not in (None, {}):
        deny(403, "Client result injection denied.")
    applied = await apply_dashboard_write(action, payload, None)
    if not applied.get("ok"):
        return {"ok": False, "result": {"success": False, "message": applied.get("message") or "Write failed"}}
    return {"ok": True, "result": applied.get("result") or {"success": True, "proofUrl": applied.get("proofUrl"), "stats": applied.get("stats")}}


async def _verified_daily_days(db):
    """Only server-written official Full-10 evidence; never client totals/review scores."""
    totals = {}; seen = set()
    async for row in db[STUDENT_MCQ_ATTEMPTS].find({'kind':'daily', 'rankingVerification.eligible': True}):
        v = row.get('rankingVerification') or {}
        if v.get('policy') != 'official-daily-full10-v1' or v.get('attempted') != 10:
            continue
        sid = normalize_student_id(row.get('studentId') or '')
        key = (sid, v.get('setId'))
        try: day = date.fromisoformat(v['day']); correct = int(v['correct'])
        except (KeyError, ValueError, TypeError): continue
        if not sid or not key[1] or key in seen or not 0 <= correct <= 10: continue
        seen.add(key)
        bucket = totals.setdefault(sid, {}).setdefault(day, [0,0])
        bucket[0] += 10; bucket[1] += correct
    return totals
