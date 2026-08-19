"""Student login against Mongo so 100–200 concurrent sign-ins do not hit Apps Script."""
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth import hash_password, require_mentor, verify_password
from config import settings
from db import STUDENT_ACCOUNTS, get_db

router = APIRouter(prefix="/api/student-auth", tags=["student-auth"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        "forcePasswordChange": not bool(doc.get("passwordChanged")),
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
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": {
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
                "passwordHash": hash_password(pwd),
                "passwordChanged": password_changed,
                "updatedAt": _now(),
            },
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
