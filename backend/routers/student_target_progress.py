"""Personalised day-based target progress.

A student picks a start day (1..MAX_DAYS) on first login. That choice is locked:
the student app can read it and complete days, but only a mentor can change the
start day, through ``PATCH /api/student-targets/{student_id}/start-day``.

The day a student may work on advances **only when they complete the previous
day** — the calendar date never moves it, and a future day can never be opened
early:

    unlocked_day = first day from start_day onwards that is not yet complete

So: pick Day 12 -> only Day 12's targets are open -> complete Day 12 -> Day 13
unlocks. That day number replaces the calendar date when choosing which
published target day the student sees.

Everything here is additive. Students with no progress record keep the existing
calendar-date behaviour in ``routers/daily_targets.py``, so the installed app and
every student who has not picked a day yet are unaffected.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_mentor
from db import STUDENT_ACCOUNTS, STUDENT_TARGET_PROGRESS, get_db
from routers.daily_targets import (
    TARGETS,
    _audience_matches,
    from_live_plan,
    live_plan_ids,
    plan_order,
)
from routers.dashboard_access import dashboard_student, own_payload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["student-targets"])

IST = ZoneInfo("Asia/Kolkata")
MAX_DAYS = 40
MIN_DAY = 1


def _now() -> str:
    return datetime.now(IST).isoformat()


def _today() -> date:
    return datetime.now(IST).date()


def _student_id(value: str) -> str:
    return str(value or "").strip().upper()


def _parse_date(value) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def unlocked_day(record: dict) -> int:
    """The day the student may work on now.

    Sequential by design: the day only moves forward when the previous one is
    marked complete. The calendar date never advances a student, and a future
    day can never be opened early.
    """
    start_day = int(record.get("startDay") or MIN_DAY)
    done = {int(d) for d in (record.get("completedDays") or [])}
    day = max(MIN_DAY, start_day)
    while day < MAX_DAYS and day in done:
        day += 1
    return min(MAX_DAYS, day)


def _public(record: dict) -> dict:
    done = sorted({int(d) for d in (record.get("completedDays") or [])})
    day = unlocked_day(record)
    start_day = int(record.get("startDay") or MIN_DAY)
    total_days = max(0, MAX_DAYS - start_day + 1)
    done_in_range = [d for d in done if start_day <= d <= MAX_DAYS]
    return {
        "studentId": record.get("studentId"),
        "startDay": start_day,
        "startDate": record.get("startDate"),
        "currentDay": day,
        "nextDay": day + 1 if day < MAX_DAYS else None,
        "totalDays": total_days,
        "completedCount": len(done_in_range),
        "progressPercent": round(100 * len(done_in_range) / total_days) if total_days else 0,
        "advanceRule": "complete-day",
        "maxDays": MAX_DAYS,
        "completedDays": done,
        "completedOn": record.get("dayLog") or {},
        "lastCompletedDay": record.get("lastCompletedDay"),
        "locked": True,
        "finished": day >= MAX_DAYS and MAX_DAYS in done,
        "updatedAt": record.get("updatedAt"),
        "updatedBy": record.get("updatedBy"),
    }


async def _ensure_indexes() -> None:
    db = get_db()
    try:
        await db[STUDENT_TARGET_PROGRESS].create_index("studentId", unique=True)
    except Exception as exc:  # never block the student on an index problem
        logger.warning("student_target_progress index: %s", exc)


async def get_progress(student_id: str) -> Optional[dict]:
    return await get_db()[STUDENT_TARGET_PROGRESS].find_one(
        {"studentId": _student_id(student_id)}, {"_id": 0}
    )


async def personal_day_for(student_id: str) -> Optional[int]:
    """Used by daily targets: None when the student has not chosen a day yet."""
    record = await get_progress(student_id)
    return unlocked_day(record) if record else None


# ── models ───────────────────────────────────────────────────────────────────
class StartIn(BaseModel):
    startDay: int = Field(ge=MIN_DAY, le=MAX_DAYS)
    studentId: Optional[str] = None


class CompleteDayIn(BaseModel):
    day: Optional[int] = Field(default=None, ge=MIN_DAY, le=MAX_DAYS)
    studentId: Optional[str] = None


class StartDayIn(BaseModel):
    startDay: int = Field(ge=MIN_DAY, le=MAX_DAYS)
    note: Optional[str] = Field(default=None, max_length=300)


# ── student endpoints ────────────────────────────────────────────────────────
@router.post("/api/student-targets/start")
async def start_progress(body: StartIn, principal=Depends(dashboard_student)):
    """Lock in the student's start day. Allowed once — a second call is a no-op."""
    payload = own_payload(principal, body.model_dump())
    sid = payload["studentId"]
    await _ensure_indexes()
    db = get_db()
    existing = await get_progress(sid)
    if existing:
        return {"ok": True, "created": False, "progress": _public(existing)}
    student = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 0, "studentId": 1})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    today = _today()
    record = {
        "studentId": sid,
        "startDay": int(body.startDay),
        "startDate": today.isoformat(),
        "completedDays": [],
        "dayLog": {},
        "dayTasks": {},
        "lastCompletedDay": None,
        "locked": True,
        "createdAt": _now(),
        "updatedAt": _now(),
        "updatedBy": "student",
    }
    await db[STUDENT_TARGET_PROGRESS].insert_one(dict(record))
    record.pop("_id", None)
    return {"ok": True, "created": True, "progress": _public(record)}


