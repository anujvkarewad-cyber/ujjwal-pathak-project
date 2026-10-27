"""Batch-wise weekly target plans.

The mentor types a multi-day plan ONCE (day rows with subject, topic, hours and
type). Publishing expands it into the existing ``daily_targets`` documents, so
the installed app keeps reading ``/api/ai/daily-target`` unchanged — no APK
work, no per-day manual entry.

AI revision reminders are generated in the background (one per plan day) so
publishing a 7-day plan stays instant. A best-effort mirror of every active
plan is written to the "Target Plans" tab of the tracker spreadsheet; a sheet
failure never blocks the plan itself.
"""
import asyncio
import base64
import json as _json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from auth import require_mentor
from db import get_db
from routers.daily_targets import (
    SUBJECTS,
    TARGETS,
    _audience_matches,
    _ensure_indexes,
    _groq_reminder,
    _norm,
    _now,
    _students,
    _task_kind,
    _today,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["target-plans"])

PLANS = "target_plans"
IST = ZoneInfo("Asia/Kolkata")
ALL = "All"
MAX_DAYS = 90
SHEET_ID = "1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc"
SHEET_TAB = "Target Plans"

_SUBJECT_HINTS = [
    (("cost", "costing", "cm"), "Cost and Management Accounting"),
    (("audit", "auditing"), "Auditing and Assurance"),
    (("account", "accounting", "as "), "Advanced Accounting"),
    (("law", "legal"), "Corporate and Other Laws"),
    (("tax", "taxation", "gst", "dt"), "Taxation"),
    (("fm", "sm", "financial", "strategic"), "Financial Management and Strategic Management"),
]


def _subject_canon(value: str) -> str:
    text = _norm(value)
    if text in ("", "all", "all subjects"):
        return ALL
    for canonical in SUBJECTS:
        if text == _norm(canonical):
            return canonical
    for keys, canonical in _SUBJECT_HINTS:
        if any(text.startswith(key) or f" {key}" in text or text == key for key in keys):
            return canonical
    return str(value or "").strip() or ALL


def _parse_day(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class EntryIn(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=240)
    hours: Optional[float] = Field(default=None, ge=0, le=24)
    mandatory: bool = True
    kind: str = Field(default="study", max_length=20)  # study | revision | test


class DayIn(BaseModel):
    day: int = Field(ge=1, le=90)
    entries: List[EntryIn] = Field(min_length=1, max_length=10)


class PlanIn(BaseModel):
    mode: Literal["calendar", "personal"] = "calendar"
    includedBackupDays: int = Field(default=1, ge=0, le=60)
    revisionBudgetMinutes: int = Field(default=30, ge=10, le=180)
    name: str = Field(min_length=1, max_length=120)
    startDate: str = Field(min_length=10, max_length=10)
    attempt: str = Field(default=ALL, max_length=80)
    group: str = Field(default=ALL, max_length=80)
    batch: str = Field(default=ALL, max_length=80)
    days: List[DayIn] = Field(min_length=1, max_length=90)


class DayEditIn(BaseModel):
    day: int = Field(ge=1, le=90)
    entries: List[EntryIn] = Field(min_length=1, max_length=10)


def _clean_entries(entries: List[EntryIn]) -> List[dict]:
    clean = []
    for item in entries:
        kind = _norm(item.kind) or "study"
        if kind not in ("study", "revision", "test"):
            kind = "study"
        label = (item.topic or "").strip()
        if item.hours:
            hours = item.hours
            label += f" ({int(hours) if hours == int(hours) else hours}hr)"
        if kind == "test" and "test" not in _norm(label):
            label += " (TEST)"
        clean.append({
            "subject": _subject_canon(item.subject),
            "topic": (item.topic or "").strip(),
            "hours": item.hours,
            "kind": kind,
            "label": label,
            "mandatory": item.mandatory,
        })
    return clean


def _group_by_subject(entries: List[dict]) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["subject"], []).append(entry)
    return groups


def _tasks_for(entries: List[dict], old_tasks: Optional[List[dict]] = None) -> List[dict]:
    old_ids = {(_norm(t.get("label") or ""), t.get("id")) for t in (old_tasks or [])}
    old_by_label = {label: tid for label, tid in old_ids if label}
    tasks = []
    for entry in entries:
        label = entry["label"]
        tasks.append({
            "id": old_by_label.get(_norm(label)) or "t-" + uuid.uuid4().hex[:10],
            "label": label,
            "detail": entry.get("topic") or "",
            "kind": _task_kind(label) if entry["kind"] != "test" else "test",
        })
    return tasks


