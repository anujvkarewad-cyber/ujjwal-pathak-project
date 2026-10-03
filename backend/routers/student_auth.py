"""Student login against Mongo so 100–200 concurrent sign-ins do not hit Apps Script.

Passwords are stored as bcrypt hashes. A one-shot import copies the Students
sheet into Mongo. The Vercel proxy tries this API first, then falls back to
Apps Script only when the account is not in Mongo yet.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth import hash_password, require_mentor, verify_password
from config import settings
from db import STUDENT_ACCOUNTS, get_db

router = APIRouter(prefix="/api/student-auth", tags=["student-auth"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sept_2026_attempt(attempt: str, batch: str = "") -> bool:
    """Sept 2026 CA attempt only. Empty attempt is not treated as Sept 26."""
    if not str(attempt or "").strip():
        return False
    text = f"{attempt} {batch}".strip().lower()
    if re.search(r"sept(?:ember)?\s*20?26", text):
        return True
    if re.search(r"\bsep(?:t)?[\s./-]*26\b", text):
        return True
    return False


# ── Attempt-based access control ──────────────────────────────────────────
# App access is allowed ONLY for students whose attempt is the configured
# minimum or later. Earlier attempts are closed because their attempt is
# finished (e.g. Sept 2026 attempt done → closed now).
#   default minimum: Jan 2027 → "jan 27", "Jan 2027", "March 2027"… allowed
#                                 "sept 2026", "dec 26"… closed
# Override without code changes: ACCESS_MIN_ATTEMPT="YYYY-MM" (e.g. "2027-01").
IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _attempt_ym(attempt: str, batch: str = ""):
    """Parse month text or a sheet date (01/01/2027, 2027-01-01) into (year, month)."""
    for raw in (attempt, batch):
        s = str(raw or "").strip()
        iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if iso:
            month = int(iso.group(2))
            if 1 <= month <= 12:
                return (int(iso.group(1)), month)
        dmy = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", s)
        if dmy:
            month = int(dmy.group(2))
            if 1 <= month <= 12:
                return (int(dmy.group(3)), month)
        # Google Sheets can serialize a date as
        # "Fri Jan 01 2027 00:00:00 GMT+0530 (India Standard Time)".
        # Parse month-day-year before the generic month-year rule below;
        # otherwise that rule mistakes the day (01) for the year 2001 and
        # incorrectly closes a valid Jan/May 2027 student's access.
        sheet_date = re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
            r"\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(\d{4})\b",
            s.lower(),
        )
        if sheet_date:
            month = _MONTHS.get(sheet_date.group(1)[:3])
            if month is not None:
                return (int(sheet_date.group(2)), month)
    text = f"{attempt} {batch}".strip().lower()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s./-]*(\d{2,4})\b", text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1)[:3])
    if mon is None:
        return None
    year = int(m.group(2))
    if year < 100:
        year += 2000
    return (year, mon)


def _jan_2027_access_through() -> date:
    raw = (os.environ.get("JAN_2027_ACCESS_THROUGH") or "2027-01-20").strip()
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return date(2027, 1, 20)


def _attempt_access_allowed(
    attempt: str,
    batch: str = "",
    today: Optional[date] = None,
) -> bool:
    raw = (os.environ.get("ACCESS_MIN_ATTEMPT") or "2027-01").strip().split("-")
    try:
        min_ym = (int(raw[0]), int(raw[1]))
    except Exception:
        min_ym = (2027, 1)
    ym = _attempt_ym(attempt, batch)
    if ym is None or ym < min_ym:
        return False
    # Jan 2027 students retain access through 20 Jan 2027 in India. Closing
    # this cohort must not close May 2027 or any later eligible attempt.
    if ym == (2027, 1):
        ist_today = today or datetime.now(IST).date()
        return ist_today <= _jan_2027_access_through()
    return True


def _attempt_access_closed_message(attempt: str, batch: str = "") -> str:
    ym = _attempt_ym(attempt, batch)
    if ym == (2027, 1) and datetime.now(IST).date() > _jan_2027_access_through():
        return "Your Jan 2027 app access closed after 20 January 2027."
    return "Your attempt access is closed. The app is open for Jan 2027 attempt students onwards."


def normalize_student_id(raw: str) -> str:
    value = str(raw or "").strip().upper()
    if not value:
        return ""
    dup = re.match(r"^(UMP\d+)\1+$", value)
    if dup:
        value = dup.group(1)
    match = re.match(r"^UMP(\d+)$", value)
    if match:
        return "UMP" + match.group(1).zfill(4)
    return value


def _public_profile(doc: dict) -> dict:
    return {
        "success": True,
        "studentId": doc.get("studentId") or "",
        "studentName": doc.get("studentName") or "",
        "email": doc.get("email") or "",
        "caLevel": doc.get("caLevel") or "",
        "group": doc.get("group") or "",
        "attempt": doc.get("attempt") or "",
        "batch": doc.get("batch") or "",
        "phone": doc.get("phone") or "",
        "address": doc.get("address") or "",
        "joinedOn": doc.get("joinedOn") or "",
        "forcePasswordChange": bool(doc.get("forcePasswordChange")) or not bool(doc.get("passwordChanged")),
        "master": bool(doc.get("master")),
        "whatsapp": doc.get("whatsapp") or doc.get("phone") or "",
    }


def _password_ok(password: str, doc: dict) -> bool:
    hashed = str(doc.get("passwordHash") or "")
    if hashed:
        return verify_password(password, hashed)
    legacy = str(doc.get("password") or "")
    if not legacy:
        return False
    return password == legacy


def _extract_login(body: "StudentLoginBody") -> tuple[str, str]:
    payload = body.payload if isinstance(body.payload, dict) else {}
    student_id = normalize_student_id(body.studentId or payload.get("studentId") or "")
    password = str(body.password if body.password is not None else payload.get("password") or "").strip()
    return student_id, password


class StudentLoginBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: Optional[str] = None
    password: Optional[str] = Field(default=None, repr=False)
    action: Optional[str] = None
    payload: Optional[dict] = None


class StudentImportItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256, repr=False)
    studentName: str = ""
    email: str = ""
    caLevel: str = ""
    group: str = ""
    attempt: str = ""
    batch: str = ""
    phone: str = ""
    address: str = ""
    joinedOn: str = ""
    passwordChanged: Any = False


class StudentImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    students: list[StudentImportItem] = Field(default_factory=list, max_length=500)


class ChangePasswordBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: str = Field(min_length=1, max_length=64)
    currentPassword: str = Field(min_length=1, max_length=256, repr=False)
    newPassword: str = Field(min_length=1, max_length=256, repr=False)


async def authenticate_student(student_id: str, password: str) -> dict:
    """Mongo-only check. Never calls Apps Script (avoids proxy loops)."""
    sid = normalize_student_id(student_id)
    pwd = str(password or "").strip()
    if not sid or not pwd:
        return {"success": False, "message": "Student ID or password is incorrect.", "code": "invalid"}
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {"success": False, "message": "Student ID not found.", "code": "not_found"}
    if not _password_ok(pwd, doc):
        return {"success": False, "message": "Incorrect password.", "code": "wrong_password"}
    # Master accounts (mentor's own app IDs) always have full access,
    # regardless of the attempt-based access rule.
    if doc.get("master"):
        return _public_profile(doc)
    if not _attempt_access_allowed(str(doc.get("attempt") or ""), str(doc.get("batch") or "")):
        return {
            "success": False,
            "message": _attempt_access_closed_message(
                str(doc.get("attempt") or ""),
                str(doc.get("batch") or ""),
            ),
            "code": "group_closed",
        }
    if doc.get("password") and not doc.get("passwordHash"):
        await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid},
            {"$set": {"passwordHash": hash_password(pwd)}, "$unset": {"password": ""}},
        )
    return _public_profile(doc)


async def upsert_student_account(item: StudentImportItem) -> None:
    sid = normalize_student_id(item.studentId)
    pwd = str(item.password or "").strip()
    if not sid or not pwd:
        return
    changed = item.passwordChanged
    password_changed = str(changed).strip().lower() in {"1", "true", "yes", "y"}
    db = get_db()
    existing = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}) or {}
    keep_password = bool(existing.get("passwordChanged")) and bool(existing.get("passwordHash"))
    fields = {
        "studentId": sid,
        "studentName": (item.studentName or "").strip(),
        "email": (item.email or "").strip(),
        "caLevel": (item.caLevel or "").strip(),
        "group": (item.group or "").strip(),
        "attempt": (item.attempt or "").strip(),
        "batch": (item.batch or "").strip(),
        "phone": (item.phone or "").strip(),
        "address": (item.address or "").strip(),
        "joinedOn": (item.joinedOn or "").strip(),
        "updatedAt": _now(),
    }
    if not keep_password:
        fields["passwordHash"] = hash_password(pwd)
        fields["passwordChanged"] = password_changed
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": fields,
            "$unset": {"password": ""},
            "$setOnInsert": {"createdAt": _now()},
        },
        upsert=True,
    )


def _import_allowed(request: Request) -> bool:
    if settings.dev_auth_bypass:
        return True
    header = (request.headers.get("X-UMP-Import") or "").strip()
    expected = (getattr(settings, "student_import_key", "") or "").strip()
    if expected and header and header == expected:
        return True
    return False


@router.get("/status")
async def student_auth_status():
    db = get_db()
    count = await db[STUDENT_ACCOUNTS].count_documents({})
    return {"ok": True, "accounts": count}


@router.post("/login")
async def student_login(body: StudentLoginBody):
    student_id, password = _extract_login(body)
    result = await authenticate_student(student_id, password)
    return {"result": result}


@router.post("/change-password")
async def student_change_password(body: ChangePasswordBody):
    sid = normalize_student_id(body.studentId)
    current = str(body.currentPassword or "").strip()
    new_pwd = str(body.newPassword or "").strip()
    if not sid or not current or not new_pwd:
        return {"result": {"success": False, "message": "Student not found."}}
    if len(new_pwd) < 6:
        return {"result": {"success": False, "message": "New password is too short."}}
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {"result": {"success": False, "message": "Student not found.", "code": "not_found"}}
    if not _password_ok(current, doc):
        return {"result": {"success": False, "message": "Current password is incorrect."}}
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": {
                "passwordHash": hash_password(new_pwd),
                "passwordChanged": True,
                "forcePasswordChange": False,
                "updatedAt": _now(),
            },
            "$unset": {"password": ""},
        },
    )
    return {"result": {"success": True, "message": "Password changed."}}


@router.post("/import")
async def import_students(body: StudentImportBody, request: Request):
    if not _import_allowed(request):
        try:
            await require_mentor(request)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Import not allowed")
    upserted = 0
    for item in body.students:
        if not str(item.password or "").strip():
            continue
        await upsert_student_account(item)
        upserted += 1
    return {"ok": True, "upserted": upserted}


@router.get("/account-reset-status")
async def account_reset_status(request: Request):
    """Mentor-only: has the four-account emergency reset already run?"""
    from account_reset import MARKER_KEY, RESET_STUDENT_IDS, marker_doc

    if not settings.dev_auth_bypass:
        await require_mentor(request)
    doc = await marker_doc()
    if doc:
        doc.pop("_id", None)
    return {
        "key": MARKER_KEY,
        "studentIds": list(RESET_STUDENT_IDS),
        "applied": bool(doc),
        "marker": doc,
    }


@router.post("/account-reset")
async def run_account_reset(request: Request, force: bool = False):
    """Mentor-only manual trigger for the idempotent four-account reset."""
    from account_reset import reset_accounts

    if not settings.dev_auth_bypass:
        await require_mentor(request)
    return await reset_accounts(force=force)


class SaveWhatsAppBody(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    number: str = Field(min_length=6, max_length=20)


@router.post("/whatsapp")
async def save_whatsapp(body: SaveWhatsAppBody):
    """Student saves their own WhatsApp number (used for enrollment welcome,
    reminders and announcements)."""
    from whatsapp import normalize_number

    sid = normalize_student_id(body.studentId)
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {"result": {"success": False, "message": "Student ID not found."}}
    num = normalize_number(body.number)
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {"$set": {"whatsapp": num, "phone": num, "updatedAt": _now()}},
    )
    return {"result": {"success": True, "whatsapp": num}}


class ReminderNotifyBody(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=300)


@router.post("/reminder-notify")
async def reminder_notify(body: ReminderNotifyBody):
    """Mirror a student reminder to their saved WhatsApp number."""
    from whatsapp import normalize_number, send_whatsapp

    sid = normalize_student_id(body.studentId)
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {"result": {"success": False, "message": "Student ID not found."}}
    raw = str(doc.get("whatsapp") or doc.get("phone") or "").strip()
    if not raw:
        return {"result": {"success": False, "message": "No WhatsApp number saved yet."}}
    ok = await send_whatsapp(normalize_number(raw), f"Reminder: {body.text}", purpose="reminder")
    return {"result": {"success": bool(ok)}}
