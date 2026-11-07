"""Student login against Mongo so 100–200 concurrent sign-ins do not hit Apps Script.

Passwords are stored as bcrypt hashes. A one-shot import copies the Students
sheet into Mongo. The Vercel proxy tries this API first, then falls back to
Apps Script only when the account is not in Mongo yet.
"""
import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from routers.dashboard_access import dashboard_student, own_payload
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth import hash_password, require_mentor, verify_password
import sheet_coverage
from config import settings
import login_failures
import password_sheet_sync

logger = logging.getLogger(__name__)
from db import STUDENT_ACCOUNTS, STUDENT_ADMIN_AUDIT, get_db

router = APIRouter(prefix="/api/student-auth", tags=["student-auth"])

# Enrollment batch values are deliberately closed, rather than accepting
# arbitrary mentor-entered text. These labels must match the Google Form.
ALLOWED_STUDENT_BATCHES = (
    "Before Result Batch 1",
    "Before Result Batch 2",
    "After Result Batch 1",
    "After Result Batch 2",
    "After Result Batch 1 with Classes",
)


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
    """Read a student ID the way a student types it.

    Students far more often mistype the two letters of the prefix than the
    digits: on 04-Nov-2026, 15 of the 37 open failed logins were exactly this -
    "UPM0092" (letters swapped), "UMPO350" (letter O instead of zero, tried 8
    times) or "UMP00092" (one zero too many). Those were reported to the student
    as "Student ID not found" even though the account existed.

    Only the prefix, the letter O and surplus leading zeros are repaired; the
    digits themselves are never guessed, so a real wrong ID still fails.
    """
    value = str(raw or "").strip().upper()
    if not value:
        return ""
    dup = re.match(r"^(UMP\d+)\1+$", value)
    if dup:
        value = dup.group(1)
    candidate = re.sub(r"^U[MPO]{2}(?=[0-9O])", "UMP", value)  # UPM / UMM / UMO prefixes
    candidate = re.sub(r"^(UMP)([0-9O]+)$", lambda m: m.group(1) + m.group(2).replace("O", "0"), candidate)
    match = re.match(r"^UMP(\d+)$", candidate)
    if match:
        digits = match.group(1).lstrip("0") or "0"
        return "UMP" + digits.zfill(4)
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
    # Trusted Sheet/Apps-Script imports normally preserve a password that the
    # student already changed. Account recovery is the one explicit exception:
    # after a verified OTP, the reset service must be allowed to replace that
    # existing hash. This flag is accepted only on the import-key/mentor-
    # protected /import route; public login/change-password cannot set it.
    forcePasswordReset: bool = False


class StudentImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    students: list[StudentImportItem] = Field(default_factory=list, max_length=2000)


class StudentBatchChangeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    batch: str = Field(min_length=1, max_length=80)
    # Optimistic concurrency: the mentor UI sends the batch it displayed. If
    # another mentor changed it in the meantime, Apps Script rejects the stale
    # write instead of silently overwriting the newer choice.
    expectedBatch: str = Field(default="", max_length=80)


class ChangePasswordBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: str = Field(min_length=1, max_length=64)
    currentPassword: str = Field(min_length=1, max_length=256, repr=False)
    newPassword: str = Field(min_length=1, max_length=256, repr=False)


def _plausible_login_id(raw) -> str:
    """An id worth recording a failure against: uppercase, long enough, has a digit.

    Someone typing rubbish at the login screen must not create a row the mentor then
    has to ignore, but a real-looking id that simply has no account yet is exactly what
    the mentor needs to see (that student is trying to get in).
    """
    sid = str(raw or "").strip().upper()
    if len(sid) < 6 or not any(ch.isdigit() for ch in sid):
        return ""
    return sid[:24]


async def authenticate_student(student_id: str, password: str) -> dict:
    """Login check + a record of whether it worked.

    The outcome is the whole point of the mentor's Password Reset tab: a student being
    told "Incorrect password" used to leave no trace at all. Recorded here rather than
    in one route, because the app and the proxy path both come through this function.
    """
    result = await _check_credentials(student_id, password)
    try:
        ok = isinstance(result, dict) and bool(result.get("success"))
        sid = normalize_student_id(student_id) if ok else _plausible_login_id(student_id)
        if sid:
            login_failures.note_attempt(sid, ok, "" if ok else str(result.get("code") or ""))
    except Exception as exc:  # noqa: BLE001 - an auth result must never depend on bookkeeping
        logger.warning("[login-failures] bookkeeping skipped (%s)", type(exc).__name__)
    return result


