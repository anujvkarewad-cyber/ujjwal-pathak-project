"""Mentor-uploaded daily targets.

Groq does not invent the study target. The mentor types the tasks and chooses
who receives them: subject, group, batch, and attempt. Groq's only job here is
one short revision reminder, written once from those exact tasks.
"""
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_mentor
from db import STUDENT_ACCOUNTS, get_db
from routers.revision_schedule import due_revisions

try:
    import httpx
except Exception:
    httpx = None

router = APIRouter(tags=["daily-targets"])

TARGETS = "daily_targets"
DONE = "daily_target_done"
IST = ZoneInfo("Asia/Kolkata")
ALL = "All"
logger = logging.getLogger(__name__)

SUBJECTS = [
    "Advanced Accounting",
    "Corporate and Other Laws",
    "Taxation",
    "Cost and Management Accounting",
    "Auditing and Assurance",
    "Financial Management and Strategic Management",
]

_indexed = False


def _now() -> str:
    return datetime.now(IST).isoformat()


def _today():
    return datetime.now(IST).date()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _is_all(value: str) -> bool:
    text = _norm(value)
    return text in {"", "all", "all subjects", "all groups", "all batches", "all attempts"}


def _attempt_key(value: str) -> str:
    text = _norm(value)
    if _is_all(value):
        return "all"
    months = {
        "jan": "jan", "january": "jan", "01": "jan", "1": "jan",
        "feb": "feb", "february": "feb", "02": "feb", "2": "feb",
        "mar": "mar", "march": "mar", "03": "mar", "3": "mar",
        "apr": "apr", "april": "apr", "04": "apr", "4": "apr",
        "may": "may", "05": "may", "5": "may",
        "jun": "jun", "june": "jun", "06": "jun", "6": "jun",
        "jul": "jul", "july": "jul", "07": "jul", "7": "jul",
        "aug": "aug", "august": "aug", "08": "aug", "8": "aug",
        "sep": "sep", "sept": "sep", "september": "sep", "09": "sep", "9": "sep",
        "oct": "oct", "october": "oct", "10": "oct",
        "nov": "nov", "november": "nov", "11": "nov",
        "dec": "dec", "december": "dec", "12": "dec",
    }
    iso = re.search(r"\b(20\d{2})[ ./-](\d{1,2})[ ./-](\d{1,2})\b", text)
    if iso:
        month = months.get(str(int(iso.group(2))))
        if month:
            return f"{month} {iso.group(1)}"
    dmy = re.search(r"\b(\d{1,2})[ ./-](\d{1,2})[ ./-](20\d{2})\b", text)
    if dmy:
        month = months.get(str(int(dmy.group(2))))
        if month:
            return f"{month} {dmy.group(3)}"
    named = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b\s*(20\d{2})\b", text)
    if named:
        month = months.get(named.group(1)[:3])
        if month:
            return f"{month} {named.group(2)}"
    return text


def _group_key(value: str) -> str:
    text = _norm(value)
    if text in {"", "all", "all groups"}:
        return "all"
    if text in {"both", "both groups", "combined", "group 1 and 2", "group i and ii"}:
        return "both"
    has1 = bool(re.search(r"\b(1|i|one)\b", text))
    has2 = bool(re.search(r"\b(2|ii|two)\b", text))
    if has1 and has2:
        return "both"
    if has2:
        return "g2"
    if has1:
        return "g1"
    return text


def _batch_key(value: str) -> str:
    if _is_all(value):
        return "all"
    return _norm(value)


def _subject_key(value: str) -> str:
    if _is_all(value):
        return "all"
    return _norm(value)


def _audience_matches(student: dict, target: dict) -> bool:
    if _attempt_key(target.get("attempt")) != "all" and _attempt_key(target.get("attempt")) != _attempt_key(student.get("attempt")):
        return False
    if _batch_key(target.get("batch")) != "all" and _batch_key(target.get("batch")) != _batch_key(student.get("batch")):
        return False
    target_group = _group_key(target.get("group"))
    student_group = _group_key(student.get("group"))
    if target_group == "all":
        return True
    # "Both Groups" is a distinct audience, not a wildcard for G1/G2.
    # Only a target explicitly addressed to All can cross group boundaries.
    return target_group in {"g1", "g2", "both"} and target_group == student_group


def _specificity(target: dict) -> int:
    score = 0
    if _attempt_key(target.get("attempt")) != "all":
        score += 4
    if _group_key(target.get("group")) != "all":
        score += 2
    if _batch_key(target.get("batch")) != "all":
        score += 1
    if _subject_key(target.get("subject")) != "all":
        score += 8
    return score


