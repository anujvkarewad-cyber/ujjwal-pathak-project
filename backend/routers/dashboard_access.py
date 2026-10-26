"""Student dashboard boundary: existing credentials, fresh account state, no legacy bypass."""
from fastapi import HTTPException, Request, Response
import asyncio
import hashlib
import hmac
import os

# Only unfinished equivalent password checks share work. No completed proof or
# account/access decision is cached. Keys are process-local HMACs, never secrets.
_PROOF_KEY = os.urandom(32)
_PROOFS = {}
_MAX_INFLIGHT_PROOFS = 16

def _proof_stamp(sid, password, account):
    fields = [sid, password, str(account.get("passwordHash") or ""), str(account.get("password") or "")]
    return hmac.new(_PROOF_KEY, repr(fields).encode(), hashlib.sha256).digest()

async def _verify_current_password(sid, password, account):
    from routers.student_auth import _password_ok
    loop = asyncio.get_running_loop()
    key = (loop, _proof_stamp(sid, password, account))
    task = _PROOFS.get(key)
    if task is None:
        if sum(k[0] is loop for k in _PROOFS) >= _MAX_INFLIGHT_PROOFS:
            deny(503, "Authentication service busy. Try again shortly.")
        task = asyncio.create_task(asyncio.to_thread(_password_ok, password, account))
        _PROOFS[key] = task
        def discard(done):
            if _PROOFS.get(key) is done:
                _PROOFS.pop(key, None)
            if not done.cancelled():
                done.exception()  # consume a late failure after caller cancellation
        task.add_done_callback(discard)
    return await asyncio.shield(task)

from db import get_db, STUDENT_ACCOUNTS

READ_ACTIONS = frozenset({"getStats", "getStudyLog", "getWeeklyReports", "getStudentMentorNotes", "getStudentFeedback", "getAnnouncements", "getLeaderboard", "notes.listForStudent", "attendance.status"})
WRITE_ACTIONS = frozenset({"addStudyLog", "deleteStudyLog", "attendance.markAbsent", "attendance.requestLeave", "attendance.cancelLeave", "feedback.read"})

def deny(status, message):
    raise HTTPException(status_code=status, detail=message, headers={"Cache-Control":"no-store"})

async def dashboard_student(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    from routers.student_auth import normalize_student_id, _password_ok, _attempt_access_allowed
    sid = normalize_student_id(request.headers.get("X-Student-Id", ""))
    password = request.headers.get("X-Session-Password", "")
    if not sid or not password:
        deny(401, "Student authentication required.")
    account = await get_db()[STUDENT_ACCOUNTS].find_one({"studentId":sid})
    # Do not reveal account existence, access reasons, or other private fields.
    if not account or not await _verify_current_password(sid, password, account):
        deny(401, "Student authentication required.")
    # Access and credential changes during an offloaded check must be observed.
    fresh = await get_db()[STUDENT_ACCOUNTS].find_one({"studentId":sid})
    if not fresh or _proof_stamp(sid, password, fresh) != _proof_stamp(sid, password, account):
        deny(401, "Student authentication required.")
    account = fresh
    if (account.get("removedAt") or str(account.get("status") or "").lower() == "removed"
        or account.get("accessEnabled") is False
        or not (account.get("master") or _attempt_access_allowed(str(account.get("attempt") or ""), str(account.get("batch") or "")))):
        deny(403, "Student access unavailable.")
    return {"studentId":account["studentId"]}

def own_payload(principal, payload, target=None):
    from routers.student_auth import normalize_student_id
    owner = principal["studentId"]
    payload = dict(payload or {})
    for value in (target, payload.get("studentId")):
        if value not in (None, "") and normalize_student_id(value) != owner:
            deny(403, "Student scope denied.")
    payload["studentId"] = owner
    return payload
