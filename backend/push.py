"""FCM push sending — HTTP v1, best-effort, never raises to callers.

Env (set on the Cloud Run service):
  FIREBASE_SERVICE_ACCOUNT_JSON : full service-account JSON (raw or base64), or
  FCM_PROJECT_ID / FCM_CLIENT_EMAIL / FCM_PRIVATE_KEY  (PEM, \\n-escaped ok)

When nothing is configured every send is a silent no-op, so the rest of the
app never breaks because push credentials are absent. Mirrors the payload
shape the installed APKs already understand (data.title/body/link/tag +
android HIGH priority), so no client update is needed for pushes to work.
"""
from __future__ import annotations

import asyncio
import hashlib
import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import httpx

from db import DEVICE_TOKENS, STUDENT_ACCOUNTS, get_db

logger = logging.getLogger("push")

IST = timezone(timedelta(hours=5, minutes=30))
# Nothing automatic may wake a student between 00:00 and 06:59 IST. 16-Oct-2026:
# one scheduler tick still running at midnight sent 441 pushes in the 00:00 hour,
# so the window is enforced at the send call itself, not only in the job loop.
QUIET_HOURS_IST = range(0, 7)


def quiet_block_reason(quiet_hours=None, at: datetime | None = None) -> str:
    """Why an *automatic* push must be held back right now, "" to send it.

    Mentors keep an escape hatch (PUSH_ALLOW_QUIET=1) for a deliberate late-night
    announcement; nothing scheduled ever consults it.
    """
    if (os.environ.get("PUSH_ALLOW_QUIET", "") or "").strip().lower() in ("1", "true", "yes", "on"):
        return ""
    hours = QUIET_HOURS_IST if quiet_hours is None else quiet_hours
    if (at or datetime.now(IST)).hour in hours:
        return "quiet hours (00:00-06:59 IST)"
    return ""


_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_MAX_TOKENS_PER_STUDENT = 10

_access_token: str = ""
_access_expiry: float = 0.0

# Strong references so fire-and-forget tasks are never garbage collected.
_background_tasks: set = set()


def spawn(coro) -> None:
    """Fire-and-forget a coroutine without blocking the caller's request."""
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        # No event loop (scripts/tests) — drop silently rather than raise.
        coro.close()
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _credentials() -> tuple[str, str, str]:
    """(project_id, client_email, private_key) from env; empty strings if unset."""
    raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if raw:
        info: dict = {}
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            try:
                info = json.loads(base64.b64decode(raw).decode("utf-8"))
            except Exception:
                info = {}
        project = str(info.get("project_id") or "")
        email = str(info.get("client_email") or "")
        key = str(info.get("private_key") or "")
        if email and key:
            return project or "ump-dashboard", email, key
    project = (os.environ.get("FCM_PROJECT_ID") or "ump-dashboard").strip()
    email = (os.environ.get("FCM_CLIENT_EMAIL") or "").strip()
    key = (os.environ.get("FCM_PRIVATE_KEY") or "").replace("\\n", "\n").strip()
    return project, email, key


def configured() -> bool:
    _, email, key = _credentials()
    return bool(email and key)


async def _get_access_token() -> str:
    global _access_token, _access_expiry
    now = time.time()
    if _access_token and now < _access_expiry:
        return _access_token
    project, email, key = _credentials()
    if not (email and key):
        raise RuntimeError("FCM credentials are not configured")
    import jwt  # pyjwt (already in requirements)

    claim = {
        "iss": email,
        "scope": _SCOPE,
        "aud": _TOKEN_URL,
        "iat": int(now),
        "exp": int(now) + 3600,
    }
    assertion = jwt.encode(claim, key, algorithm="RS256")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        token = str(resp.json().get("access_token") or "")
    if not token:
        raise RuntimeError("Empty FCM access token")
    _access_token = token
    _access_expiry = now + 55 * 60
    return token


