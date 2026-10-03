"""Emergency one-shot reset of four student logins (idempotent).

Why
---
UMP0043, UMP0081, UMP0088 and UMP0090 were left with a stale/unknown local
password hash in Mongo while the Students sheet still holds their real
password. They cannot sign in. This module puts those four accounts back on
their **existing Sheet password** and makes the app ask them to set a new one
on first login. Nothing else about the account is touched: name, email,
CA level, group, attempt, batch, phone, address, joinedOn, WhatsApp number,
MCQ attempts, analytics, messages and every other collection are preserved.

Two supported password sources (first one that yields a value wins):

1. **Explicit Sheet passwords** — ``ACCOUNT_RESET_SHEET_PASSWORDS`` env var,
   either JSON (``{"UMP0043": "...", ...}``) or ``UMP0043:pass,UMP0081:pass``.
   Set it as an *encrypted* Koyeb secret; never commit passwords to Git.
   The account is immediately usable with the Sheet password.

2. **Sheet re-sync (default, no secrets needed)** — the account is flagged so
   the next Students-sheet import (`POST /api/student-auth/import`, which
   already carries the Sheet password) re-applies the Sheet password.
   `upsert_student_account()` only keeps a local password when
   ``passwordChanged`` is true, so clearing that flag hands authority back to
   the sheet. ``forcePasswordChange`` survives the import.

Idempotency
-----------
A marker document is written to the ``migrations`` collection
(``key = account_reset_2026_10_four_accounts``). Every later run — on every
boot, every redeploy — is a no-op, so a student who has already picked a new
password is never knocked back to the Sheet password. ``force=True``
(or ``ACCOUNT_RESET_FORCE=1``) deliberately re-runs it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from auth import hash_password
from db import MIGRATIONS, STUDENT_ACCOUNTS, get_db

logger = logging.getLogger(__name__)

# The exact four accounts in scope. Nothing outside this tuple is touched.
RESET_STUDENT_IDS: tuple[str, ...] = ("UMP0043", "UMP0081", "UMP0088", "UMP0090")

# Idempotency marker key (bump the suffix only for a genuinely new reset).
MARKER_KEY = "account_reset_2026_10_four_accounts"

# Fields the reset is allowed to write. Anything else on the document is
# preserved exactly as-is.
_PASSWORD_FIELDS = ("passwordHash", "passwordChanged", "forcePasswordChange")

_SHEET_PASSWORD_ENV = "ACCOUNT_RESET_SHEET_PASSWORDS"
_FORCE_ENV = "ACCOUNT_RESET_FORCE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_id(raw: str) -> str:
    from routers.student_auth import normalize_student_id

    return normalize_student_id(raw)


def parse_sheet_passwords(raw: Optional[str]) -> dict[str, str]:
    """Parse ``{"UMP0043": "pw"}`` JSON or ``UMP0043:pw,UMP0081:pw`` pairs."""
    text = str(raw or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            logger.error("[account-reset] %s is not valid JSON — ignoring", _SHEET_PASSWORD_ENV)
            return {}
        if isinstance(data, Mapping):
            for key, value in data.items():
                sid, pwd = _normalize_id(key), str(value or "").strip()
                if sid and pwd:
                    parsed[sid] = pwd
        return parsed
    for chunk in text.replace("\n", ",").split(","):
        if ":" not in chunk:
            continue
        key, _, value = chunk.partition(":")
        sid, pwd = _normalize_id(key), value.strip()
        if sid and pwd:
            parsed[sid] = pwd
    return parsed


def sheet_passwords_from_env() -> dict[str, str]:
    return parse_sheet_passwords(os.environ.get(_SHEET_PASSWORD_ENV))


async def marker_doc() -> Optional[dict]:
    db = get_db()
    return await db[MIGRATIONS].find_one({"key": MARKER_KEY})


async def already_applied() -> bool:
    return await marker_doc() is not None


async def reset_accounts(
    student_ids: Iterable[str] = RESET_STUDENT_IDS,
    passwords: Optional[Mapping[str, str]] = None,
    force: bool = False,
) -> dict:
    """Apply the four-account reset. Safe to call on every boot.

    Returns a summary dict: ``{"ok", "applied", "skipped", "accounts": [...]}``.
    """
    db = get_db()
    ids = [sid for sid in (_normalize_id(s) for s in student_ids) if sid]
    supplied = {
        _normalize_id(k): str(v).strip()
        for k, v in (passwords if passwords is not None else sheet_passwords_from_env()).items()
        if str(v or "").strip()
    }

    existing_marker = await marker_doc()
    if existing_marker is not None and not force:
        logger.info("[account-reset] marker %s present — nothing to do", MARKER_KEY)
        return {
            "ok": True,
            "applied": False,
            "skipped": True,
            "reason": "already_applied",
            "key": MARKER_KEY,
            "appliedAt": existing_marker.get("appliedAt"),
            "accounts": existing_marker.get("accounts", []),
        }

    results: list[dict] = []
    for sid in ids:
        doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
        if not doc:
            logger.warning("[account-reset] %s not found in %s — skipped", sid, STUDENT_ACCOUNTS)
            results.append({"studentId": sid, "status": "not_found", "mode": None})
            continue

        pwd = supplied.get(sid)
        if pwd:
            # Sheet password known → restore it right now.
            update_set = {
                "passwordHash": hash_password(pwd),
                "passwordChanged": False,
                "forcePasswordChange": True,
                "passwordResetAt": _now(),
                "passwordResetBy": MARKER_KEY,
                "sheetPasswordResyncPending": False,
                "updatedAt": _now(),
            }
            mode = "sheet_password_applied"
        else:
            # No secret supplied → hand password authority back to the sheet.
            # The next Students-sheet import re-applies the Sheet password
            # because `passwordChanged` is false.
            update_set = {
                "passwordChanged": False,
                "forcePasswordChange": True,
                "sheetPasswordResyncPending": True,
                "passwordResetAt": _now(),
                "passwordResetBy": MARKER_KEY,
                "updatedAt": _now(),
            }
            mode = "awaiting_sheet_resync"

        await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid},
            {"$set": update_set, "$unset": {"password": ""}},
        )
        logger.info("[account-reset] %s reset (%s)", sid, mode)
        results.append({"studentId": sid, "status": "reset", "mode": mode})

    if not any(r["status"] == "reset" for r in results):
        # None of the four accounts exist yet (e.g. the API booted before the
        # Students-sheet import). Do NOT write the marker — otherwise the real
        # reset would be permanently skipped once the accounts appear.
        logger.warning(
            "[account-reset] no target account present yet — marker not written, "
            "the reset will be retried on the next boot"
        )
        return {
            "ok": True,
            "applied": False,
            "skipped": True,
            "reason": "no_accounts_found",
            "key": MARKER_KEY,
            "accounts": results,
        }

    marker = {
        "key": MARKER_KEY,
        "appliedAt": _now(),
        "studentIds": ids,
        "accounts": results,
        "forced": bool(force),
        "touchedFields": list(_PASSWORD_FIELDS),
        "note": (
            "Emergency reset to Sheet passwords with forced password change. "
            "Only password fields were written; all other student data preserved."
        ),
    }
    await db[MIGRATIONS].update_one({"key": MARKER_KEY}, {"$set": marker}, upsert=True)

    return {
        "ok": True,
        "applied": True,
        "skipped": False,
        "key": MARKER_KEY,
        "appliedAt": marker["appliedAt"],
        "accounts": results,
    }


async def run_account_reset_on_boot() -> Optional[dict]:
    """Startup hook. Never raises — a failed reset must not take the API down."""
    try:
        return await reset_accounts(force=_truthy(os.environ.get(_FORCE_ENV, "")))
    except Exception:  # pragma: no cover - defensive
        logger.exception("[account-reset] failed")
        return None


async def _main() -> None:  # pragma: no cover - manual operator tool
    logging.basicConfig(level=logging.INFO)
    summary = await reset_accounts(force=_truthy(os.environ.get(_FORCE_ENV, "")))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover - manual operator tool
    asyncio.run(_main())