async def _check_credentials(student_id: str, password: str) -> dict:
    """Mongo-only check. Never calls Apps Script (avoids proxy loops)."""
    sid = normalize_student_id(student_id)
    pwd = str(password or "").strip()
    if not sid or not pwd:
        return {"success": False, "message": "Student ID or password is incorrect.", "code": "invalid"}
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {
            "success": False,
            "message": "Student ID not found. Your ID is UMP followed by 4 digits, e.g. UMP0123.",
            "code": "not_found",
        }
    # Soft-removed students (mentor removed them from the program) cannot log
    # in. Their data is kept so a mentor restore brings the account back.
    if doc.get("removedAt") or str(doc.get("status") or "").strip().lower() == "removed":
        return {
            "success": False,
            "message": "This account has been removed from the program. Please contact your mentor.",
            "code": "removed",
        }
    # Mentor-controlled access OFF (restored 2026-10-13 — the owner flow that
    # blocks non-studious students with a visible reason). The message is what
    # every app client shows on the login screen.
    if doc.get("accessEnabled") is False:
        reason = str(doc.get("accessReason") or "").strip()
        detail = f" Reason: {reason}." if reason else ""
        return {
            "success": False,
            "message": (
                "Your app access is turned off by your mentor."
                + detail
                + " Contact your mentor to turn it back on."
            ),
            "code": "access_blocked",
            "reason": reason,
        }
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
    force_password_reset = bool(item.forcePasswordReset)
    keep_password = (
        bool(existing.get("passwordChanged"))
        and bool(existing.get("passwordHash"))
        and not force_password_reset
    )
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
        "updatedAt": _now(),
    }
    # joinedOn drives the per-student tracker start. Never blank a stored date:
    # an import row without a join date keeps what is already known, and a brand
    # new account defaults to today — the day the student was added (IST).
    joined = (item.joinedOn or "").strip() or str(existing.get("joinedOn") or "").strip()
    fields["joinedOn"] = joined or datetime.now(IST).date().isoformat()
    if not keep_password:
        fields["passwordHash"] = hash_password(pwd)
        fields["passwordChanged"] = password_changed
        if force_password_reset:
            # A self-service reset chooses the final password (changed=True),
            # while a mentor-issued temporary password (changed=False) must be
            # changed on next login.
            fields["forcePasswordChange"] = not password_changed
            fields["sheetPasswordResyncPending"] = False
            fields["passwordResetAt"] = _now()
            fields["passwordResetBy"] = "trusted_password_reset_import"
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


async def _change_sheet_batch(
    student_id: str,
    batch: str,
    expected_batch: str = "",
) -> dict:
    """Update the authoritative Students sheet through its owner-authorized
    Apps Script. The shared import key stays server-side and never reaches the
    mentor browser."""
    url = (getattr(settings, "student_admin_script_url", "") or "").strip()
    key = (getattr(settings, "student_import_key", "") or "").strip()
    if not url or not key:
        raise HTTPException(status_code=503, detail="Student batch management is not configured.")

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.post(
                url,
                json={
                    "action": "mentorChangeBatch",
                    "payload": {
                        "studentId": student_id,
                        "batch": batch,
                        "expectedBatch": expected_batch,
                        "adminKey": key,
                    },
                },
            )
        response.raise_for_status()
        envelope = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Students Sheet could not be updated. No Mongo change was made.",
        ) from exc

    result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Students Sheet returned an invalid response. No Mongo change was made.")
    if result.get("success"):
        return result
    code = str(result.get("code") or "")
    if code == "not_found":
        raise HTTPException(status_code=404, detail="Student ID was not found in the Students Sheet.")
    if code == "batch_conflict":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This student's batch changed after the page was opened. Refresh and try again.",
                "currentBatch": str(result.get("currentBatch") or ""),
            },
        )
    if code == "unauthorized":
        raise HTTPException(status_code=502, detail="Students Sheet rejected the protected update. Check server configuration.")
    raise HTTPException(status_code=502, detail="Students Sheet rejected the batch change. No Mongo change was made.")


@router.get("/status")
async def student_auth_status():
    db = get_db()
    count = await db[STUDENT_ACCOUNTS].count_documents({})
    return {"ok": True, "accounts": count}