@router.get("/api/student-targets/progress")
async def read_progress(
    studentId: str = Query(default="", max_length=64),
    principal=Depends(dashboard_student),
):
    payload = own_payload(principal, {"studentId": studentId})
    record = await get_progress(payload["studentId"])
    if not record:
        return {"ok": True, "started": False, "maxDays": MAX_DAYS, "progress": None}
    return {"ok": True, "started": True, "progress": _public(record)}


@router.post("/api/student-targets/complete-day")
async def complete_day(body: CompleteDayIn, principal=Depends(dashboard_student)):
    """Mark the current personal day complete and move to the next one."""
    payload = own_payload(principal, body.model_dump())
    sid = payload["studentId"]
    record = await get_progress(sid)
    if not record:
        raise HTTPException(status_code=404, detail="Start day is not selected yet.")
    current = unlocked_day(record)
    day = int(body.day or current)
    if day > current:
        raise HTTPException(
            status_code=400,
            detail=f"Day {day} is locked. Finish Day {current} first to unlock it.",
        )
    if day < current:
        raise HTTPException(
            status_code=400,
            detail=f"Day {day} is already complete. Today's day is Day {current}.",
        )
    done = sorted(set(int(d) for d in (record.get("completedDays") or [])) | {day})
    db = get_db()
    await db[STUDENT_TARGET_PROGRESS].update_one(
        {"studentId": sid},
        {"$set": {
            "completedDays": done,
            "dayLog": dict(record.get("dayLog") or {}, **{str(day): _now()}),
            "lastCompletedDay": day,
            "updatedAt": _now(),
            "updatedBy": "student",
        }},
    )
    record.update({"completedDays": done, "lastCompletedDay": day,
                   "dayLog": dict(record.get("dayLog") or {}, **{str(day): _now()})})
    return {"ok": True, "day": day, "progress": _public(record)}


def planned_date(start_date: Optional[date], start_day: int, day: int) -> Optional[str]:
    """Calendar date the day nominally falls on. Label only — it never unlocks a day."""
    if not start_date:
        return None
    return (start_date + timedelta(days=max(0, day - start_day))).isoformat()


def _task_rows(target: dict) -> list:
    paper = target.get("subject")
    paper = "" if not paper or str(paper).strip().lower() in {"all", "everyone", "any"} else str(paper)
    rows = []
    for task in target.get("tasks") or []:
        detail = task.get("detail") or ""
        if paper and paper.lower() not in detail.lower():
            detail = (paper + (". " + detail if detail else "")).strip()
        rows.append({
            "id": task.get("id"),
            "label": task.get("label") or "Study task",
            "detail": detail,
            "kind": task.get("kind") or "chapter",
        })
    return rows


class TaskTickIn(BaseModel):
    day: int = Field(ge=MIN_DAY, le=MAX_DAYS)
    taskId: str = Field(min_length=1, max_length=120)
    done: bool = True


@router.post("/api/student-targets/toggle-task")
async def toggle_task(body: TaskTickIn, principal=Depends(dashboard_student)):
    """Tick one task inside a day.

    This is the checklist, not the day completion: a day only advances through
    /complete-day. Locked days cannot be ticked, and past days stay tickable only
    until the day is marked complete.
    """
    payload = own_payload(principal, body.model_dump())
    sid = payload["studentId"]
    record = await get_progress(sid)
    if not record:
        raise HTTPException(status_code=404, detail="Start day is not selected yet.")
    current = unlocked_day(record)
    if body.day > current:
        raise HTTPException(status_code=400, detail=f"Day {body.day} is locked. Day {current} is open.")
    if body.day < int(record.get("startDay") or MIN_DAY):
        raise HTTPException(status_code=400, detail="That day is before your start day.")

    day_tasks = {str(k): list(v or []) for k, v in (record.get("dayTasks") or {}).items()}
    key = str(body.day)
    ticked = set(day_tasks.get(key) or [])
    if body.done:
        ticked.add(body.taskId)
    else:
        ticked.discard(body.taskId)
    day_tasks[key] = sorted(ticked)

    await get_db()[STUDENT_TARGET_PROGRESS].update_one(
        {"studentId": sid},
        {"$set": {"dayTasks": day_tasks, "updatedAt": _now(), "updatedBy": "student"}},
    )
    record["dayTasks"] = day_tasks
    return {
        "ok": True,
        "day": body.day,
        "doneCount": len(ticked),
        "dayTasks": day_tasks[key],
        "progress": _public(record),
    }


