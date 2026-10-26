"""Keep the Students sheet's password column equal to what the student can use.

The sheet is the credential ledger this institute already works from: the mentor
reads it, the welcome mail is built from it. But the app stores only a bcrypt
hash, so a password a student changes inside the app can never be written back
afterwards - it is unknown to the server too. The one moment it IS known is the
request that carries it: a successful login, or the change-password call itself.

So this module mirrors the value at that moment. It is deliberately:
  * fire-and-forget - a slow or broken Google API call can never delay a login,
  * deduplicated - the same password is written once, not on every login,
  * silent about secrets - nothing here logs a password, ever,
  * switchable off - PASSWORD_SHEET_SYNC=0 disables every write.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Optional

import bcrypt
import httpx

logger = logging.getLogger(__name__)

SHEET_ID = os.environ.get(
    "TRACKER_SHEET_ID", "1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc"
).strip()
SHEET_TAB = "Students"
ENABLED = (os.environ.get("PASSWORD_SHEET_SYNC", "1") or "1").strip().lower() not in (
    "0", "false", "no", "off",
)
LAYOUT_TTL_SEC = 600
CHANGED_FLAG_TEXT = "Yes"

_sheet_layout: dict = {"at": 0.0, "rows": {}, "pwd_col": None, "changed_col": None}
_written: dict = {}  # studentId -> fingerprint of the value last written
_tasks: set = set()


def _fingerprint(plaintext: str) -> str:
    # A comparison tag only; it is not a credential and is never usable as one.
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:32]


def _col_letter(index: int) -> str:
    out, n = "", index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _token() -> str:
    from routers.notes_inbox import _google_token  # same service account, cached

    return _google_token()


async def _read_range(rng: str) -> list:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{SHEET_TAB}%21{rng}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {_token()}"})
    resp.raise_for_status()
    return resp.json().get("values") or []


async def _write_cell(cell: str, value: str) -> bool:
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{SHEET_TAB}%21{cell}"
        "?valueInputOption=RAW"  # RAW: a password starting with = + - @ stays text
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(
            url,
            json={"values": [[value]]},
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        )
    if resp.status_code >= 400:
        logger.warning("[password-sheet-sync] %s write failed (HTTP %s)", cell, resp.status_code)
        return False
    return int(resp.json().get("updatedCells") or 0) > 0


async def _layout_for() -> dict:
    """Row number per student id, plus which columns hold password + flag."""
    now = time.time()
    if _sheet_layout["rows"] and now - _sheet_layout["at"] < LAYOUT_TTL_SEC:
        return _sheet_layout
    header_rows, id_rows = await asyncio.gather(_read_range("A1:U1"), _read_range("A1:A400"))
    if not header_rows:
        raise RuntimeError("Students sheet header could not be read")
    names = [str(cell or "").strip().lower() for cell in header_rows[0]]
    if "passwords" not in names:
        raise RuntimeError("Students sheet has no 'Passwords' column")
    rows: dict = {}
    for number, row in enumerate(id_rows, start=1):
        sid = str((row or [""])[0] if row else "").strip().upper()
        if sid:
            rows.setdefault(sid, number)
    _sheet_layout.update(
        at=now,
        rows=rows,
        pwd_col=names.index("passwords"),
        changed_col=names.index("password changed") if "password changed" in names else None,
    )
    return _sheet_layout


def reset_cache() -> None:
    """Test/admin hook: forget the cached layout and the dedupe tags."""
    _sheet_layout["at"] = 0.0
    _sheet_layout["rows"] = {}
    _written.clear()


async def write_password(student_id: str, plaintext: str, *, flag_changed: bool = True) -> bool:
    """One sheet write. Raises only for callers that want to know; login never does."""
    sid = str(student_id or "").strip().upper()
    if not sid or not plaintext:
        return False
    layout = await _layout_for()
    row = layout["rows"].get(sid)
    if not row:
        logger.info("[password-sheet-sync] %s is not a row in the Students sheet", sid)
        return False
    ok = await _write_cell(f"{_col_letter(layout['pwd_col'])}{row}", plaintext)
    if ok and flag_changed and layout.get("changed_col") is not None:
        await _write_cell(f"{_col_letter(layout['changed_col'])}{row}", CHANGED_FLAG_TEXT)
    return ok


def mark_written(student_id: str, plaintext: str) -> None:
    """Tell the mirror this value is already in the sheet (a mentor set it by hand).

    Without this, the student's next login re-writes the same cell for no reason: the
    dedupe tag only knows about values the app itself pushed.
    """
    sid = str(student_id or "").strip().upper()
    if sid and plaintext:
        _written[sid] = _fingerprint(plaintext)


def queue_sync(student_id: str, plaintext: Optional[str], *, flag_changed: bool = False) -> None:
    """Schedule a sheet write if this value is not already in the sheet. Never raises.

    `flag_changed` belongs to the caller that KNOWS this is a new password (the
    change-password route). A login mirror must not set it: 'Password Changed' feeds
    passwordChanged on import, and import keeps that account's hash forever once the
    flag is on - so raising it on every login would freeze the sheet column.
    """
    if not ENABLED or not plaintext:
        return
    sid = str(student_id or "").strip().upper()
    if not sid:
        return
    if _written.get(sid) == _fingerprint(plaintext):
        return

    async def run() -> None:
        try:
            if await write_password(sid, plaintext, flag_changed=flag_changed):
                _written[sid] = _fingerprint(plaintext)
                logger.info("[password-sheet-sync] %s: sheet password refreshed", sid)
        except Exception as exc:  # Google down, layout missing, anything
            logger.warning("[password-sheet-sync] %s skipped (%s)", sid, type(exc).__name__)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # a sync context (script, migration): do it inline
        asyncio.run(run())
        return
    task = loop.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ── coverage: which sheet cells are actually usable right now ───────────────
# A cell can be 'valid' (it authenticates), 'marked' (the honest note left when a
# student's own password could not be recovered), 'stale' (a dead password still
# typed in, which is the dangerous one because a mentor would mail it), or
# 'blank'. The mirror shrinks 'marked' + 'stale' on its own as students sign in,
# so this count is the one number that says whether the job is done.
MARKER_PREFIXES = ("CHANGED-IN-APP", "PROBE-")


def coverage_of(sheet_rows: list, accounts: list) -> dict:
    """Classify every active student's sheet password cell. Pure: no Google, no Mongo."""
    if not sheet_rows:
        return {"total": 0, "valid": 0, "marked": 0, "stale": 0, "blank": 0,
                "pending": [], "skipped": {"noHeader": True}}
    names = [str(cell or "").strip().lower() for cell in sheet_rows[0]]
    if "student id" not in names or "passwords" not in names:
        return {"total": 0, "valid": 0, "marked": 0, "stale": 0, "blank": 0,
                "pending": [], "skipped": {"noHeader": True}}
    id_col, pwd_col = names.index("student id"), names.index("passwords")
    flag_col = names.index("password changed") if "password changed" in names else None

    by_sid = {}
    for doc in accounts:
        sid = str(doc.get("studentId") or "").strip().upper()
        if sid:
            by_sid[sid] = doc

    valid = marked = stale = blank = 0
    pending: list = []
    for row in sheet_rows[1:]:
        sid = str(row[id_col] if len(row) > id_col else "").strip().upper()
        if not sid.startswith("UMP") or sid in ("UMP0000", "UMP9999"):
            continue  # master logins are not students and carry no sheet row
        account = by_sid.get(sid)
        if account is None or account.get("removedAt"):
            continue
        value = str(row[pwd_col] if len(row) > pwd_col else "").strip()
        hashed = str(account.get("passwordHash") or "")
        if not value:
            blank += 1
            pending.append({"studentId": sid, "studentName": str(account.get("studentName") or ""),
                            "state": "blank"})
            continue
        works = bcrypt.checkpw(value.encode(), hashed.encode()) if hashed else value == str(account.get("password") or "")
        if works:
            valid += 1
            continue
        if value.startswith(MARKER_PREFIXES):
            marked += 1
            state = "marked"
        else:
            stale += 1
            state = "stale"
        pending.append({
            "studentId": sid,
            "studentName": str(account.get("studentName") or ""),
            "state": state,
            "loggedFlag": str(row[flag_col] if flag_col is not None and len(row) > flag_col else "").strip(),
        })
    pending.sort(key=lambda item: item["studentId"])
    total = valid + marked + stale + blank
    return {"total": total, "valid": valid, "marked": marked, "stale": stale, "blank": blank,
            "pending": pending, "skipped": {}}