@router.post("/login")
async def student_login(body: StudentLoginBody):
    student_id, password = _extract_login(body)
    result = await authenticate_student(student_id, password)
    # The sheet is the mentor's credential ledger, and a password a student
    # changed in the app is otherwise unknowable. A successful login is the one
    # request that proves the value, so the sheet is refreshed here - off the
    # response path, and never for a failed attempt.
    if isinstance(result, dict) and result.get("success"):
        password_sheet_sync.queue_sync(student_id, password)
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
    password_sheet_sync.queue_sync(sid, new_pwd, flag_changed=True)
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


@router.patch("/students/{student_id}/batch")
async def change_student_batch(
    student_id: str,
    body: StudentBatchChangeBody,
    claims: dict = Depends(require_mentor),
):
    """Compatibility route: authoritative moves now require reviewed batch+group.

    Preserve the route and action via the workspace, but never let a stale mentor
    client bypass CAS, durable locks or the no-automatic-rollback safety contract.
    """
    sid = normalize_student_id(student_id)
    if not re.fullmatch(r"UMP\d{4,}", sid):
        raise HTTPException(400, "Invalid Student ID.")
    if str(body.batch or "").strip() not in ALLOWED_STUDENT_BATCHES:
        raise HTTPException(400, {"message": "Choose a valid batch.", "allowedBatches": list(ALLOWED_STUDENT_BATCHES)})
    raise HTTPException(409, {"code": "reviewed_membership_required", "message": "Use the reviewed batch/group workspace. Nothing changed.", "workspace": "/batches?studentId=" + sid + "&action=transfer"})


# ── Students sheet ⇄ Mongo batch drift ──────────────────────────────────────
# A student's own profile (APK and webapp) shows what validateLogin returns, and
# validateLogin is served by Apps Script - that is, from the Students sheet.
# Every audience decision (which test, which notes, which daily target, which
# push, which batch rank) is taken from Mongo instead. So a batch typed by hand
# into the sheet shows up nowhere and quietly keeps sending a student the other
# batch's material. These two routes make that gap visible and let the mentor
# close it in one click, without touching passwords or any other profile field.

STUDENTS_SHEET_ID = os.environ.get(
    "TRACKER_SHEET_ID", "1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc"
).strip()
BATCH_DRIFT_TTL_SEC = 90
_drift_cache: dict = {"at": None, "payload": None}

# Master/test accounts are not students; their sheet row does not exist on
# purpose and their batch is intentionally "ALL".
BATCH_DRIFT_SKIP_IDS = {"UMP0000", "UMP9999"}


def batch_drift_rows(sheet_rows: list, accounts: list) -> dict:
    """Compare the sheet's Batch column with the Mongo account batch.

    Pure on purpose: this is the whole rule, so it is testable without Google.
    Returns {"drift": [...], "needsImport": [...], "skipped": {...}} where a
    drift row carries both values so the mentor can see who is right.
    """
    if not sheet_rows:
        return {"drift": [], "needsImport": [], "skipped": {"noHeader": True}}
    header = [str(cell or "").strip().lower() for cell in sheet_rows[0]]
    try:
        id_col = header.index("student id")
        batch_col = header.index("batch")
    except ValueError:
        return {"drift": [], "needsImport": [], "skipped": {"noHeader": True}}

    by_sid = {}
    for doc in accounts:
        sid = str(doc.get("studentId") or "").strip().upper()
        if sid:
            by_sid[sid] = doc

    drift, needs_import, skipped_removed = [], [], 0
    seen: set = set()
    for row in sheet_rows[1:]:
        sid = str(row[id_col] if len(row) > id_col else "").strip().upper()
        if not re.fullmatch(r"UMP\d{4,}", sid) or sid in BATCH_DRIFT_SKIP_IDS:
            continue
        seen.add(sid)
        sheet_batch = str(row[batch_col] if len(row) > batch_col else "").strip()
        account = by_sid.get(sid)
        if account is None:
            if sheet_batch:
                needs_import.append({
                    "studentId": sid,
                    "studentName": str(_sheet_row_name(row, header) or ""),
                    "sheetBatch": sheet_batch,
                })
            continue
        if account.get("removedAt"):
            skipped_removed += 1
            continue
        mongo_batch = str(account.get("batch") or "").strip()
        if not sheet_batch or sheet_batch == mongo_batch:
            continue
        drift.append({
            "studentId": sid,
            "studentName": str(account.get("studentName") or ""),
            "sheetBatch": sheet_batch,
            "mongoBatch": mongo_batch,
        })
    drift.sort(key=lambda r: r["studentId"])
    needs_import.sort(key=lambda r: r["studentId"])
    return {
        "drift": drift,
        "needsImport": needs_import,
        "skipped": {"removedStudents": skipped_removed, "sheetRowsWithoutAccount": len(seen) - len(drift) - len(needs_import) - skipped_removed},
    }



