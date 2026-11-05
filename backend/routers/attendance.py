"""Student self-reported "on leave" / "absent" days (owner spec, 14 Oct 2026).

Students often vanish from the tracker and only explain later ("absent the").
The app now lets them declare it themselves:

  * **On leave** - a date range (2/3/4 days away from home) -> those days show
    as *Leave* in the mentor tracker.
  * **Absent** - a single day -> shows as *Absent*.

Owner decisions (14 Oct 2026):
  * the student declares it himself; the mentor can cancel/change it later.
  * leave AND absent days are BOTH kept out of the attendance % / rank-drop
    maths, but they stay visible and are counted separately so the mentor can
    see *why* a day was empty.
  * the 23:00 / 07:00 / 14:00 missing-tracker reminders skip excused days.

Collections
-----------
``student_leave``  one doc per leave range  (_id = "leave:<uuid>")
``student_absent`` one doc per student+day   (_id = "absent:<sid>:<date>")

Dates are stored as plain ``YYYY-MM-DD`` strings so the tracker can compare them
with its own ``date`` keys without timezone drift.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import require_mentor
from db import STUDENT_ACCOUNTS, get_db
from routers.student_auth import normalize_student_id

IST = timezone(timedelta(hours=5, minutes=30))

STUDENT_LEAVE = "student_leave"
STUDENT_ABSENT = "student_absent"

MAX_LEAVE_DAYS = 21  # one request can cover at most this many days
BACKFILL_DAYS = 3  # "absent the" is usually said 1-3 days later
REASON_MAX = 160

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


# ── small helpers ───────────────────────────────────────────────────────────


def _today() -> date:
    return datetime.now(IST).date()


def _now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _parse_day(value: Any) -> Optional[date]:
    """Accept a date, a datetime or a YYYY-MM-DD string; else None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _day_str(day: date) -> str:
    return day.isoformat()


def _clean_reason(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text[:REASON_MAX]


def _clean_sid(value: Any) -> str:
    sid = normalize_student_id(str(value or ""))
    if not sid:
        raise HTTPException(status_code=400, detail="studentId is required.")
    return sid


async def _ensure_student(db, sid: str) -> None:
    found = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 0, "studentId": 1})
    if not found:
        raise HTTPException(status_code=404, detail="Student not found.")


# ── writers ─────────────────────────────────────────────────────────────────


async def mark_absent(
    db,
    student_id: Any,
    day: Any = None,
    reason: Any = None,
    source: str = "student",
    actor: str = "",
) -> dict:
    """Create/replace the absent entry for one day (today or up to 3 days back)."""
    sid = _clean_sid(student_id)
    await _ensure_student(db, sid)
    target = _parse_day(day) or _today()
    today = _today()
    if target > today:
        raise HTTPException(status_code=400, detail="Aaj se aage ki date nahi chun sakte.")
    if (today - target).days > BACKFILL_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Sirf pichle {BACKFILL_DAYS} din tak hi absent mark kar sakte hain.",
        )
    if await _leave_covers(db, sid, target):
        # Already on leave that day - no need for a second record.
        return {
            "success": True,
            "kind": "leave",
            "date": _day_str(target),
            "message": "Us din aap leave par the.",
        }
    record = {
        "studentId": sid,
        "date": _day_str(target),
        "reason": _clean_reason(reason),
        "status": "active",
        "source": source,
        "actor": actor,
        "createdAt": _now_iso(),
    }
    await db[STUDENT_ABSENT].update_one(
        {"_id": f"absent:{sid}:{_day_str(target)}"},
        {"$set": record, "$setOnInsert": {"_id": f"absent:{sid}:{_day_str(target)}"}},
        upsert=True,
    )
    return {"success": True, "kind": "absent", "date": _day_str(target), "reason": record["reason"]}


