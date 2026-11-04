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
import re as _re
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
MAX_DAYS = 40
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


def _ai_photo_ready() -> bool:
    return bool((os.environ.get("GROQ_API_KEY") or "").strip())


@router.get("/api/target-plans")
async def list_plans(_mentor=Depends(require_mentor)):
    db = get_db()
    cursor = db[PLANS].find({}, {"_id": 0}).sort("createdAt", -1)
    rows = await cursor.to_list(100)
    return {
        "ok": True,
        "plans": [_public_plan(row) for row in rows],
        # The page uses this to hide/disable the photo button instead of showing a
        # scary error banner on every load when the AI key is absent.
        "capabilities": {"aiPhotoReading": _ai_photo_ready()},
    }


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
    "If a day lists two different topics with their own hours, keep them as separate entries - never merge "
    "two lines into one entry. Copy the hours written next to each topic. "
    "Include backup/extra days as their own days. "
    "A full-day revision line becomes {\"subject\":\"All\",\"topic\":\"Revision (full day)\","
    "\"hours\":1,\"kind\":\"revision\"}. Lines containing TEST use kind \"test\". "
    "Read hours from '(3hr)' style notes. No prose, no markdown fences. "
    "The JSON must be complete: finish every object and array you open."
)


def _close_truncated_json(text: str) -> Optional[str]:
    """Finish a JSON document the model stopped writing mid-way.

    Qwen answers with `finish_reason: "stop"` yet often omits the final `}` (or the
    last few closers) on long answers. Rebalancing the brackets recovers the whole
    plan instead of rejecting a photo that was read correctly.
    """
    body = text.strip()
    if not body:
        return None
    # Walk once to learn what is still open, ignoring brackets inside strings.
    stack, in_string, escaped = [], False, False
    for ch in body:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
    if not stack and not in_string:
        return body                      # already balanced
    candidate = body + ('"' if in_string else "")
    candidate += "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return candidate


def _trimmed_variants(text: str, tries: int = 6) -> List[str]:
    """Cut back to earlier boundaries, then re-close — for answers cut mid-value."""
    out: List[str] = []
    body = text.rstrip()
    for _ in range(tries):
        cut = max(body.rfind(","), body.rfind("{"), body.rfind("["))
        if cut <= 0:
            break
        body = body[:cut]
        closed = _close_truncated_json(body)
        if closed:
            out.append(closed)
    return out