def _covers(target: dict, day) -> bool:
    try:
        start = datetime.fromisoformat(str(target.get("startDate"))).date()
        end = datetime.fromisoformat(str(target.get("endDate") or target.get("startDate"))).date()
    except Exception:
        return False
    return start <= day <= end


def _best_targets(student: dict, rows: list, day) -> list:
    chosen = {}
    for row in rows:
        if row.get("active") is False or not _covers(row, day) or not _audience_matches(student, row):
            continue
        key = _subject_key(row.get("subject"))
        prev = chosen.get(key)
        if not prev or _specificity(row) > _specificity(prev) or (
            _specificity(row) == _specificity(prev) and str(row.get("createdAt") or "") > str(prev.get("createdAt") or "")
        ):
            chosen[key] = row
    return list(chosen.values())


def _task_kind(label: str) -> str:
    text = _norm(label)
    if any(word in text for word in ("mcq", "question practice", "practice questions")):
        return "mcq"
    if any(word in text for word in ("tracker", "log hour", "study hour", "log your")):
        return "tracker"
    if "revis" in text:
        return "revise"
    return "chapter"


def _student_id(value: str) -> str:
    value = re.sub(r"\s+", "", str(value or "")).upper()
    dup = re.match(r"^(UMP\d+)\1+$", value)
    if dup:
        value = dup.group(1)
    match = re.match(r"^UMP(\d+)$", value)
    if match:
        return "UMP" + match.group(1).zfill(4)
    return value


def _public_target(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "startDate": row.get("startDate"),
        "endDate": row.get("endDate"),
        "attempt": row.get("attempt") or ALL,
        "group": row.get("group") or ALL,
        "batch": row.get("batch") or ALL,
        "subject": row.get("subject") or ALL,
        "tasks": row.get("tasks") or [],
        "revisionReminder": (row.get("revisionReminder") or "") if row.get("reminderSource") == "groq" else "",
        "reminderSource": row.get("reminderSource") or "plain",
        "createdAt": row.get("createdAt"),
        "studentCount": row.get("studentCount") or 0,
    }


def _clean_reminder(text: str) -> str:
    text = re.sub(r"[*_#]+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(parts[:2]).strip()
    return text[:320]


async def _groq_reminder(subject: str, tasks: list) -> tuple:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        raise HTTPException(status_code=503, detail="AI revision reminders are not configured. No changes were saved. Ask the administrator to check the Groq configuration.")
    if not tasks:
        raise HTTPException(status_code=400, detail="Add at least one task before generating an AI reminder.")
    lines = "\n".join(f"- {task.get('label')}" for task in tasks if task.get("label"))
    prompt = (
        "Write two short sentences for a CA student. "
        "First, tell them to do only the mentor's target on the timer. "
        "Second, tell them that after the timer they must answer the receipt questions, "
        "and those answers decide weak, average, or strong. "
        "Do not add a chapter, section number, case, or revision date. English only. No emoji.\n"
        f"Subject: {subject or 'All subjects'}\n"
        f"Mentor target:\n{lines}"
    )
    errors = []
    # Use supported production Groq models (the old Llama IDs are retired
    # for free/developer accounts). Keep reasoning out of student messages.
    # At most two AI attempts, with a wall-clock cap on each request.
    # An alternate Groq model is still AI generation, never a plain-text fallback.
    for model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b"):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await asyncio.wait_for(client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "max_completion_tokens": 768,
                        "reasoning_effort": "low",
                        "include_reasoning": False,
                        "messages": [
                            {"role": "system", "content": "You only remind the student to revise the given target. You never create a new study target."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                ), timeout=10)
            if response.status_code in (401, 403):
                logger.warning("Groq reminder authorization failed (HTTP %s)", response.status_code)
                raise HTTPException(status_code=503, detail="Groq rejected the AI configuration. No changes were saved. Ask the administrator to check the Groq API key and access.")
            if response.status_code != 200:
                provider_code = ""
                try:
                    raw_code = (response.json().get("error") or {}).get("code") or ""
                    provider_code = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw_code))[:60]
                except Exception:
                    pass
                reason = f"HTTP {response.status_code}" + (f"/{provider_code}" if provider_code else "")
                errors.append(f"{model}: {reason}")
                logger.warning("Groq reminder request failed (model=%s, reason=%s)", model, reason)
                continue
            choice = (response.json().get("choices") or [{}])[0]
            # Never use internal reasoning as a substitute for the final answer.
            content = ((choice.get("message") or {}).get("content") or "")
            cleaned = _clean_reminder(content)
            if choice.get("finish_reason") == "length":
                errors.append(f"{model}: incomplete_output")
                continue
            if len(cleaned) >= 20:
                return cleaned, "groq"
            errors.append(f"{model}: empty_or_short_output")
        except HTTPException:
            raise
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}")
            logger.warning("Groq reminder request failed (model=%s, error=%s)", model, type(exc).__name__)
            continue
    raise HTTPException(
        status_code=503,
        detail="AI reminder generation failed after two attempts. No changes were saved. Your draft is still available. " + "; ".join(errors),
    )