def _target_doc(*, plan_id: str, day: int, date_iso: str, audience: dict, subject: str,
                tasks: List[dict], count: int) -> dict:
    return {
        "id": "dt-" + uuid.uuid4().hex[:12],
        "startDate": date_iso,
        "endDate": date_iso,
        "attempt": audience["attempt"],
        "group": audience["group"],
        "batch": audience["batch"],
        "subject": subject,
        "tasks": tasks,
        "revisionReminder": "",
        "reminderSource": "pending",
        "studentCount": count,
        "planId": plan_id,
        "planDay": day,
        "createdAt": _now(),
        "createdBy": "target-plan",
        "active": True,
    }


async def _gen_day_reminders(plan_id: str) -> None:
    """Background: one Groq reminder per plan day, stored on that day's targets."""
    db = get_db()
    plan = await db[PLANS].find_one({"id": plan_id}, {"_id": 0})
    if not plan:
        return
    for day in plan.get("days") or []:
        targets = (day.get("targets") or {}).values()
        if not targets:
            continue
        labels = [entry.get("label") for entry in day.get("entries") or [] if entry.get("label")]
        try:
            reminder, source = await _groq_reminder(ALL, [{"label": text} for text in labels])
        except HTTPException as exc:
            logger.warning("plan %s day %s reminder failed: %s", plan_id, day.get("day"), exc.detail)
            continue
        except Exception as exc:  # noqa: BLE001 — background job must never crash
            logger.warning("plan %s day %s reminder error: %s", plan_id, day.get("day"), exc)
            continue
        if source == "groq" and reminder.strip():
            await db[TARGETS].update_many(
                {"id": {"$in": list(targets)}},
                {"$set": {"revisionReminder": reminder, "reminderSource": "groq"}},
            )


def _mirror_rows(plans: List[dict]) -> List[List[object]]:
    rows: List[List[object]] = [[
        "Plan", "Day", "Date", "Batch", "Group", "Attempt", "Subject", "Topic", "Hours", "Type", "Mode", "Included backup days", "Revision budget minutes",
    ]]
    for plan in plans:
        for day in plan.get("days") or []:
            for entry in day.get("entries") or []:
                rows.append([
                    plan.get("name"), day.get("day"), day.get("date"),
                    plan.get("batch"), plan.get("group"), plan.get("attempt"),
                    entry.get("subject"), entry.get("topic"),
                    entry.get("hours") if entry.get("hours") is not None else "",
                    entry.get("kind"), plan.get("mode", "calendar"),
                    plan.get("includedBackupDays", 0), plan.get("revisionBudgetMinutes", 30),
                ])
    return rows


def _mirror_sheet(plans: List[dict]) -> str:
    """Best-effort rewrite of the 'Target Plans' tab. Never raises."""
    try:
        import requests
        from routers.notes_inbox import _google_token

        token = _google_token()
        base = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        head = {"Authorization": f"Bearer {token}"}
        meta = requests.get(base + "?fields=sheets.properties.title", headers=head, timeout=20)
        if meta.status_code >= 400:
            return f"sheet read failed ({meta.status_code})"
        titles = [s["properties"]["title"] for s in (meta.json().get("sheets") or [])]
        if SHEET_TAB not in titles:
            created = requests.post(
                base + ":batchUpdate",
                headers={**head, "Content-Type": "application/json"},
                json={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB}}}]},
                timeout=20,
            )
            if created.status_code >= 400:
                return f"tab create failed ({created.status_code})"
        values = _mirror_rows(plans)
        requests.post(
            base + f"/values/{SHEET_TAB}!A2:Z1000:clear",
            headers={**head, "Content-Type": "application/json"},
            json={},
            timeout=30,
        )
        put = requests.put(
            base + f"/values/{SHEET_TAB}!A1:M{len(values)}?valueInputOption=RAW",
            headers={**head, "Content-Type": "application/json"},
            json={"values": values},
            timeout=30,
        )
        if put.status_code >= 400:
            return f"sheet write failed ({put.status_code})"
        return "ok"
    except Exception as exc:  # noqa: BLE001 — mirror must never block publishing
        logger.warning("target plan sheet mirror failed: %s", exc)
        return f"skipped ({type(exc).__name__})"


