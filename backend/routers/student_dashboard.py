"""Student dashboard reads from Mongo so 8 parallel Apps Script calls stop.

Import copies announcements, leaderboard, notes, stats, logs, reports and
mentor notes from the Students spreadsheet. The Vercel proxy asks this API
first and only falls back to Google when a section has not been imported yet.
"""
from datetime import datetime, timezone
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if body.leaderboard is not None:
        shared_set["leaderboard"] = body.leaderboard
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
        doc = {
            "studentId": sid,
            "updatedAt": _now(),
        }
        if item.stats is not None:
            doc["stats"] = item.stats
        if item.studyLog is not None:
            doc["studyLog"] = item.studyLog
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
    if not field:
        return {"found": False}
    if not student_id:
        return {"found": False}
    doc = await db[DASHBOARD_STUDENTS].find_one({"studentId": student_id})
    if not doc or field not in doc:
        return {"found": False}
    value = doc.get(field)
    if field == "stats":
        return {"found": True, "result": value or {}}
    return {"found": True, "result": value or []}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _last7_index(iso_date: str) -> int:
    try:
        day = datetime.fromisoformat(str(iso_date)[:10]).date()
    except ValueError:
        day = datetime.now(timezone.utc).date()
    return (day.weekday() + 1) % 7


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
        logs = [row] + [x for x in (doc.get("studyLog") or []) if isinstance(x, dict)]
        stats = dict(doc.get("stats") or {})
        prev_total = float(stats.get("totalHours") or 0)
        prev_entries = int(stats.get("totalEntries") or 0)
        last7 = list(stats.get("last7") or [0, 0, 0, 0, 0, 0, 0])
        while len(last7) < 7:
            last7.append(0)
        idx = _last7_index(entry_date)
        last7[idx] = float(last7[idx] or 0) + hours
        today = _today()
        stats.update({
            "todayHours": hours if entry_date == today else float(stats.get("todayHours") or 0),
            "weeklyHours": float(stats.get("weeklyHours") or 0) + hours,
            "monthlyHours": float(stats.get("monthlyHours") or 0) + hours,
            "totalHours": prev_total + hours,
            "totalEntries": prev_entries + 1,
            "averageHours": round((prev_total + hours) / max(prev_entries + 1, 1), 2),
            "lastSubmission": entry_date,
            "last7": last7,
        })
        await db[DASHBOARD_STUDENTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "studyLog": logs[:400], "stats": stats, "updatedAt": now}},
            upsert=True,
        )
        return {"ok": True, "success": True, "proofUrl": proof}

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
    return {"ok": True, "result": applied.get("result") or {"success": True, "proofUrl": applied.get("proofUrl")}}