async def _ensure_indexes():
    global _indexed
    if _indexed:
        return
    db = get_db()
    await db[TARGETS].create_index("startDate")
    await db[DONE].create_index([("studentId", 1), ("date", 1)])
    _indexed = True


async def _students():
    db = get_db()
    cursor = db[STUDENT_ACCOUNTS].find(
        {},
        {"_id": 0, "studentId": 1, "studentName": 1, "group": 1, "attempt": 1, "batch": 1},
    )
    return await cursor.to_list(5000)


def _matching_students(students: list, target: dict) -> list:
    return [row for row in students if _audience_matches(row, target)]


class TaskIn(BaseModel):
    label: str = Field(min_length=1, max_length=240)
    detail: str = Field(default="", max_length=400)


class TargetIn(BaseModel):
    startDate: str = Field(min_length=10, max_length=10)
    endDate: Optional[str] = Field(default=None, max_length=10)
    attempt: str = Field(default=ALL, max_length=80)
    group: str = Field(default=ALL, max_length=80)
    batch: str = Field(default=ALL, max_length=80)
    subject: str = Field(default=ALL, max_length=120)
    tasks: List[TaskIn] = Field(min_length=1, max_length=12)


def _parse_date(value: str):
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.")


@router.get("/api/targets/options")
async def target_options(_mentor=Depends(require_mentor)):
    students = await _students()
    def unique(field):
        values = sorted({str(row.get(field) or "").strip() for row in students if str(row.get(field) or "").strip()})
        return values
    return {
        "attempts": unique("attempt"),
        "groups": unique("group"),
        "batches": unique("batch"),
        "subjects": SUBJECTS,
        "studentCount": len(students),
    }


@router.get("/api/targets/preview")
async def preview_target(
    attempt: str = Query(default=ALL),
    group: str = Query(default=ALL),
    batch: str = Query(default=ALL),
    _mentor=Depends(require_mentor),
):
    draft = {"attempt": attempt, "group": group, "batch": batch, "subject": ALL}
    matched = _matching_students(await _students(), draft)
    return {
        "count": len(matched),
        "names": [row.get("studentName") or row.get("studentId") for row in matched[:8]],
        "sample": [{"studentId": row.get("studentId"), "group": row.get("group")} for row in matched[:8]],
    }


@router.get("/api/targets")
async def list_targets(_mentor=Depends(require_mentor)):
    await _ensure_indexes()
    db = get_db()
    rows = await db[TARGETS].find({"active": {"$ne": False}}, {"_id": 0}).sort("startDate", -1).to_list(200)
    return {"targets": [_public_target(row) for row in rows]}


@router.post("/api/targets")
async def create_target(body: TargetIn, mentor=Depends(require_mentor)):
    start = _parse_date(body.startDate)
    end = _parse_date(body.endDate) if body.endDate else start
    if end < start:
        raise HTTPException(status_code=400, detail="End date cannot be before the start date.")
    if (end - start).days > 31:
        raise HTTPException(status_code=400, detail="A target can cover at most 31 days.")
    tasks = []
    for item in body.tasks:
        label = re.sub(r"\s+", " ", item.label).strip()
        if not label:
            continue
        tasks.append({
            "id": "t-" + uuid.uuid4().hex[:10],
            "label": label,
            "detail": re.sub(r"\s+", " ", item.detail or "").strip(),
            "kind": _task_kind(label),
        })
    if not tasks:
        raise HTTPException(status_code=400, detail="Add at least one task.")
    subject = (body.subject or ALL).strip() or ALL
    reminder, source = await _groq_reminder(subject, tasks)
    if source != "groq" or not reminder.strip():
        raise HTTPException(status_code=503, detail="An AI-generated reminder is required. The target was not published.")
    students = await _students()
    draft = {
        "attempt": body.attempt or ALL,
        "group": body.group or ALL,
        "batch": body.batch or ALL,
        "subject": subject,
    }
    count = len(_matching_students(students, draft))
    doc = {
        "id": "dt-" + uuid.uuid4().hex[:12],
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "attempt": draft["attempt"],
        "group": draft["group"],
        "batch": draft["batch"],
        "subject": subject,
        "tasks": tasks,
        "revisionReminder": reminder,
        "reminderSource": source,
        "studentCount": count,
        "createdAt": _now(),
        "createdBy": mentor.get("sub") or "mentor",
        "active": True,
    }
    await _ensure_indexes()
    await get_db()[TARGETS].insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "target": _public_target(doc)}