async def request_leave(
    db,
    student_id: Any,
    start: Any,
    end: Any,
    reason: Any = None,
    source: str = "student",
    actor: str = "",
) -> dict:
    """Declare a leave range. Overlapping active ranges get extended (one record)."""
    sid = _clean_sid(student_id)
    await _ensure_student(db, sid)
    from_day = _parse_day(start)
    to_day = _parse_day(end) or from_day
    if not from_day:
        raise HTTPException(status_code=400, detail="Leave ki start date chahiye.")
    if to_day < from_day:
        raise HTTPException(status_code=400, detail="End date start se pehle nahi ho sakti.")
    if (to_day - from_day).days + 1 > MAX_LEAVE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Ek baar me {MAX_LEAVE_DAYS} din tak ki leave daal sakte hain.",
        )
    today = _today()
    if from_day < today - timedelta(days=BACKFILL_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"Leave {BACKFILL_DAYS} din pehle se shuru nahi ho sakti.",
        )
    if to_day < today - timedelta(days=BACKFILL_DAYS):
        raise HTTPException(
            status_code=400,
            detail="Purani dates ke liye 'Absent' use karo.",
        )

    leaves = await db[STUDENT_LEAVE].find(
        {"studentId": sid, "status": {"$ne": "cancelled"}}
    ).to_list(length=50)
    merged = None
    for row in leaves:
        row_from = _parse_day(row.get("from"))
        row_to = _parse_day(row.get("to")) or row_from
        if not row_from:
            continue
        # Overlapping or touching ranges become one clean record.
        if from_day <= row_to + timedelta(days=1) and row_from <= to_day + timedelta(days=1):
            merged = row
            from_day = min(from_day, row_from)
            to_day = max(to_day, row_to)
            break
    if merged and (to_day - from_day).days + 1 > MAX_LEAVE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Ek baar me {MAX_LEAVE_DAYS} din tak ki leave daal sakte hain.",
        )
    if merged:
        await db[STUDENT_LEAVE].update_one(
            {"_id": merged.get("_id")},
            {
                "$set": {
                    "from": _day_str(from_day),
                    "to": _day_str(to_day),
                    "days": (to_day - from_day).days + 1,
                    "reason": _clean_reason(reason) or str(merged.get("reason") or ""),
                    "updatedAt": _now_iso(),
                }
            },
        )
        leave_id = str(merged.get("_id") or "")
    else:
        leave_id = f"leave:{uuid.uuid4().hex[:10]}"
        await db[STUDENT_LEAVE].insert_one(
            {
                "_id": leave_id,
                "studentId": sid,
                "from": _day_str(from_day),
                "to": _day_str(to_day),
                "days": (to_day - from_day).days + 1,
                "reason": _clean_reason(reason),
                "status": "active",
                "source": source,
                "actor": actor,
                "createdAt": _now_iso(),
            }
        )
    return {
        "success": True,
        "kind": "leave",
        "leaveId": leave_id,
        "from": _day_str(from_day),
        "to": _day_str(to_day),
        "days": (to_day - from_day).days + 1,
    }


async def cancel_leave(
    db,
    student_id: Any = None,
    leave_id: Any = None,
    day: Any = None,
    actor: str = "",
) -> dict:
    """Cancel a leave range (by id) or a single absent day (by studentId+date)."""
    if leave_id:
        row = await db[STUDENT_LEAVE].find_one({"_id": str(leave_id)})
        if not row:
            raise HTTPException(status_code=404, detail="Leave record nahi mila.")
        if student_id:
            sid = _clean_sid(student_id)
            if sid != str(row.get("studentId") or ""):
                raise HTTPException(status_code=403, detail="Ye leave aapki nahi hai.")
        await db[STUDENT_LEAVE].update_one(
            {"_id": str(leave_id)},
            {"$set": {"status": "cancelled", "cancelledAt": _now_iso(), "cancelledBy": actor}},
        )
        return {"success": True, "kind": "leave", "leaveId": str(leave_id), "status": "cancelled"}

    sid = _clean_sid(student_id)
    target = _parse_day(day) or _today()
    result = await db[STUDENT_ABSENT].update_one(
        {"_id": f"absent:{sid}:{_day_str(target)}"},
        {"$set": {"status": "cancelled", "cancelledAt": _now_iso(), "cancelledBy": actor}},
    )
    if not result.matched_count:
        # Nothing to cancel: still answer success so the app stays simple.
        return {"success": True, "kind": "absent", "date": _day_str(target), "status": "none"}
    return {"success": True, "kind": "absent", "date": _day_str(target), "status": "cancelled"}


# ── readers ─────────────────────────────────────────────────────────────────


