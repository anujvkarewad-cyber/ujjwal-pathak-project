"""Student ↔ Mentor messenger.

Student app writes via POST /api/messages/send and reads its thread via
GET /api/messages/thread. The mentor dashboard reads all threads via
GET /api/messages/inbox and replies via POST /api/messages/reply.

Every NEW student message can optionally notify the mentor on WhatsApp
(config-driven; best-effort — never blocks or breaks the send).
"""
import logging
import os
from datetime import datetime, timezone

import push as push_service
from routers.dashboard_access import dashboard_student, own_payload
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_mentor
from db import STUDENT_ACCOUNTS, STUDENT_MESSAGES, get_db
from models import MessageReplyRequest, MessageSendRequest

try:
    from whatsapp import mentor_number, send_whatsapp
except Exception:  # pragma: no cover
    async def send_whatsapp(to, text, purpose="general"):  # type: ignore
        return False

    def mentor_number():  # type: ignore
        return ""

router = APIRouter(prefix="/api/messages", tags=["messages"])
logger = logging.getLogger(__name__)

# ── "tell the mentor a student wrote" ──────────────────────────────────────
# The mentor is on a phone, so an inbox that only updates when he opens it is
# useless. Every student message now also fires an app push to the mentor's own
# device(s). A "mentor device" is simply a phone signed in to one of the
# accounts listed in MENTOR_ALERT_STUDENT_IDS (default: the demo/tutorial
# account the owner already carries), so no new app build is needed.
ALERTS = "mentor_alerts"


def mentor_pager_ids() -> list:
    raw = (os.environ.get("MENTOR_ALERT_STUDENT_IDS") or "UMP9900").strip()
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


GROUP_LABELS = {"group1": "Group 1", "group2": "Group 2", "both": "Both"}


async def placement(db, student_id: str, batch_hint: str = "") -> str:
    """Where the student sits right now, e.g. "After Result Batch 1 / Group 2".

    The mentor needs this to know who is writing without opening the dashboard, so
    the notification carries it. Mongo mirrors the sheet membership (transfers write
    both), and it is one indexed read instead of a full sheet read on every message.
    """
    account = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": student_id}, {"batch": 1, "group": 1}
    ) or {}
    batch = str(account.get("batch") or batch_hint or "").strip()
    raw_group = str(account.get("group") or "").strip()
    key = raw_group.lower().replace(" ", "").replace("_", "")
    group = GROUP_LABELS.get(key) or raw_group
    if batch and group:
        return f"{batch} / {group}"
    return batch or group or "Batch not set"


async def alert_mentor(db, student_id: str, who: str, text: str, unread: int, batch_hint: str = "") -> int:
    """Push a short alert to the mentor's devices. Never raises, never blocks a send."""
    where = await placement(db, student_id, batch_hint)
    title = f"New message from {who}"
    body = f"{where} — " + ((text or "").strip().replace("\n", " ")[:110] or "New message")
    if unread > 1:
        body = f"{body}  ({unread} unread)"
    sent = 0
    for pager in mentor_pager_ids():
        if pager == student_id.upper():
            continue  # the demo account talking to itself is not news
        try:
            sent += await push_service.push_to_student(
                pager, title, body, link="home", tag=f"student-msg-{student_id}"
            )
        except Exception as exc:  # noqa: BLE001 - alerting is best effort
            logger.warning("mentor alert push failed for %s (%s)", pager, type(exc).__name__)
    try:
        await db[ALERTS].insert_one({
            "at": _now(), "kind": "student_message", "studentId": student_id,
            "studentName": who, "placement": where, "excerpt": (text or "")[:300],
            "pagers": mentor_pager_ids(), "providerAccepted": sent,
        })
    except Exception:  # pragma: no cover - audit must never break the send
        pass
    return sent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _thread_doc(db, student_id: str) -> dict:
    doc = await db[STUDENT_MESSAGES].find_one({"studentId": student_id})
    return doc or {"studentId": student_id, "studentName": None, "batch": None, "messages": [], "unreadForMentor": 0}