@router.post("/api/targets/{target_id}/reminder")
async def regenerate_target_reminder(target_id: str, _mentor=Depends(require_mentor)):
    """Repair an existing plain reminder without publishing a duplicate target."""
    collection = get_db()[TARGETS]
    row = await collection.find_one({"id": target_id, "active": {"$ne": False}})
    if not row:
        raise HTTPException(status_code=404, detail="Target not found.")
    reminder, source = await _groq_reminder(row.get("subject") or ALL, row.get("tasks") or [])
    if source != "groq" or not reminder.strip():
        raise HTTPException(status_code=503, detail="An AI-generated reminder is required. The target was not changed.")
    changes = {"revisionReminder": reminder, "reminderSource": source, "reminderUpdatedAt": _now()}
    result = await collection.update_one(
        {"id": target_id, "active": {"$ne": False}}, {"$set": changes},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Target no longer active.")
    return {"ok": True, "target": _public_target(dict(row, **changes))}


@router.delete("/api/targets/{target_id}")
async def remove_target(target_id: str, _mentor=Depends(require_mentor)):
    result = await get_db()[TARGETS].update_one({"id": target_id}, {"$set": {"active": False, "removedAt": _now()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"ok": True}


class CompleteIn(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    taskId: str = Field(min_length=1, max_length=80)


@router.post("/api/targets/complete")
async def complete_task(body: CompleteIn):
    sid = _student_id(body.studentId)
    await get_db()[DONE].update_one(
        {"studentId": sid, "date": _today().isoformat(), "taskId": body.taskId},
        {"$set": {"doneAt": _now()}},
        upsert=True,
    )
    return {"ok": True}


@router.get("/api/ai/daily-target")
async def student_daily_target(studentId: str = Query(min_length=1, max_length=64)):
    """Installed app calls this. Empty means no mentor target, so the app keeps its own list."""
    sid = _student_id(studentId)
    db = get_db()
    student = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid},
        {"_id": 0, "studentId": 1, "group": 1, "attempt": 1, "batch": 1},
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    today = _today()
    window_start = (today - timedelta(days=2)).isoformat()
    rows = await db[TARGETS].find(
        {"active": {"$ne": False}, "endDate": {"$gte": window_start}},
        {"_id": 0},
    ).to_list(300)
    chosen = _best_targets(student, rows, today)
    due = await due_revisions(sid)
    if not chosen and not due:
        raise HTTPException(status_code=404, detail="No target published.")
    done = {
        row.get("taskId")
        for row in await db[DONE].find(
            {"studentId": sid, "date": today.isoformat()},
            {"_id": 0, "taskId": 1},
        ).to_list(50)
    }
    tasks = []
    for target in chosen:
        paper = target.get("subject") if not _is_all(target.get("subject")) else ""
        for task in target.get("tasks") or []:
            detail = task.get("detail") or ""
            if paper and paper.lower() not in detail.lower():
                detail = (paper + (". " + detail if detail else "")).strip()
            tasks.append({
                "id": task.get("id"),
                "label": task.get("label") or "Study task",
                "detail": detail,
                "kind": task.get("kind") or "chapter",
                "done": task.get("id") in done,
            })
    if chosen:
        yesterday = _best_targets(student, rows, today - timedelta(days=1))
        # Historical plain reminders stay stored, but are never sent to students.
        candidates = [row for row in (yesterday or chosen)
                      if row.get("reminderSource") == "groq" and (row.get("revisionReminder") or "").strip()]
        if candidates:
            reminder_row = max(candidates, key=lambda row: (_specificity(row), str(row.get("createdAt") or "")))
            pieces = []
            for row in candidates:
                text = (row.get("revisionReminder") or "").strip()
                if text not in pieces:
                    pieces.append(text)
            reminder_id = "revise-" + str(reminder_row.get("id") or "today")
            tasks.append({
                "id": reminder_id,
                "label": "Use the timer",
                "detail": " ".join(pieces)[:320],
                "kind": "revise",
                "done": reminder_id in done,
            })
    for item in due:
        task_id = "due-" + _norm(item.get("concept"))[:40].replace(" ", "-")
        tasks.append({
            "id": task_id,
            "label": "Revise " + str(item.get("concept") or "chapter"),
            "detail": item.get("reminder") or "",
            "kind": "revise",
            "done": task_id in done,
        })
    return {
        "date": today.isoformat(),
        "tasks": tasks,
        "locked": False,
        "source": "mentor",
        "reminderSource": "mentor",
        "dueRevisions": due,
    }