# --------------------------------------------------------------------------- #
# device tokens
# --------------------------------------------------------------------------- #
async def save_device_token(student_id: str, token: str) -> bool:
    student_id = (student_id or "").strip().upper()
    token = (token or "").strip()
    if not student_id or len(token) < 20:
        return False
    db = get_db()
    now = int(time.time() * 1000)
    # Deterministic ID prevents parallel token upserts creating multiple owners.
    key = "device-" + hashlib.sha256(token.encode()).hexdigest()
    await db[DEVICE_TOKENS].update_one(
        {"_id": key},
        {
            "$set": {"token": token, "studentId": student_id, "updatedAt": now},
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    # Reconcile only this presented token, never bulk-migrate unrelated records.
    await db[DEVICE_TOKENS].delete_many({"token": token, "_id": {"$ne": key}})
    # Cap the fleet per student so stale devices age out.
    stale = (
        await db[DEVICE_TOKENS]
        .find({"studentId": student_id})
        .sort("updatedAt", -1)
        .skip(_MAX_TOKENS_PER_STUDENT)
        .to_list(length=100)
    )
    if stale:
        await db[DEVICE_TOKENS].delete_many({"_id": {"$in": [d["_id"] for d in stale]}})
    return True


async def remove_device_token(student_id: str, token: str) -> bool:
    # Idempotent, owner-scoped: a delayed A logout cannot remove B's binding.
    await get_db()[DEVICE_TOKENS].delete_many({"studentId": student_id, "token": token.strip()})
    return True


async def students_with_devices() -> list[str]:
    db = get_db()
    values = await db[DEVICE_TOKENS].distinct("studentId")
    out: list[str] = []
    for value in values:
        sid = str(value or "").strip().upper()
        if sid and sid not in out and not await _student_is_removed(db, sid):
            out.append(sid)
    return out


async def _student_is_removed(db, student_id: str) -> bool:
    """Soft-removed students (mentor removed them) never receive pushes."""
    return await _student_unreachable_reason(db, student_id) is not None


async def _student_unreachable_reason(db, student_id: str) -> Optional[str]:
    """Why this student must not be pinged right now, or None to go ahead.

    "removed" - left the program, and "access_off" - the mentor locked the app for
    them. The second one is the fix for the 15-Oct-2026 complaint: students kept
    getting "New test published" for a test their login refused to open, which reads
    as the app breaking rather than as a lock. The content still lands in their list,
    and the restore itself sends a "you missed this" push (see access_events).
    """
    doc = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": student_id},
        {"_id": 0, "status": 1, "removedAt": 1, "accessEnabled": 1, "attempt": 1, "batch": 1, "master": 1},
    )
    if not doc:
        return "unknown"
    from routers.student_auth import _attempt_access_allowed
    if not (doc.get("master") or _attempt_access_allowed(str(doc.get("attempt") or ""), str(doc.get("batch") or ""))):
        return "access_off"
    if bool(doc.get("removedAt")) or str(doc.get("status") or "").strip().lower() == "removed":
        return "removed"
    if doc.get("accessEnabled") is False:
        return "access_off"
    return None


# --------------------------------------------------------------------------- #
# audience helpers
# --------------------------------------------------------------------------- #
def matches_audience(doc: dict, account: dict) -> bool:
    """Batch/group targeting — blank or 'All'/'Both' on the doc means everyone."""
    if doc.get("exclusiveGroup"):
        from routers.mentor_workspace import group_key
        wanted = group_key(doc.get("group"))
        return bool(doc.get("batch") and doc.get("batch") == account.get("batch") and wanted != "unknown" and wanted == group_key(account.get("group")))
    want_batch = str(doc.get("batch") or doc.get("audience") or "").strip().lower()
    want_group = str(doc.get("group") or "").strip().lower()
    have_batch = str(account.get("batch") or "").strip().lower()
    have_group = str(account.get("group") or "").strip().lower()
    if want_batch and want_batch not in ("all batches", "all", "both"):
        if want_batch != have_batch:
            return False
    if want_group and want_group not in ("both", "both groups", "all"):
        if have_group and have_group not in ("both", "both groups") and want_group != have_group:
            return False
    return True


async def audience_student_ids(batch: str = "", group: str = "") -> list[str]:
    """Students (from accounts) matching an optional batch/group filter."""
    db = get_db()
    ids: list[str] = []
    async for acc in db[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "batch": 1, "group": 1}):
        sid = str(acc.get("studentId") or "").strip().upper()
        if not sid:
            continue
        if matches_audience({"batch": batch, "group": group}, acc):
            ids.append(sid)
    return ids