async def _leave_covers(db, sid: str, day: date) -> bool:
    row = await db[STUDENT_LEAVE].find_one(
        {
            "studentId": sid,
            "status": {"$ne": "cancelled"},
            "from": {"$lte": _day_str(day)},
            "to": {"$gte": _day_str(day)},
        },
        {"_id": 1},
    )
    return bool(row)


async def attendance_index(
    db,
    from_day: date,
    to_day: date,
    student_ids: Optional[list[str]] = None,
) -> dict:
    """{(studentId, date): {"kind": "leave"|"absent", "reason": str, "recordId": str}}.

    The tracker uses this to label a day as Leave/Absent instead of Missed.
    """
    index: dict = {}
    sid_filter: dict = {}
    if student_ids:
        sids = [normalize_student_id(s) for s in student_ids if str(s or "").strip()]
        sid_filter = {"studentId": {"$in": sids}} if sids else {"studentId": {"$in": []}}
    from_str, to_str = _day_str(from_day), _day_str(to_day)

    async for row in db[STUDENT_LEAVE].find(
        {**sid_filter, "status": {"$ne": "cancelled"}, "from": {"$lte": to_str}, "to": {"$gte": from_str}}
    ):
        sid = str(row.get("studentId") or "")
        start = _parse_day(row.get("from"))
        end = _parse_day(row.get("to")) or start
        if not sid or not start:
            continue
        cursor = max(start, from_day)
        last = min(end or start, to_day)
        while cursor <= last:
            index[(sid, cursor)] = {
                "kind": "leave",
                "reason": str(row.get("reason") or ""),
                "recordId": str(row.get("_id") or ""),
            }
            cursor += timedelta(days=1)

    async for row in db[STUDENT_ABSENT].find(
        {**sid_filter, "status": {"$ne": "cancelled"}, "date": {"$gte": from_str, "$lte": to_str}}
    ):
        sid = str(row.get("studentId") or "")
        day = _parse_day(row.get("date"))
        if not sid or not day:
            continue
        index.setdefault(
            (sid, day),
            {
                "kind": "absent",
                "reason": str(row.get("reason") or ""),
                "recordId": str(row.get("_id") or ""),
            },
        )
    return index


async def excused_students(db, day: date) -> set[str]:
    """Student ids that are leave/absent on ``day`` (used to skip reminders)."""
    index = await attendance_index(db, day, day)
    return {sid for (sid, _day) in index.keys()}


async def student_status(db, student_id: Any) -> dict:
    """Everything the app needs: today's status + active/upcoming leave."""
    sid = _clean_sid(student_id)
    today = _today()
    index = await attendance_index(db, today - timedelta(days=14), today + timedelta(days=30), [sid])
    today_entry = index.get((sid, today))
    leaves = await db[STUDENT_LEAVE].find(
        {"studentId": sid, "status": {"$ne": "cancelled"}, "to": {"$gte": _day_str(today - timedelta(days=BACKFILL_DAYS))}},
    ).sort("from", 1).to_list(length=20)
    recent_absent = [
        {"date": day.isoformat(), "reason": entry.get("reason", "")}
        for (row_sid, day), entry in sorted(index.items(), key=lambda kv: kv[0][1])
        if row_sid == sid and entry.get("kind") == "absent" and day <= today
    ][-5:]
    return {
        "studentId": sid,
        "today": _day_str(today),
        "status": (today_entry or {}).get("kind") or "none",
        "reason": (today_entry or {}).get("reason") or "",
        "recordId": (today_entry or {}).get("recordId") or "",
        "leaves": [
            {
                "leaveId": str(row.get("_id") or ""),
                "from": row.get("from"),
                "to": row.get("to"),
                "days": row.get("days"),
                "reason": row.get("reason") or "",
                "source": row.get("source") or "",
                "active": str(row.get("from") or "") <= _day_str(today) <= str(row.get("to") or ""),
            }
            for row in leaves
        ],
        "recentAbsent": recent_absent,
        "limits": {"maxLeaveDays": MAX_LEAVE_DAYS, "backfillDays": BACKFILL_DAYS},
    }


# ── mentor REST (dashboard) ─────────────────────────────────────────────────


class LeaveIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    studentId: str = Field(min_length=1, max_length=64)
    from_: str = Field(alias="from", min_length=1, max_length=32)
    to: Optional[str] = Field(default=None, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX)