def _sheet_row_name(row: list, header: list) -> str:
    """Student name from the sheet row, whatever column order the sheet has."""
    try:
        idx = header.index("student name")
    except ValueError:
        return ""
    return str(row[idx] if len(row) > idx else "").strip()


_coverage_cache: dict = {"at": None, "payload": None}


STUDENTS_SHEET_ROW_LIMIT = 2000


async def _sheet_students_rows() -> list:
    """The whole Students tab (one read) - shared by the drift and coverage checks."""
    from routers.notes_inbox import _google_token

    try:
        token = _google_token()
    except HTTPException as exc:
        raise HTTPException(status_code=503, detail=str(exc.detail)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Students sheet could not be read.") from exc
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{STUDENTS_SHEET_ID}/values/Students!A1:U{STUDENTS_SHEET_ROW_LIMIT}"
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Students sheet is unreachable right now.") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Students sheet read failed (HTTP {resp.status_code}).")
    return resp.json().get("values") or []


async def _accounts_lite() -> list:
    db = get_db()
    cursor = db[STUDENT_ACCOUNTS].find(
        {},
        {"studentId": 1, "studentName": 1, "batch": 1, "removedAt": 1, "passwordHash": 1, "password": 1},
    )
    try:
        return await cursor.to_list(2000)
    except AttributeError:  # a test double without to_list
        return list(cursor)


async def _sheet_batch_rows() -> list:
    """Read the Students sheet (same service account the access toggle uses)."""
    return await _sheet_students_rows()


async def _live_accounts() -> list:
    return await _accounts_lite()


@router.get("/students/batch-drift")
async def get_batch_drift(refresh: bool = False, claims: dict = Depends(require_mentor)):
    """Mentor-only: which students' batch differs between the sheet and the app."""
    now = datetime.now(timezone.utc)
    cached = _drift_cache.get("payload")
    if (
        not refresh
        and cached
        and _drift_cache.get("at")
        and (now - _drift_cache["at"]).total_seconds() < BATCH_DRIFT_TTL_SEC
    ):
        return {**cached, "cached": True}

    sheet_rows = await _sheet_batch_rows()
    accounts = await _live_accounts()
    diff = batch_drift_rows(sheet_rows, accounts)
    payload = {
        "ok": True,
        "checkedAt": _now(),
        "sheetRows": max(0, len(sheet_rows) - 1),
        "accountsChecked": len(accounts),
        "driftCount": len(diff["drift"]),
        "needsImportCount": len(diff["needsImport"]),
        "drift": diff["drift"],
        "needsImport": diff["needsImport"],
        "skipped": diff["skipped"],
    }
    _drift_cache["at"] = now
    _drift_cache["payload"] = payload
    return {**payload, "cached": False}


class BatchDriftApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    studentIds: list[str] = Field(default_factory=list)