@router.get("/api/student-targets/day-ladder")
async def day_ladder(studentId: str = Query(default="", max_length=64), principal=Depends(dashboard_student)):
    """Compact ladder for the chip strip: day, date and state only."""
    payload = own_payload(principal, {"studentId": studentId})
    record = await get_progress(payload["studentId"])
    if not record:
        raise HTTPException(status_code=404, detail="Start day is not selected yet.")
    done = {int(d) for d in (record.get("completedDays") or [])}
    current = unlocked_day(record)
    start_day = int(record.get("startDay") or MIN_DAY)
    start_date = _parse_date(record.get("startDate"))
    days = []
    for day in range(MIN_DAY, MAX_DAYS + 1):      # the strip always starts at Day 1
        if day < start_day:
            state = "locked"
        elif day in done:
            state = "complete"
        elif day == current:
            state = "open"
        else:
            state = "locked"
        days.append({
            "day": day,
            "plannedDate": planned_date(start_date, start_day, day),
            "beforeStart": day < start_day,
            "state": state,
        })
    return {"ok": True, "startDay": start_day, "currentDay": current, "maxDays": MAX_DAYS, "days": days}


async def build_timeline(record: dict, student: dict, from_day: int = 0,
                         include_locked: bool = False) -> dict:
    """Day-by-day view used by both the student app and the mentor webapp."""
    db = get_db()
    done = {int(d) for d in (record.get("completedDays") or [])}
    log = record.get("dayLog") or {}
    current = unlocked_day(record)
    start_day = int(record.get("startDay") or MIN_DAY)
    start_date = _parse_date(record.get("startDate"))
    first = max(MIN_DAY, int(from_day or MIN_DAY))

    rows = await db[TARGETS].find(
        {"active": {"$ne": False},
         "planDay": {"$gte": first, "$lte": MAX_DAYS if include_locked else max(current, first)}},
        {"_id": 0},
    ).to_list(5000)
    live = await live_plan_ids(db)
    # Two bugs met here: a cancelled plan keeps its target rows active, and the
    # same task could arrive from more than one row - the day then listed six
    # tasks with two "Revision (full day)" lines. Keep the newest live plan only,
    # and never repeat a task id.
    rows = [row for row in rows if from_live_plan(row, live) and _audience_matches(student, row)]

    # One plan per day: the newest live plan that carries that day. Older plans
    # never add their tasks on top (that is how a day showed six tasks, two of
    # them "Revision (full day)").
    order = await plan_order(db)
    chosen: dict = {}
    for row in rows:
        try:
            day_number = int(row.get("planDay"))
        except (TypeError, ValueError):
            continue
        plan_id = str(row.get("planId") or "")
        stamp = order.get(plan_id, ("", ""))
        if day_number not in chosen or stamp > chosen[day_number][0]:
            chosen[day_number] = (stamp, plan_id)

    by_day: dict = {}
    for row in rows:
        try:
            day_number = int(row.get("planDay"))
        except (TypeError, ValueError):
            continue
        if str(row.get("planId") or "") != chosen[day_number][1]:
            continue
        by_day.setdefault(day_number, []).extend(_task_rows(row))

    # Never repeat the same task on a day.
    for day_number, tasks in by_day.items():
        seen, unique = set(), []
        for task in tasks:
            task_id = str(task.get("id") or "")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            unique.append(task)
        by_day[day_number] = unique

    days = []
    for day in range(first, MAX_DAYS + 1):
        if day < start_day:
            state = "locked"
        elif day in done:
            state = "complete"
        elif day == current:
            state = "open"
        else:
            state = "locked"
        tasks = [dict(task) for task in by_day.get(day, [])] if (include_locked or state != "locked") else []
        ticked = set((record.get("dayTasks") or {}).get(str(day)) or [])
        for task in tasks:
            task["done"] = str(task.get("id")) in ticked
        days.append({
            "day": day,
            "plannedDate": planned_date(start_date, start_day, day),
            "beforeStart": day < start_day,
            "state": state,
            "completedOn": (log or {}).get(str(day)),
            "targetCount": len(tasks),
            "doneCount": sum(1 for task in tasks if task.get("done")),
            "targets": tasks,
        })
    return {
        "ok": True,
        "studentId": record.get("studentId"),
        "startDay": start_day,
        "currentDay": current,
        "maxDays": MAX_DAYS,
        "days": days,
    }


