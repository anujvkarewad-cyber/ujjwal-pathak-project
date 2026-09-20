"""Mentor-facing WhatsApp visibility: config status + delivery log.

Lets the dashboard show that student messages are being mirrored to WhatsApp
(the 'dual delivery' proof) without exposing any secrets.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth import require_mentor
from db import STUDENT_ACCOUNTS, WHATSAPP_LOG, get_db

try:
    from whatsapp import whatsapp_status
except Exception:  # pragma: no cover
    def whatsapp_status():  # type: ignore
        return {"provider": "off", "ready": False, "mentorNumber": False, "active": False}

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.get("/status")
async def status(claims: dict = Depends(require_mentor)):
    return whatsapp_status()


@router.get("/log")
async def log(limit: int = Query(default=30, ge=1, le=200), claims: dict = Depends(require_mentor)):
    db = get_db()
    docs = await db[WHATSAPP_LOG].find({}).sort("at", -1).to_list(length=limit)
    for d in docs:
        d.pop("_id", None)
    return {"ok": True, "entries": docs}


class AnnounceBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    studentIds: Optional[list] = None


@router.post("/announce")
async def announce(body: AnnounceBody, claims: dict = Depends(require_mentor)):
    """Send an announcement over WhatsApp to every student (or a chosen list)
    that has a WhatsApp number on file. Works with any provider; in simulate
    mode each send is logged so the dashboard shows the delivery trail."""
    from whatsapp import normalize_number, send_whatsapp

    db = get_db()
    query = {}
    if body.studentIds:
        query = {"studentId": {"$in": [str(s).strip().upper() for s in body.studentIds]}}
    docs = await db[STUDENT_ACCOUNTS].find(query).to_list(length=1000)
    sent = skipped = 0
    for d in docs:
        raw = str(d.get("whatsapp") or d.get("phone") or "").strip()
        if not raw:
            skipped += 1
            continue
        ok = await send_whatsapp(normalize_number(raw), body.text, purpose="announcement")
        if ok:
            sent += 1
    return {"ok": True, "sent": sent, "skippedNoNumber": skipped}
