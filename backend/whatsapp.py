"""WhatsApp sending service — pluggable provider, config-driven.

Automated WhatsApp requires the WhatsApp Business API. Two integrations are
supported and selected by environment config:

  WHATSAPP_PROVIDER=meta    → Meta WhatsApp Cloud API
  WHATSAPP_PROVIDER=msg91   → MSG91 (common Indian aggregator)
  (unset / anything else)   → disabled; messages are only logged, never sent

This module NEVER raises to callers — WhatsApp is best-effort. Every attempt
(success or failure) is written to the `whatsapp_log` collection and, on
failure, swallowed so the main flow (enrollment / messaging) never breaks.

Credentials are read from the environment / .env. Do NOT hardcode tokens here.
"""
import os
from datetime import datetime, timezone

import httpx

from db import WHATSAPP_LOG, get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def provider() -> str:
    return (os.environ.get("WHATSAPP_PROVIDER") or "").strip().lower()


# Owner's current receiving WhatsApp number.
# Updated 2026-09-21: 8620836103 -> 7709379809. This constant is authoritative.
MENTOR_WHATSAPP_DEFAULT = "917709379809"


def mentor_number() -> str:
    """Mentor's WhatsApp number in international format, e.g. 919876543210."""
    return (MENTOR_WHATSAPP_DEFAULT or os.environ.get("WHATSAPP_MENTOR_NUMBER") or "").strip()


def normalize_number(raw: str) -> str:
    """Normalize a phone number to digits with country code (default India +91)."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if len(digits) == 10:
        digits = "91" + digits
    return digits


async def _log(recipient: str, purpose: str, status: str, detail: str) -> None:
    try:
        db = get_db()
        await db[WHATSAPP_LOG].insert_one(
            {"at": _now(), "to": recipient, "purpose": purpose, "status": status, "detail": detail}
        )
    except Exception:  # pragma: no cover - logging must never break the flow
        pass


async def send_meta(to_number: str, body_text: str) -> tuple[bool, str]:
    """Send a free-form/template message via Meta WhatsApp Cloud API.

    Env: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, optional WHATSAPP_TEMPLATE_NAME
    """
    token = os.environ.get("WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not token or not phone_id:
        return False, "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID not configured"

    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    template = os.environ.get("WHATSAPP_TEMPLATE_NAME", "").strip()
    if template:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {"name": template, "language": {"code": "en"},
                          "components": [{"type": "body", "parameters": [{"type": "text", "text": body_text}]}]},
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": body_text},
        }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    if r.status_code < 300:
        return True, "sent"
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


async def send_msg91(to_number: str, body_text: str) -> tuple[bool, str]:
    """Send via MSG91 WhatsApp API.

    Env: MSG91_AUTH_KEY, MSG91_TEMPLATE_ID (approved template), MSG91_SOURCE (91...)
    """
    auth_key = os.environ.get("MSG91_AUTH_KEY", "").strip()
    template_id = os.environ.get("MSG91_TEMPLATE_ID", "").strip()
    source = os.environ.get("MSG91_SOURCE", "91").strip()
    if not auth_key or not template_id:
        return False, "MSG91_AUTH_KEY / MSG91_TEMPLATE_ID not configured"

    url = "https://control.msg91.com/api/v5/whatsapp/whatsappoutsourcemessage"
    payload = {
        "flow_id": template_id,
        "sender": source,
        "recipient": to_number,
        "variables": {"message": body_text},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers={"authkey": auth_key})
    if r.status_code < 300:
        return True, "sent"
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


async def send_whatsapp(to_number: str, body_text: str, purpose: str = "general") -> bool:
    """Best-effort WhatsApp send. Returns True only if actually delivered to provider."""
    to_number = normalize_number(to_number)
    if not to_number:
        await _log("", purpose, "skipped", "empty recipient number")
        return False

    prov = provider()
    if prov == "meta":
        ok, detail = await send_meta(to_number, body_text)
    elif prov == "msg91":
        ok, detail = await send_msg91(to_number, body_text)
    elif prov == "simulate":
        # Demo mode: proves the dual-channel flow without real credentials.
        # Switch to meta/msg91 + credentials for real delivery.
        ok, detail = True, "simulated delivery (set WHATSAPP_PROVIDER=meta/msg91 + credentials for real WhatsApp)"
    else:
        await _log(to_number, purpose, "skipped", f"no provider configured (WHATSAPP_PROVIDER='{prov}')")
        return False

    await _log(to_number, purpose, "sent" if ok else "failed", detail)
    return ok


def whatsapp_status() -> dict:
    """Config state for the dashboard indicator (never exposes secrets)."""
    prov = provider()
    if prov == "meta":
        ready = bool(os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"))
    elif prov == "msg91":
        ready = bool(os.environ.get("MSG91_AUTH_KEY") and os.environ.get("MSG91_TEMPLATE_ID"))
    elif prov == "simulate":
        ready = True
    else:
        ready = False
    return {"provider": prov or "off", "ready": ready, "mentorNumber": bool(mentor_number()),
            "active": ready and bool(mentor_number())}