@router.post("/students/batch-drift/apply")
async def apply_batch_drift(body: BatchDriftApplyBody, claims: dict = Depends(require_mentor)):
    """Mentor-only: copy the sheet's Batch into Mongo for the named students.

    The sheet is re-read here instead of trusting what the browser showed, so a
    stale dialog can never write an outdated batch. Only rows that are still
    drifting are written; everything else is left exactly as it is.
    """
    wanted = {str(sid or "").strip().upper() for sid in body.studentIds if str(sid or "").strip()}
    all_rows = "*" in wanted or "ALL" in wanted
    sheet_rows = await _sheet_batch_rows()
    accounts = await _live_accounts()
    drift = batch_drift_rows(sheet_rows, accounts)["drift"]
    selected = [row for row in drift if all_rows or row["studentId"] in wanted]
    if not selected:
        return {"ok": True, "synced": 0, "rows": [], "remaining": len(drift),
                "message": "Nothing to sync - those students already match."}

    db = get_db()
    mentor = claims.get("sub") or "mentor"
    done, failed = [], []
    from routers.mentor_workspace import LOCKS
    from pymongo.errors import DuplicateKeyError
    import uuid
    for row in selected:
        stamp = _now()
        owner = "drift-" + str(uuid.uuid4())
        try:
            await db[LOCKS].insert_one({'_id':row['studentId'], 'planId':owner, 'kind':'batch_drift', 'at':stamp})
        except DuplicateKeyError:
            failed.append(row['studentId'])
            continue
        account = await db[STUDENT_ACCOUNTS].find_one({'studentId':row['studentId']}) or {}
        try:
            result = await db[STUDENT_ACCOUNTS].update_one(
                {"studentId": row["studentId"], "batch":row["mongoBatch"], "membershipVersion":account.get("membershipVersion")},
                {"$set": {
                    "batch": row["sheetBatch"],
                    "membershipVersion": str(uuid.uuid4()),
                    "batchUpdatedAt": stamp,
                    "batchUpdatedBy": mentor,
                    "updatedAt": stamp,
                }},
            )
        except Exception:
            failed.append(row["studentId"])
            continue
        await db[LOCKS].delete_one({'_id':row['studentId'], 'planId':owner})
        if not getattr(result, "matched_count", 0):
            failed.append(row["studentId"])
            continue
        done.append({
            "studentId": row["studentId"],
            "from": row["mongoBatch"],
            "to": row["sheetBatch"],
        })
        try:
            await db[STUDENT_ADMIN_AUDIT].insert_one({
                "action": "student_batch_drift_sync",
                "studentId": row["studentId"],
                "previousBatch": row["mongoBatch"],
                "batch": row["sheetBatch"],
                "mentor": mentor,
                "sheetUpdated": False,
                "mongoUpdated": True,
                "at": stamp,
            })
        except Exception:
            pass  # already consistent; an audit failure must not undo the fix
    _drift_cache["at"] = None
    _drift_cache["payload"] = None
    return {
        "ok": not failed,
        "synced": len(done),
        "rows": done,
        "failed": failed,
        "remaining": max(0, len(drift) - len(done)),
        "message": (
            f"{len(done)} student(s) now follow the sheet."
            + (f" {len(failed)} could not be written." if failed else "")
        ),
    }


async def _coverage_payload() -> dict:
    """Classify every sheet cell against its account hash.

    The bcrypt work runs in a worker thread: bcrypt releases the GIL while it
    computes, so the event loop keeps answering other requests instead of
    standing still for two minutes.
    """
    rows = await _sheet_students_rows()
    accounts = await _accounts_lite()
    out = await asyncio.to_thread(password_sheet_sync.coverage_of, rows, accounts)
    return {
        "ok": True,
        "checkedAt": _now(),
        "accountsChecked": len(accounts),
        "usablePct": round(100 * out["valid"] / out["total"], 1) if out["total"] else 0,
        **out,
    }


@router.get("/students/password-coverage")
async def get_password_coverage(refresh: bool = False, claims: dict = Depends(require_mentor)):
    """Mentor-only: how many Students-sheet password cells a student can actually use.

    The sheet is the ledger the mentor reads and the welcome mail is built from, and
    a student's own password reaches it only at the moment they sign in. So this is
    the progress meter for that: 'pending' shrinks by itself as students log in, and
    it is empty when every active student's sheet cell matches their live password.
    """
    payload = await sheet_coverage.coverage_for(_coverage_payload, refresh=refresh)
    return {**payload, "cached": bool(sheet_coverage.payload() is payload)}


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
async def save_whatsapp(body: SaveWhatsAppBody, principal=Depends(dashboard_student)):
    """Student saves their own WhatsApp number (used for enrollment welcome,
    reminders and announcements)."""
    from whatsapp import normalize_number

    sid = own_payload(principal, {"studentId":body.studentId})["studentId"]
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
async def reminder_notify(body: ReminderNotifyBody, principal=Depends(dashboard_student)):
    """Mirror a student reminder to their saved WhatsApp number."""
    from whatsapp import normalize_number, send_whatsapp

    sid = own_payload(principal, {"studentId":body.studentId})["studentId"]
    db = get_db()
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not doc:
        return {"result": {"success": False, "message": "Student ID not found."}}
    raw = str(doc.get("whatsapp") or doc.get("phone") or "").strip()
    if not raw:
        return {"result": {"success": False, "message": "No WhatsApp number saved yet."}}
    ok = await send_whatsapp(normalize_number(raw), f"Reminder: {body.text}", purpose="reminder")
    return {"result": {"success": bool(ok)}}
