"""Mentor-facing WhatsApp visibility: config status + delivery log.

Lets the dashboard show that student messages are being mirrored to WhatsApp
(the 'dual delivery' proof) without exposing any secrets.
"""
from fastapi import APIRouter, Depends, Query

from auth import require_mentor
from db import WHATSAPP_LOG, get_db

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