async def _active_plans() -> List[dict]:
    db = get_db()
    cursor = db[PLANS].find({"status": "active"}, {"_id": 0}).sort("createdAt", -1)
    return await cursor.to_list(100)


def _public_plan(plan: dict) -> dict:
    return {key: plan.get(key) for key in (
        "id", "name", "startDate", "attempt", "group", "batch", "days",
        "status", "studentCount", "createdAt", "updatedAt", "cancelledAt",
        "mode", "includedBackupDays", "revisionBudgetMinutes",
    )}


@router.get("/api/target-plans")
async def list_plans(_mentor=Depends(require_mentor)):
    db = get_db()
    cursor = db[PLANS].find({}, {"_id": 0}).sort("createdAt", -1)
    rows = await cursor.to_list(100)
    return {"ok": True, "plans": [_public_plan(row) for row in rows]}


@router.post("/api/target-plans")
async def publish_plan(body: PlanIn, mentor=Depends(require_mentor)):
    start = _parse_day(body.startDate)
    if not start:
        raise HTTPException(status_code=400, detail="Start date must be YYYY-MM-DD.")
    seen = set()
    ordered: List[DayIn] = []
    for day in sorted(body.days, key=lambda row: row.day):
        if day.day in seen:
            raise HTTPException(status_code=400, detail=f"Day {day.day} is listed twice.")
        seen.add(day.day)
        ordered.append(day)
    first_day = ordered[0].day
    if [row.day for row in ordered] != list(range(first_day, first_day + len(ordered))):
        raise HTTPException(status_code=400, detail="Days must run consecutively from the first day number (e.g. 1,2,3 or 24,25,26).")

    students = await _students()
    if body.mode == "personal":
        from routers.smart_targets import _authoritative_students
        students = await _authoritative_students()
    audience = {"attempt": body.attempt or ALL, "group": body.group or ALL, "batch": body.batch or ALL}
    count = len([row for row in students if _audience_matches(row, audience)])
    if count == 0:
        raise HTTPException(status_code=400, detail="No students match this batch, group and attempt.")

    await _ensure_indexes()
    db = get_db()
    plan_id = "tp-" + uuid.uuid4().hex[:12]
    days: List[dict] = []
    total_targets = 0
    for row in ordered:
        date = start + timedelta(days=row.day - first_day)
        entries = _clean_entries(row.entries)
        days.append({
            "day": row.day,
            "date": date.isoformat(),
            "entries": entries,
            "targets": {},
        })
    plan = {
        "id": plan_id,
        "name": (body.name or "").strip(),
        "startDate": start.isoformat(),
        "attempt": audience["attempt"],
        "group": audience["group"],
        "batch": audience["batch"],
        "days": days,
        "status": "active",
        "studentCount": count,
        "createdAt": _now(),
        "createdBy": mentor.get("sub") or "mentor",
        "mode": body.mode,
        "includedBackupDays": body.includedBackupDays,
        "revisionBudgetMinutes": body.revisionBudgetMinutes,
    }
    if body.mode == "personal" and any(not any(e.get("mandatory", True) for e in d["entries"]) for d in days):
        raise HTTPException(400, "Every personal day needs a mandatory task.")
    await db[PLANS].insert_one(plan)
    if body.mode == "personal":
        mirror = await asyncio.to_thread(_mirror_sheet, await _active_plans())
        plan.pop("_id", None)
        return {"ok": True, "plan": _public_plan(plan), "studentCount": count,
                "targetsCreated": 0, "sheetMirror": mirror}

    for day in days:
        for subject, entries in _group_by_subject(day["entries"]).items():
            doc = _target_doc(
                plan_id=plan_id, day=day["day"], date_iso=day["date"],
                audience=audience, subject=subject,
                tasks=_tasks_for(entries), count=count,
            )
            await db[TARGETS].insert_one(doc)
            doc.pop("_id", None)
            day["targets"][subject] = doc["id"]
            total_targets += 1
    await db[PLANS].update_one({"id": plan_id}, {"$set": {"days": days}})

    asyncio.create_task(_gen_day_reminders(plan_id))
    mirror = await asyncio.to_thread(_mirror_sheet, await _active_plans())
    plan.pop("_id", None)
    return {
        "ok": True,
        "plan": _public_plan(dict(plan, days=days)),
        "studentCount": count,
        "targetsCreated": total_targets,
        "sheetMirror": mirror,
    }