# --------------------------------------------------------------------------- #
# sending
# --------------------------------------------------------------------------- #
async def _send_to_token(token: str, title: str, body: str, data: dict) -> bool:
    project, _, _ = _credentials()
    access = await _get_access_token()
    payload_data = {
        "title": str(title or "")[:200],
        "body": str(body or "")[:500],
        "link": str(data.get("link") or ""),
        "tag": str(data.get("tag") or "ump-general"),
        "studentId": str(data.get("studentId") or ""),
        "timestamp": str(int(time.time() * 1000)),
    }
    message = {
        "message": {
            "token": token,
            "data": payload_data,
            "android": {
                "priority": "HIGH",
                "notification": {
                    "title": payload_data["title"],
                    "body": payload_data["body"],
                    "color": "#3157D5",
                    "channel_id": "ump-updates",
                },
            },
            "apns": {"payload": {"aps": {"sound": "default", "badge": 1}}},
        }
    }
    url = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url, json=message, headers={"Authorization": f"Bearer {access}"}
        )
    if resp.status_code < 400:
        return True
    text = resp.text[:300]
    logger.warning("FCM send failed (%s)", resp.status_code)
    if "UNREGISTERED" in text or "INVALID_ARGUMENT" in text:
        try:
            db = get_db()
            await db[DEVICE_TOKENS].delete_many({"token": token})
        except Exception:
            pass
    return False


async def push_to_student(
    student_id: str,
    title: str,
    body: str,
    *,
    link: str = "",
    tag: str = "ump-general",
) -> int:
    """Return provider-accepted send count, not physical-device delivery."""
    if not configured():
        return 0
    student_id = (student_id or "").strip().upper()
    if not student_id:
        return 0
    try:
        db = get_db()
        if await _student_unreachable_reason(db, student_id):
            return 0
        docs = await db[DEVICE_TOKENS].find(
            {"studentId": student_id}, {"token": 1}
        ).to_list(length=_MAX_TOKENS_PER_STUDENT)
        sent = 0
        seen_tokens = set()
        for doc in docs:
            token = str(doc.get("token") or "")
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            try:
                # Re-check ownership after the initial query; ambiguous legacy
                # duplicate owners fail closed until that token is re-registered.
                owners = await db[DEVICE_TOKENS].distinct("studentId", {"token": token})
                if owners != [student_id]:
                    continue
                if await _send_to_token(token, title, body, {"link": link, "tag": tag, "studentId": student_id}):
                    sent += 1
            except Exception as exc:
                logger.warning("Push provider request failed")
        return sent
    except Exception as exc:
        logger.warning("Push dispatch unavailable")
        return 0


async def push_to_students(
    student_ids: Iterable[str],
    title: str,
    body: str,
    *,
    link: str = "",
    tag: str = "ump-general",
    throttle_s: float = 0.15,
) -> int:
    sent = 0
    for sid in student_ids:
        sent += await push_to_student(sid, title, body, link=link, tag=tag)
        if throttle_s:
            await asyncio.sleep(throttle_s)
    return sent


async def push_to_all(
    title: str,
    body: str,
    *,
    link: str = "",
    tag: str = "ump-general",
    batch: str = "",
    group: str = "",
    throttle_s: float = 0.15,
    hold_quiet: bool = False,
) -> int:
    """Push to every student with a registered device, filtered by batch/group.

    `hold_quiet=True` is for broadcast sends that fire themselves (weekly report):
    they are held inside the quiet window instead of waking the whole batch.
    """
    held = quiet_block_reason() if hold_quiet else ""
    if held:
        logger.info("push_to_all held: %s (tag=%s)", held, tag)
        return 0
    if not configured():
        return 0
    try:
        registered = set(await students_with_devices())
        if not registered:
            return 0
        if batch or group:
            accounts = await audience_student_ids(batch=batch, group=group)
            targets = [sid for sid in accounts if sid in registered]
        else:
            targets = sorted(registered)
        return await push_to_students(
            targets, title, body, link=link, tag=tag, throttle_s=throttle_s
        )
    except Exception as exc:
        logger.warning("push_to_all failed: %s", exc)
        return 0
