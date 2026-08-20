"""Student dashboard reads/writes on Mongo, with sheet import merge."""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth import require_mentor
from config import settings
from db import DASHBOARD_SHARED, DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db
from routers.student_auth import normalize_student_id

router = APIRouter(prefix="/api/student-dashboard", tags=["student-dashboard"])

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
    seen = set()
    out = []
    for row in list(new or []) + list(old or []):
        if not isinstance(row, dict):
            continue
        try:
            hours = round(float(row.get("hours") or 0), 2)
        except (TypeError, ValueError):
            hours = 0.0
        key = (
            str(row.get("date") or "")[:10],
            str(row.get("topic") or row.get("subjects") or ""),
            hours,
            str(row.get("proof") or "")[:80],
        )
        if key in seen or (not key[0] and not hours):
            continue
        seen.add(key)
        out.append({
            "date": key[0],
            "topic": str(row.get("topic") or row.get("subjects") or ""),
            "hours": hours,
            "proof": str(row.get("proof") or ""),
        })
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
    return {
        "totalHours": round(total, 2),
        "monthlyHours": round(month_h, 2),
        "weeklyHours": round(week_h, 2),
        "todayHours": round(today_h, 2),
        "averageHours": round(total / entries, 2) if entries else 0,
        "totalEntries": entries,
        "lastSubmission": last_sub,
        "last7": [round(x, 1) for x in last7],
        "streak": int(prev.get("streak") or 0),
        "rank": int(prev.get("rank") or 0),
        "weeklyRank": int(prev.get("weeklyRank") or 0),
        "monthlyRank": int(prev.get("monthlyRank") or 0),
    }


async def _rebuild_leaderboard(db) -> None:
    names = {}
    async for account in db[STUDENT_ACCOUNTS].find({}):
        sid = account.get("studentId")
        if sid:
            names[sid] = account.get("studentName") or sid
    rows = []
    async for doc in db[DASHBOARD_STUDENTS].find({}):
        sid = doc.get("studentId")
        if not sid:
            continue
        stats = doc.get("stats") or {}
        rows.append({
            "studentId": sid,
            "studentName": names.get(sid) or sid,
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
        shared_set["announcements"] = body.announcements
    if body.notes is not None:
        shared_set["notes"] = body.notes
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
        }
        if item.reports is not None:
            doc["reports"] = item.reports
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
        return {"found": True, "result": shared.get(SHARED_ACTIONS[action]) or []}

    if action == "notes.listForStudent":
        student_doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id}) if student_id else None
        if student_doc and isinstance(student_doc.get("notes"), list):
            return {"found": True, "result": student_doc.get("notes") or []}
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"})
        if not shared or "notes" not in shared:
            return {"found": False}
        account = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id}) if student_id else None
        return {"found": True, "result": _notes_for_student(shared.get("notes") or [], account)}

    field = PERSONAL_ACTIONS.get(action)
    if not field or not student_id:
        return {"found": False}
    doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id})
    if not doc or field not in doc:
        return {"found": False}
    value = doc.get(field)
    if field == "stats":
        logs = doc.get("studyLog") if isinstance(doc.get("studyLog"), list) else []
        if logs:
            value = _recompute_stats(logs, value if isinstance(value, dict) else {})
        return {"found": True, "result": value or {}}
    return {"found": True, "result": value or []}


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
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "studyLog": logs, "stats": stats, "updatedAt": now}},
            upsert=True,
        )
        await _rebuild_leaderboard(db)
        return {"ok": True, "success": True, "proofUrl": proof, "stats": stats}

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
        announcements = [item] + list(shared.get("announcements") or [])
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
        notes = [item] + list(shared.get("notes") or [])
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