def _extract_plan_json(text: str) -> Optional[dict]:
    """Pull a plan object out of whatever the model returned.

    Vision models sometimes wrap JSON in ``` fences, add prose before/after, emit
    trailing commas, or answer with a bare list of days. All of that is recovered
    here instead of failing the mentor's upload.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if "```" in cleaned:                       # ```json ... ``` or ``` ... ```
        parts = cleaned.split("```")
        for part in parts:
            body = part.strip()
            if body.lower().startswith("json"):
                body = body[4:].strip()
            if body.startswith("{") or body.startswith("["):
                cleaned = body
                break
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start:end + 1])
    for chunk in list(candidates):
        candidates.append(_re.sub(r",\s*([}\]])", r"\1", chunk))   # trailing commas
        closed = _close_truncated_json(chunk)                       # cut-off answer
        if closed and closed != chunk:
            candidates.append(closed)
            candidates.extend(_trimmed_variants(chunk))
    for chunk in candidates:
        try:
            parsed = _json.loads(chunk)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            # tolerate {"plan": {...}} / {"result": {...}} wrappers
            for wrapper in ("plan", "result", "data"):
                inner = parsed.get(wrapper)
                if isinstance(inner, dict) and ("days" in inner or "entries" in inner):
                    return inner
            return parsed
        if isinstance(parsed, list):
            return {"days": parsed}
    return None


def _entries_from_row(row: dict) -> List[dict]:
    """A day may carry entries/tasks/topics, a single flat entry, or bare strings."""
    raw = row.get("entries") or row.get("tasks") or row.get("topics") or row.get("rows")
    if raw is None and (row.get("topic") or row.get("subject")):
        raw = [row]                                   # flat {day, subject, topic}
    if isinstance(raw, str):
        raw = [raw]
    out: List[dict] = []
    for item in (raw or [])[:10]:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append({"topic": text})
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _coerce_entries(items: List) -> List[EntryIn]:
    """Plain dicts (from a model) -> validated EntryIn objects, skipping junk."""
    out: List[EntryIn] = []
    for item in items:
        if isinstance(item, EntryIn):
            out.append(item)
            continue
        if not isinstance(item, dict):
            item = {"topic": str(item)}
        fields = {k: v for k, v in item.items() if k in EntryIn.model_fields}
        fields["subject"] = str(fields.get("subject") or "").strip() or "All"
        fields["topic"] = str(fields.get("topic") or fields.get("label") or "").strip()
        if not fields["topic"]:
            continue
        try:
            out.append(EntryIn(**fields))
        except Exception:  # noqa: BLE001 — one bad row must not kill the whole photo
            continue
    return out


def _normalize_parsed_days(parsed: dict) -> List[dict]:
    rows = parsed.get("days")
    if rows is None and isinstance(parsed.get("entries"), list):   # one day, no wrapper
        rows = [parsed]
    out: List[dict] = []
    for index, row in enumerate((rows or [])[:MAX_DAYS], start=1):
        if not isinstance(row, dict):
            continue
        entries_in = _entries_from_row(row)
        if not entries_in:
            continue
        clean = _clean_entries(_coerce_entries(entries_in))
        if not clean:
            continue
        out.append({
            "day": len(out) + 1,
            "entries": [{key: entry[key] for key in ("subject", "topic", "hours", "kind")} for entry in clean],
        })
    return out


_MAX_429_WAIT = 25.0


def _retry_after_seconds(resp) -> float:
    """Groq sends Retry-After, or an 'in 12.5s' hint in the message."""
    header = (resp.headers.get("retry-after") or "").strip()
    try:
        if header:
            return float(header)
    except ValueError:
        pass
    match = _re.search(r"try again in ([0-9.]+)\s*s", resp.text or "", _re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0
    return 0.0


def _shrink_for_vision(data: bytes, ctype: str, max_side: int = 1400) -> tuple:
    """Downscale before upload.

    Vision tokens scale with pixels, and Groq's free tier counts the prompt against
    its per-minute budget. A 1086x1448 phone photo becomes ~1400px on the long edge,
    which still reads handwriting but costs a fraction of the tokens. Any failure
    just returns the original bytes — a sharp photo must never be rejected here.
    """
    try:
        from PIL import Image  # Pillow is already a backend dependency
        import io as _io

        img = Image.open(_io.BytesIO(data))
        img.load()
        if max(img.size) <= max_side:
            return data, ctype
        ratio = max_side / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        # Judge by pixels, not bytes: vision cost scales with resolution, and a
        # re-encoded JPEG can be a few KB larger than the original while still
        # being far cheaper to read.
        return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 — never block a photo because of a resize
        return data, ctype


_REPAIR_PROMPT = (
    "The text below was supposed to describe a study plan. Convert it to minified JSON with exactly this "
    'shape and nothing else: {"name":string,"group":""|"1"|"2","days":[{"day":1,"entries":'
    '[{"subject":string,"topic":string,"hours":number|null,"kind":"study"|"revision"|"test"}]}]}. '
    "If a day has no subject, use \"All\". Never add commentary."
)


async def _repair_plan_json(client, key: str, model: str, raw_text: str) -> str:
    """Ask the model to turn its own prose/broken JSON into the exact schema."""
    try:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0,
                "max_completion_tokens": 2048,
                "messages": [{"role": "user", "content": _REPAIR_PROMPT + "\n\nTEXT:\n" + raw_text[:6000]}],
            },
        )
        if resp.status_code != 200:
            return ""
        return ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception:  # noqa: BLE001 — a failed repair just means we report the original error
        return ""


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
            detail="Photo reading is not set up on this server yet. Type or paste the day rows instead - "
                   "publishing a plan does not need AI.",
        )

    data, ctype = _shrink_for_vision(data, ctype)

    import httpx

    encoded = base64.b64encode(data).decode()
    errors = []
    for model in VISION_MODELS:
        try:
            payload = {
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
            }
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code == 429:
                wait = _retry_after_seconds(resp)
                if wait and wait <= _MAX_429_WAIT:
                    await asyncio.sleep(wait)
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json=payload,
                    )
            if resp.status_code == 429:
                errors.append(
                    "AI rate limit reached (Groq allows only a few photo reads per minute on the free plan)"
                )
                continue
            if resp.status_code != 200:
                errors.append(f"{model}: HTTP {resp.status_code}")
                continue
            choice = (resp.json().get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            parsed = _extract_plan_json(text)
            days = _normalize_parsed_days(parsed) if parsed else []
            if not days and text.strip():
                # Second chance: the model described the plan in prose or emitted
                # broken JSON. Ask it once more, text only, to reformat.
                repaired = await _repair_plan_json(client, key, model, text)
                parsed = _extract_plan_json(repaired)
                days = _normalize_parsed_days(parsed) if parsed else []
            if not days:
                snippet = " ".join(text.split())[:160]
                errors.append(f"{model}: no plan structure recognized" + (f" (model said: {snippet!r})" if snippet else ""))
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
        detail="The photo could not be read: " + "; ".join(errors)
        + (". Wait about a minute and press Fill from photo again." if any("rate limit" in e for e in errors)
           else ". Try a sharper photo of just the day table (whole page in frame, no glare), or type the "
                "rows by hand - publishing does not need AI."),
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