# Groq retired BOTH Llama 4 vision models (Maverick 9-Mar-2026, Scout
# 17-Jul-2026), so the old hardcoded pair could never answer. qwen3.8-27b is
# Groq's current image-input model; GROQ_VISION_MODELS rotates the list without
# a rebuild if Groq retires this one too.
VISION_MODELS = tuple(
    m.strip() for m in (os.environ.get("GROQ_VISION_MODELS")
                        or "qwen/qwen3.8-27b").split(",") if m.strip()
)

_PARSE_PROMPT = (
    "Extract the study plan from this mentor poster or handwriting photo. "
    "Return ONLY minified JSON, exactly this shape: "
    '{"name":string,"group":""|"1"|"2","days":[{"day":1,"entries":[{"subject":string,'
    '"topic":string,"hours":number|null,"kind":"study"|"revision"|"test"}]}]}. '
    f"subject must be one of: {', '.join(SUBJECTS)} or \"All\". "
    "Map short names: Cost/Costing -> Cost and Management Accounting; Audit -> Auditing and Assurance; "
    "Accounts/AS -> Advanced Accounting; Law -> Corporate and Other Laws; Tax/GST/DT -> Taxation; "
    "FM/SM -> Financial Management and Strategic Management. "
    "Keep every 'Day N' block in order with one entry per subject line. "
    "A full-day revision line becomes {\"subject\":\"All\",\"topic\":\"Revision (full day)\","
    "\"hours\":1,\"kind\":\"revision\"}. Lines containing TEST use kind \"test\". "
    "Read hours from '(3hr)' style notes. No prose, no markdown fences."
)


def _extract_plan_json(text: str) -> Optional[dict]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = _json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_parsed_days(parsed: dict) -> List[dict]:
    out: List[dict] = []
    for row in (parsed.get("days") or [])[:MAX_DAYS]:
        if not isinstance(row, dict):
            continue
        entries_in = []
        for item in (row.get("entries") or [])[:10]:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue
            hours = item.get("hours")
            try:
                hours = float(hours) if hours not in (None, "") else None
            except (TypeError, ValueError):
                hours = None
            entries_in.append(EntryIn(
                subject=str(item.get("subject") or ALL).strip() or ALL,
                topic=topic[:240],
                hours=hours,
                kind=str(item.get("kind") or "study").lower(),
            ))
        if not entries_in:
            continue
        clean = _clean_entries(entries_in)
        out.append({
            "day": len(out) + 1,
            "entries": [{key: entry[key] for key in ("subject", "topic", "hours", "kind")} for entry in clean],
        })
    return out


