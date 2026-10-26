"""A quiet record of sign-ins that did not work, so "student says the password is wrong"
becomes a list the mentor can act on.

Before this module nothing was stored: `authenticate_student` returned "Incorrect
password." and the event vanished, so a student could be locked out for a week and the
only evidence was their WhatsApp message. Now each rejected attempt bumps one small
document per student, and a successful sign-in clears it - which makes the pending
list self-cleaning: fix the password and the row stops asking for attention.

Deliberate choices:
  * fire-and-forget, like the sheet mirror - a login must never fail or slow down
    because an analytics write went wrong;
  * the submitted password is never seen here, and nothing about it is stored;
  * `openFails` is what "still stuck" means, so an old complaint does not haunt a
    student who has since logged in fine.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COLLECTION = "login_failures"
# Only these codes mean "the credentials did not work". access_blocked and
# group_closed are deliberate mentor decisions, not a forgotten password.
TRACKED_CODES = ("wrong_password", "not_found", "invalid")
RECENT_DAYS = 30

_tasks: set = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spawn(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # a sync context (script, migration): do it inline
        asyncio.run(coro)
        return
    task = loop.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _bump_failure(db, sid: str, code: str) -> None:
    await db[COLLECTION].update_one(
        {"_id": sid},
        {"$inc": {"fails": 1, "openFails": 1}, "$set": {"lastFailAt": _now(), "lastFailCode": code}},
        upsert=True,
    )


async def _bump_success(db, sid: str) -> None:
    # $set of openFails=0 in the same update as $inc of anything else on that field
    # would be a conflict, so the success path only ever settles it.
    await db[COLLECTION].update_one(
        {"_id": sid},
        {"$set": {"lastOkAt": _now(), "openFails": 0}},
        upsert=True,
    )


def note_attempt(student_id: str, ok: bool, code: str = "") -> None:
    """Record one login outcome. Never raises, never blocks, never sees the password."""
    sid = str(student_id or "").strip().upper()
    if not sid:
        return
    if not ok and code not in TRACKED_CODES:
        return
    from db import get_db

    async def run() -> None:
        try:
            db = get_db()
            if ok:
                await _bump_success(db, sid)
            else:
                await _bump_failure(db, sid, code)
        except Exception as exc:  # noqa: BLE001 - an analytics write must not break a login
            logger.warning("[login-failures] %s not recorded (%s)", sid, type(exc).__name__)

    _spawn(run())


async def clear(db, sid: str) -> None:
    """The mentor fixed the password: close the complaint without claiming a login.

    lastOkAt is only ever written by a real successful sign-in, so this records its own
    event - which is what stops a reset student from sitting in the queue all week.
    """
    sid = str(sid or "").strip().upper()
    if not sid:
        return
    try:
        await db[COLLECTION].update_one(
            {"_id": sid}, {"$set": {"openFails": 0, "resetAt": _now()}}, upsert=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[login-failures] could not clear %s (%s)", sid, type(exc).__name__)


async def summary(db) -> dict:
    """studentId -> {fails, openFails, lastFailAt, lastFailCode, lastOkAt}."""
    out: dict[str, dict] = {}
    try:
        cursor = db[COLLECTION].find({})
        try:
            docs = await cursor.to_list(4000)
        except AttributeError:  # a test double without to_list
            docs = list(cursor)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[login-failures] read failed (%s)", type(exc).__name__)
        return out
    for doc in docs:
        sid = str(doc.get("_id") or doc.get("studentId") or "").strip().upper()
        if not sid:
            continue
        out[sid] = {
            "fails": int(doc.get("fails") or 0),
            "openFails": int(doc.get("openFails") or 0),
            "lastFailAt": doc.get("lastFailAt") or "",
            "lastFailCode": doc.get("lastFailCode") or "",
            "lastOkAt": doc.get("lastOkAt") or "",
            "resetAt": doc.get("resetAt") or "",
        }
    return out