@router.get("/thread")
async def get_thread(studentId: str = Query(min_length=1, max_length=64), principal=Depends(dashboard_student)):
    """Student app: full conversation with the mentor."""
    db = get_db()
    studentId = own_payload(principal, {"studentId":studentId})["studentId"]
    doc = await _thread_doc(db, studentId)
    # student opening the thread clears nothing — unread count is mentor-side only
    return {"ok": True, "studentId": studentId, "messages": [m for m in doc.get("messages", []) if not str(m.get("id") or "").startswith("ws-")]}


@router.post("/send")
async def send_message(body: MessageSendRequest, principal=Depends(dashboard_student)):
    """Student app → mentor. Appends to the thread and (optionally) pings the
    mentor on WhatsApp."""
    body.studentId = own_payload(principal, {"studentId":body.studentId})["studentId"]
    db = get_db()
    message = {"id": f"m-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
               "from": "student", "text": body.text, "at": _now()}

    update = {
        "$push": {"messages": message},
        "$inc": {"unreadForMentor": 1},
        "$set": {"updatedAt": _now()},
    }
    if body.studentName:
        update["$set"]["studentName"] = body.studentName
    if body.batch:
        update["$set"]["batch"] = body.batch
    await db[STUDENT_MESSAGES].update_one({"studentId": body.studentId}, update, upsert=True)

    # Best-effort WhatsApp alert to the mentor (config-driven, never blocks).
    number = mentor_number()
    if number:
        who = body.studentName or body.studentId
        try:
            await send_whatsapp(
                number,
                f"New message from {who} ({body.studentId}):\n{body.text[:500]}\n\nReply in the UMP Mentor Dashboard → Messages.",
                purpose="student_message",
            )
        except Exception:
            pass

    # Push alert so the mentor's phone buzzes even if the dashboard is closed.
    who = body.studentName or body.studentId
    try:
        thread = await db[STUDENT_MESSAGES].find_one(
            {"studentId": body.studentId}, {"unreadForMentor": 1}
        ) or {}
        await alert_mentor(db, body.studentId, who, body.text,
                           int(thread.get("unreadForMentor") or 0), batch_hint=body.batch or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("mentor alert skipped (%s)", type(exc).__name__)

    return {"ok": True, "message": message}


@router.get("/inbox")
async def inbox(claims: dict = Depends(require_mentor)):
    """Mentor dashboard: all student threads, newest activity first."""
    db = get_db()
    threads = []
    async for doc in db[STUDENT_MESSAGES].find({}):
        doc.pop("_id", None)
        messages = doc.get("messages", [])
        last = messages[-1] if messages else None
        threads.append({
            "studentId": doc.get("studentId"),
            "studentName": doc.get("studentName"),
            "batch": doc.get("batch"),
            "unreadForMentor": doc.get("unreadForMentor", 0),
            "updatedAt": doc.get("updatedAt"),
            "lastMessage": last,
            "messageCount": len(messages),
        })
    threads.sort(key=lambda t: t.get("updatedAt") or "", reverse=True)
    return {"ok": True, "threads": threads}


@router.get("/inbox/{student_id}")
async def inbox_thread(student_id: str, claims: dict = Depends(require_mentor)):
    """Mentor dashboard: one full thread (opens it and marks it read)."""
    db = get_db()
    doc = await _thread_doc(db, student_id)
    await db[STUDENT_MESSAGES].update_one({"studentId": student_id}, {"$set": {"unreadForMentor": 0}})
    return {"ok": True, "studentId": student_id, "studentName": doc.get("studentName"),
            "batch": doc.get("batch"), "messages": doc.get("messages", [])}


@router.post("/reply")
async def reply(body: MessageReplyRequest, claims: dict = Depends(require_mentor)):
    """Mentor dashboard → student app."""
    db = get_db()
    message = {"id": f"m-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
               "from": "mentor", "text": body.text, "at": _now()}
    result = await db[STUDENT_MESSAGES].update_one(
        {"studentId": body.studentId},
        {"$push": {"messages": message}, "$set": {"updatedAt": _now()}},
        upsert=True,
    )
    if not result.matched_count and not result.upserted_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True, "message": message}