@router.post("/api/target-plans/parse-photo")
async def parse_plan_photo(file: UploadFile = File(...), _mentor=Depends(require_mentor)):
    """Vision-parse a poster/handwriting photo into editable plan days."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The photo must be under 10 MB.")
    ctype = (file.content_type or "image/jpeg").lower()
    if ctype not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=415, detail="Only JPG, PNG or WEBP photos are supported.")
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Reading photos needs the Groq AI key, which is not configured on this server yet. "
                   "Your plan is not lost: type or paste the day rows instead - publishing does not need AI.",
        )

    import httpx

    encoded = base64.b64encode(data).decode()
    errors = []
    for model in VISION_MODELS:
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0,
                        "max_completion_tokens": 2048,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{encoded}"}},
                                {"type": "text", "text": _PARSE_PROMPT},
                            ],
                        }],
                    },
                )
            if resp.status_code != 200:
                errors.append(f"{model}: HTTP {resp.status_code}")
                continue
            text = ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            parsed = _extract_plan_json(text)
            days = _normalize_parsed_days(parsed) if parsed else []
            if not days:
                errors.append(f"{model}: no plan structure recognized")
                continue
            return {
                "ok": True,
                "name": str(parsed.get("name") or "").strip()[:120],
                "group": str(parsed.get("group") or "").strip(),
                "days": days,
                "model": model,
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — try the next vision model
            errors.append(f"{model}: {type(exc).__name__}")
            continue
    raise HTTPException(
        status_code=503,
        detail="The photo could not be parsed: " + "; ".join(errors)
        + " - if every model reported 400/404, Groq retired its vision model; set GROQ_VISION_MODELS to a "
          "current image-capable model id (see console.groq.com/docs/vision).",
    )


@router.patch("/api/target-plans/{plan_id}/day")
async def edit_plan_day(plan_id: str, body: DayEditIn, _mentor=Depends(require_mentor)):
    db = get_db()
    plan = await db[PLANS].find_one({"id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    if plan.get("status") != "active":
        raise HTTPException(status_code=400, detail="This plan is cancelled.")
    day = next((row for row in plan.get("days") or [] if row.get("day") == body.day), None)
    if not day:
        raise HTTPException(status_code=404, detail=f"Plan has no day {body.day}.")
    if plan.get("mode") == "personal":
        entries = _clean_entries(body.entries)
        if not any(e.get("mandatory", True) for e in entries):
            raise HTTPException(400, "Every personal day needs a mandatory task.")
        day["entries"] = entries
        await db[PLANS].update_one({"id": plan_id}, {"$set": {"days": plan["days"], "updatedAt": _now()}})
        mirror = await asyncio.to_thread(_mirror_sheet, await _active_plans())
        return {"ok": True, "plan": _public_plan(plan), "sheetMirror": mirror}
    if _parse_day(day.get("date") or "") < _today():
        raise HTTPException(status_code=400, detail="Only today or upcoming days can be edited.")

    entries = _clean_entries(body.entries)
    audience = {"attempt": plan.get("attempt"), "group": plan.get("group"), "batch": plan.get("batch")}
    old_targets: Dict[str, str] = dict(day.get("targets") or {})
    old_ids = list(old_targets.values())
    old_docs = await db[TARGETS].find({"id": {"$in": old_ids}}, {"_id": 0}).to_list(50)
    old_tasks = {doc.get("id"): doc.get("tasks") for doc in old_docs}

    new_targets: Dict[str, str] = {}
    for subject, subject_entries in _group_by_subject(entries).items():
        target_id = old_targets.get(subject)
        if target_id:
            tasks = _tasks_for(subject_entries, old_tasks.get(target_id))
            await db[TARGETS].update_one(
                {"id": target_id},
                {"$set": {"tasks": tasks, "active": True, "updatedAt": _now()}},
            )
        else:
            doc = _target_doc(
                plan_id=plan_id, day=body.day, date_iso=day["date"],
                audience=audience, subject=subject,
                tasks=_tasks_for(subject_entries), count=plan.get("studentCount") or 0,
            )
            await db[TARGETS].insert_one(doc)
            doc.pop("_id", None)
            target_id = doc["id"]
        new_targets[subject] = target_id
    removed = [tid for subject, tid in old_targets.items() if subject not in new_targets]
    if removed:
        await db[TARGETS].update_many(
            {"id": {"$in": removed}},
            {"$set": {"active": False, "removedAt": _now()}},
        )
    day["entries"] = entries
    day["targets"] = new_targets
    await db[PLANS].update_one(
        {"id": plan_id},
        {"$set": {"days": plan["days"], "updatedAt": _now()}},
    )
    asyncio.create_task(_gen_day_reminders(plan_id))
    mirror = await asyncio.to_thread(_mirror_sheet, await _active_plans())
    return {"ok": True, "plan": _public_plan(dict(plan, days=plan["days"])), "sheetMirror": mirror}


@router.post("/api/target-plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str, _mentor=Depends(require_mentor)):
    db = get_db()
    plan = await db[PLANS].find_one({"id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    if plan.get("status") != "active":
        raise HTTPException(status_code=400, detail="This plan is already cancelled.")
    today = _today()
    upcoming_ids = [
        tid
        for day in plan.get("days") or []
        if _parse_day(day.get("date") or "") and _parse_day(day["date"]) >= today
        for tid in (day.get("targets") or {}).values()
    ]
    if upcoming_ids:
        await db[TARGETS].update_many(
            {"id": {"$in": upcoming_ids}},
            {"$set": {"active": False, "removedAt": _now()}},
        )
    await db[PLANS].update_one(
        {"id": plan_id},
        {"$set": {"status": "cancelled", "cancelledAt": _now()}},
    )
    mirror = await asyncio.to_thread(_mirror_sheet, await _active_plans())
    return {"ok": True, "deactivatedTargets": len(upcoming_ids), "sheetMirror": mirror}