class AbsentIn(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    date: Optional[str] = Field(default=None, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX)


class CancelIn(BaseModel):
    leaveId: Optional[str] = Field(default=None, max_length=80)
    studentId: Optional[str] = Field(default=None, max_length=64)
    date: Optional[str] = Field(default=None, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX)


@router.get("/mentor/day")
async def mentor_day(
    day: str = Query(default="", alias="date"),
    batch: str = Query(default="All Batches"),
    _mentor=Depends(require_mentor),
):
    """Everybody who is on leave / absent on a given day (default: today)."""
    db = get_db()
    target = _parse_day(day) or _today()
    index = await attendance_index(db, target, target)
    if not index:
        return {"date": _day_str(target), "list": []}
    sids = sorted({sid for (sid, _day) in index.keys()})
    accounts = await db[STUDENT_ACCOUNTS].find(
        {"studentId": {"$in": sids}},
        {"_id": 0, "studentId": 1, "studentName": 1, "batch": 1, "group": 1},
    ).to_list(length=2000)
    by_sid = {str(row.get("studentId") or ""): row for row in accounts}
    wanted_batch = str(batch or "All Batches").strip()
    items = []
    for (sid, day_key), entry in sorted(index.items(), key=lambda kv: kv[0][1]):
        account = by_sid.get(sid) or {}
        row_batch = str(account.get("batch") or "Unassigned").strip() or "Unassigned"
        if wanted_batch and wanted_batch != "All Batches" and row_batch != wanted_batch:
            continue
        items.append(
            {
                "studentId": sid,
                "studentName": str(account.get("studentName") or sid).strip() or sid,
                "batch": row_batch,
                "group": str(account.get("group") or "Unassigned").strip() or "Unassigned",
                "date": _day_str(day_key),
                "kind": entry.get("kind"),
                "reason": entry.get("reason") or "",
                "recordId": entry.get("recordId") or "",
            }
        )
    return {"date": _day_str(target), "list": items}


@router.get("/mentor/student/{student_id}")
async def mentor_student(student_id: str, _mentor=Depends(require_mentor)):
    """Leave/absent history for one student (mentor dashboard profile view)."""
    db = get_db()
    sid = _clean_sid(student_id)
    status = await student_status(db, sid)
    history = await db[STUDENT_ABSENT].find(
        {"studentId": sid}, {"_id": 0}
    ).sort("date", -1).to_list(length=60)
    leaves = await db[STUDENT_LEAVE].find({"studentId": sid}).sort("createdAt", -1).to_list(length=60)
    return {
        "studentId": sid,
        **status,
        "absentHistory": [
            {
                "date": row.get("date"),
                "reason": row.get("reason") or "",
                "status": row.get("status") or "active",
                "source": row.get("source") or "",
            }
            for row in history
        ],
        "leaveHistory": [
            {
                "leaveId": str(row.get("_id") or ""),
                "from": row.get("from"),
                "to": row.get("to"),
                "days": row.get("days"),
                "reason": row.get("reason") or "",
                "status": row.get("status") or "active",
                "source": row.get("source") or "",
                "createdAt": row.get("createdAt") or "",
            }
            for row in leaves
        ],
    }


@router.post("/mentor/leave")
async def mentor_leave(body: LeaveIn, mentor=Depends(require_mentor)):
    """Mentor marks (or extends) a leave range for a student."""
    actor = str((mentor or {}).get("sub") or "mentor")
    result = await request_leave(
        get_db(), body.studentId, body.from_, body.to or body.from_, body.reason, "mentor", actor
    )
    return result


@router.post("/mentor/absent")
async def mentor_absent(body: AbsentIn, mentor=Depends(require_mentor)):
    """Mentor marks a single absent day for a student."""
    actor = str((mentor or {}).get("sub") or "mentor")
    return await mark_absent(get_db(), body.studentId, body.date, body.reason, "mentor", actor)


@router.post("/mentor/cancel")
async def mentor_cancel(body: CancelIn, mentor=Depends(require_mentor)):
    """Mentor cancels a leave range or a single absent day."""
    actor = str((mentor or {}).get("sub") or "mentor")
    return await cancel_leave(
        get_db(), body.studentId, body.leaveId, body.date, actor=actor
    )