@router.get("/api/student-targets/day-timeline")
async def day_timeline(
    studentId: str = Query(default="", max_length=64),
    fromDay: int = Query(default=0, ge=0, le=MAX_DAYS),
    principal=Depends(dashboard_student),
):
    """Every day the student can look back at, with the targets published for it.

    Past days and the current day carry their tasks. Locked (future) days return
    an empty list on purpose — the app must not reveal tomorrow's work early.
    """
    payload = own_payload(principal, {"studentId": studentId})
    sid = payload["studentId"]
    record = await get_progress(sid)
    if not record:
        raise HTTPException(status_code=404, detail="Start day is not selected yet.")
    student = await get_db()[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid}, {"_id": 0, "studentId": 1, "group": 1, "attempt": 1, "batch": 1},
    ) or {"studentId": sid}
    return await build_timeline(record, student, fromDay)


# ── mentor endpoints ────────────────────────────────────────────────────────
@router.patch("/api/student-targets/{student_id}/start-day")
async def change_start_day(student_id: str, body: StartDayIn, mentor=Depends(require_mentor)):
    """Mentor-only: move a student's locked start day (1..40)."""
    sid = _student_id(student_id)
    if not sid:
        raise HTTPException(status_code=400, detail="student_id is required.")
    await _ensure_indexes()
    db = get_db()
    who = (mentor or {}).get("sub") or "mentor"
    existing = await get_progress(sid)
    if existing:
        await db[STUDENT_TARGET_PROGRESS].update_one(
            {"studentId": sid},
            {"$set": {"startDay": int(body.startDay), "startDate": _today().isoformat(),
                      "locked": True, "updatedAt": _now(), "updatedBy": who,
                      "lastNote": body.note or ""}},
        )
    else:
        student = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"_id": 0, "studentId": 1})
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")
        await db[STUDENT_TARGET_PROGRESS].insert_one({
            "studentId": sid, "startDay": int(body.startDay),
            "startDate": _today().isoformat(), "completedDays": [],
            "lastCompletedDay": None, "locked": True,
            "createdAt": _now(), "updatedAt": _now(), "updatedBy": who,
            "lastNote": body.note or "",
        })
    record = await get_progress(sid)
    return {"ok": True, "progress": _public(record)}


@router.get("/api/student-targets/all-progress")
async def all_progress(_mentor=Depends(require_mentor)):
    """Mentor view: every student's current day, started or not."""
    db = get_db()
    students = await db[STUDENT_ACCOUNTS].find(
        {"status": {"$ne": "removed"}},
        {"_id": 0, "studentId": 1, "name": 1, "batch": 1, "group": 1, "attempt": 1},
    ).to_list(2000)
    records = {
        row["studentId"]: row
        for row in await db[STUDENT_TARGET_PROGRESS].find({}, {"_id": 0}).to_list(3000)
    }
    rows = []
    for student in students:
        sid = student.get("studentId")
        record = records.get(sid)
        rows.append({
            "studentId": sid,
            "name": student.get("name") or "",
            "batch": student.get("batch") or "",
            "group": student.get("group") or "",
            "attempt": student.get("attempt") or "",
            "started": bool(record),
            "startDay": int(record.get("startDay") or 0) if record else None,
            "currentDay": unlocked_day(record) if record else None,
            "startDate": record.get("startDate") if record else None,
            "completedDays": len(record.get("completedDays") or []) if record else 0,
            "finished": bool(record) and _public(record)["finished"],
            "updatedBy": record.get("updatedBy") if record else None,
        })
    rows.sort(key=lambda r: (r["currentDay"] is None, -(r["currentDay"] or 0), r["name"]))
    started = sum(1 for r in rows if r["started"])
    return {
        "ok": True,
        "maxDays": MAX_DAYS,
        "total": len(rows),
        "started": started,
        "notStarted": len(rows) - started,
        "rows": rows,
    }


@router.get("/api/student-targets/{student_id}/day-timeline")
async def mentor_day_timeline(
    student_id: str,
    fromDay: int = Query(default=0, ge=0, le=MAX_DAYS),
    mentor=Depends(require_mentor),
):
    """Mentor view of one student's timeline — same ladder the student sees.

    The mentor sees every day, including locked ones, because they publish them.
    """
    sid = student_id.strip()
    record = await get_progress(sid)
    if not record:
        raise HTTPException(status_code=404, detail="This student has not picked a start day yet.")
    student = await get_db()[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid}, {"_id": 0, "studentId": 1, "group": 1, "attempt": 1, "batch": 1},
    ) or {"studentId": sid}
    return await build_timeline(record, student, fromDay, include_locked=True)
