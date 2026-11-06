"""Mentor tab: Password reset — set a student's password and have the Students sheet follow.

Why this exists: a student who is told "Incorrect password" has no way to fix it
themselves (no self-service reset in the app), and the mentor's only record of the
working value is the sheet. So today the flow was: student WhatsApps, mentor opens the
sheet, types something, tells the student, and hopes the app's own account matches.
Half the time it did not, because the app and the sheet were two different answers to
the same question.

This closes that loop in one screen:

  * the queue is built from the same sheet that the mentor reads, so batch + group
    labels here mean the same thing as on the submissions tab;
  * students whose sign-ins are failing are listed first (login_failures), and the list
    empties itself as soon as they get in;
  * every reset writes BOTH the app account and the sheet's `Passwords` cell, and the
    response says in words whether the sheet write succeeded — a silently dead ledger
    cell is what created this mess in the first place;
  * nothing here sends, schedules or repeats anything. The password is shown once, to
    the mentor, for them to pass on. It is not stored, not logged and not pushed.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import login_failures
import password_sheet_sync
import sheet_coverage
from auth import hash_password, require_mentor
from db import ANALYTICS_AUDIT_SYNC, STUDENT_ACCOUNTS, get_db
from routers.test_history import _bucket, _group_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/password-reset", tags=["passwords"])

MIN_LEN = 6            # same floor the student's own change-password route uses
MAX_LEN = 64
AUDIT_ACTION = "password_reset"
SEVERITY = {"stale": 0, "blank": 1, "marked": 2, "noRow": 3, "ok": 4}
# House style in this sheet is Word@1234 (30 of the live rows), so generated values
# look like the rest of the column and can be dictated over WhatsApp without spelling.
_SYLLABLES = ("ka", "ri", "me", "tu", "na", "vi", "sha", "le", "do", "mi", "pu", "ra")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_password() -> str:
    """A word-like password a student can actually type on a phone."""
    word = "".join(secrets.choice(_SYLLABLES) for _ in range(3))
    return f"{word.capitalize()}@{secrets.randbelow(9000) + 1000}"


def _clean_password(raw) -> str:
    """Trim, then check. Whitespace inside is kept: it is 2026 and people use passphrases."""
    pwd = str(raw or "").strip()
    if not pwd:
        return ""
    if len(pwd) < MIN_LEN:
        raise HTTPException(status_code=400, detail=f"Password is too short — use at least {MIN_LEN} characters.")
    if len(pwd) > MAX_LEN:
        raise HTTPException(status_code=400, detail=f"Password is too long (max {MAX_LEN} characters).")
    if re.search(r"\s{2,}", pwd):
        raise HTTPException(status_code=400, detail="Password has too much whitespace — check for a stray blank line.")
    return pwd


# ── the sheet, read once per request and shared ──────────────────────────── #
_sheet_cache: dict = {"at": None, "rows": [], "ok": False}
SHEET_TTL_SEC = 90


async def _sheet(force: bool = False) -> tuple[list, bool]:
    now = datetime.now(timezone.utc)
    if (
        not force
        and _sheet_cache["ok"]
        and _sheet_cache["at"]
        and (now - _sheet_cache["at"]).total_seconds() < SHEET_TTL_SEC
    ):
        return _sheet_cache["rows"], True
    from routers import student_auth as sa  # imported late so the sheet reader is swappable

    try:
        rows = await sa._sheet_students_rows()
    except Exception as exc:  # noqa: BLE001 - the tab must still work without Google
        logger.warning("[password-reset] sheet read failed: %s", type(exc).__name__)
        return _sheet_cache["rows"], False
    _sheet_cache.update(at=now, rows=rows, ok=bool(rows))
    return rows, bool(rows)


def _by_sid_from_sheet(rows: list) -> dict:
    """studentId -> {studentName, batch, groups, password, changedFlag} from the sheet."""
    if not rows:
        return {}
    header = [str(h or "").strip().lower() for h in rows[0]]

    def col(*names: str) -> int:
        for name in names:
            if name in header:
                return header.index(name)
        return -1

    i_sid, i_name = col("student id", "studentid", "id"), col("student name", "name")
    i_grp, i_batch = col("group"), col("batch")
    i_pwd, i_flag = col("passwords", "password"), col("password changed", "changed")
    if i_sid < 0:
        return {}
    out: dict[str, dict] = {}
    for row in rows[1:]:
        def cell(idx: int) -> str:
            return str(row[idx]).strip() if 0 <= idx < len(row) else ""

        sid = cell(i_sid).upper()
        if not sid.startswith("UMP") or sid in ("UMP0000", "UMP9999"):
            continue
        out[sid] = {
            "studentName": cell(i_name),
            "batch": cell(i_batch),
            "bucket": _bucket(cell(i_grp)),
            "groupText": _group_text(cell(i_grp)),
            "password": cell(i_pwd),
            "changedFlag": cell(i_flag),
        }
    return out


# ── the shared pieces: accounts, and the sheet's verdict on each one ─────── #
# passwordHash is fetched for one reason: coverage_of asks "does the sheet cell still
# authenticate?". Without the hash every row reads as stale, which would make this whole
# tab a lie on day one. It is used for that check and never returned to the browser.
ACC_PROJECTION = {"studentId": 1, "studentName": 1, "batch": 1, "group": 1, "removedAt": 1,
                  "accessEnabled": 1, "passwordChanged": 1, "forcePasswordChange": 1,
                  "lastLoginAt": 1, "passwordHash": 1, "password": 1}


async def _accounts_and_states(db, rows: list, only: set | None = None) -> tuple[dict, dict, dict]:
    """(accounts by id, sheet state by id, coverage totals).

    `only` narrows which accounts are considered, so a search does not classify 160
    rows for one hit.
    """
    accounts: dict[str, dict] = {}
    docs: list[dict] = []
    async for acc in db[STUDENT_ACCOUNTS].find({}, ACC_PROJECTION):
        sid = str(acc.get("studentId") or "").strip().upper()
        if not sid or (only is not None and sid not in only):
            continue
        accounts[sid] = acc
        docs.append(acc)
    if only is None:
        # Whole-ledger classification. It is served from the shared cache so
        # this screen opens at once instead of standing still for the two
        # minutes a full bcrypt sweep used to take.
        from routers import student_auth as sa

        try:
            coverage = await sheet_coverage.coverage_for(sa._coverage_payload, refresh=False)
        except Exception as exc:  # noqa: BLE001 - keep the reset queue available when the sheet is down
            logger.warning("[password-reset] coverage read failed: %s", type(exc).__name__)
            # The queue can still report login failures from Mongo. Sheet state is
            # unavailable, so don't claim any cells are valid or stale.
            coverage = {
                "pending": [],
                "total": 0,
                "valid": 0,
                "marked": 0,
                "stale": 0,
                "blank": 0,
            }
    else:
        # A search covers a handful of students - classify just those.
        coverage = await asyncio.to_thread(password_sheet_sync.coverage_of, rows or [], docs)
    state_of = {p["studentId"]: p["state"] for p in coverage.get("pending", [])}
    return accounts, state_of, coverage


# ── queue: who needs a password today ────────────────────────────────────── #
@router.get("/queue")
async def password_reset_queue(days: int = 7, refresh: bool = False, claims: dict = Depends(require_mentor)):
    """Students whose logins are failing, plus everyone whose sheet cell is unusable.

    Two different kinds of stuck, shown together because the mentor's action is the same:
      * `openFails` — they tried to sign in and were refused;
      * `stale` / `blank` / `marked` — the sheet holds a value that would not work
        (or none at all), so the next student who asks is already a complaint.
    A student who gets in has their failure count cleared, which is what keeps this list
    honest instead of a pile of old grievances.
    """
    days = max(1, min(int(days or 7), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = get_db()
    rows, sheet_ok = await _sheet(force=bool(refresh))
    sheet_rows = _by_sid_from_sheet(rows)
    # coverage_of is the same classifier the password meter uses, so "stale" here means
    # exactly what it means on that screen - one definition of a bad sheet cell.
    accounts, state_of, coverage = await _accounts_and_states(db, rows)
    failures = await login_failures.summary(db)

    sids = set()
    for sid, fail in failures.items():
        last = str(fail.get("lastFailAt") or "")[:19]
        try:
            recent = datetime.fromisoformat(last) if last else None
        except ValueError:
            recent = None
        in_window = bool(recent and recent.replace(tzinfo=timezone.utc) >= cutoff)
        if fail.get("openFails") or (in_window and not fail.get("lastOkAt")):
            sids.add(sid)
    for sid in state_of:
        sids.add(sid)

    out: list[dict] = []
    for sid in sids:
        acc = accounts.get(sid) or {}
        sh = sheet_rows.get(sid) or {}
        fail = failures.get(sid) or {}
        state = state_of.get(sid) or ("ok" if sh else "noRow")
        if acc.get("removedAt"):
            continue  # left the program: nobody owes them a password
        out.append({
            "studentId": sid,
            "studentName": sh.get("studentName") or acc.get("studentName") or sid,
            "batch": sh.get("batch") or acc.get("batch") or "",
            "groupText": sh.get("groupText") or _group_text(acc.get("group")),
            "bucket": sh.get("bucket") or _bucket(acc.get("group")),
            "scopeFrom": "sheet" if sh else ("accounts" if acc else ""),
            "sheetState": state,
            "sheetHasValue": bool(sh.get("password")),
            "changedFlag": sh.get("changedFlag") or "",
            "hasAccount": bool(acc),
            "accessEnabled": acc.get("accessEnabled") is not False if acc else False,
            "passwordChanged": bool(acc.get("passwordChanged")) if acc else False,
            "forcePasswordChange": bool(acc.get("forcePasswordChange")) if acc else False,
            "lastLoginAt": acc.get("lastLoginAt") or "",
            "fails": int(fail.get("fails") or 0),
            "openFails": int(fail.get("openFails") or 0),
            "lastFailAt": fail.get("lastFailAt") or "",
            "lastFailCode": fail.get("lastFailCode") or "",
            "lastOkAt": fail.get("lastOkAt") or "",
            "resetAt": fail.get("resetAt") or "",
        })
    out.sort(key=lambda r: (
        0 if r["openFails"] else 1,
        -int(r["openFails"] or 0),
        SEVERITY.get(r["sheetState"], 5),
        str(r["lastFailAt"] or ""),
        r["studentId"],
    ))
    stuck = [r for r in out if r["openFails"]]
    return {
        "ok": True,
        "days": days,
        "checkedAt": _now(),
        "sheetOk": sheet_ok,
        "sheetNote": "" if sheet_ok else "Students sheet could not be read — sheet states below are unknown, not clean.",
        "counts": {
            "listed": len(out),
            "failingNow": len(stuck),
            "stale": sum(1 for r in out if r["sheetState"] == "stale"),
            "blank": sum(1 for r in out if r["sheetState"] == "blank"),
            "marked": sum(1 for r in out if r["sheetState"] == "marked"),
            "noAccount": sum(1 for r in out if not r["hasAccount"]),
        },
        "meter": {k: coverage.get(k) for k in ("total", "valid", "marked", "stale", "blank")},
        "usablePct": round(100 * coverage.get("valid", 0) / coverage["total"], 1) if coverage.get("total") else 0,
        "rows": out,
    }


@router.get("/students")
async def password_reset_students(q: str = "", claims: dict = Depends(require_mentor)):
    """Search any student by id or name, for a reset the queue did not surface.

    The queue only shows people who are provably stuck; a mentor also gets asked for a
    password by a student who has never tried to log in. Same row shape, so the card
    they act on is one component rather than two.
    """
    query = str(q or "").strip().upper()
    if len(query) < 2:
        return {"ok": True, "rows": []}
    db = get_db()
    rows, sheet_ok = await _sheet()
    sheet_rows = _by_sid_from_sheet(rows)
    failures = await login_failures.summary(db)

    matched: set[str] = set()
    async for acc in db[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "studentName": 1, "removedAt": 1}):
        sid = str(acc.get("studentId") or "").strip().upper()
        name = str(acc.get("studentName") or "").upper()
        if sid and (query in sid or query in name) and not acc.get("removedAt"):
            matched.add(sid)
    accounts, state_of, _cov = await _accounts_and_states(db, rows, only=matched)

    hits: dict[str, dict] = {}
    for sid in sorted(matched):
        acc = accounts.get(sid) or {}
        if not acc:
            continue
        sh = sheet_rows.get(sid) or {}
        fail = failures.get(sid) or {}
        hits[sid] = {
            "studentId": sid,
            "studentName": sh.get("studentName") or acc.get("studentName") or sid,
            "batch": sh.get("batch") or acc.get("batch") or "",
            "groupText": sh.get("groupText") or _group_text(acc.get("group")),
            "bucket": sh.get("bucket") or _bucket(acc.get("group")),
            "scopeFrom": "sheet" if sh else "accounts",
            "sheetState": state_of.get(sid) or ("ok" if sh.get("password") else ("noRow" if not sh else "blank")),
            "sheetHasValue": bool(sh.get("password")),
            "changedFlag": sh.get("changedFlag") or "",
            "hasAccount": True,
            "accessEnabled": acc.get("accessEnabled") is not False,
            "passwordChanged": bool(acc.get("passwordChanged")),
            "lastLoginAt": acc.get("lastLoginAt") or "",
            "fails": int(fail.get("fails") or 0),
            "openFails": int(fail.get("openFails") or 0),
            "lastFailAt": fail.get("lastFailAt") or "",
        }
    return {"ok": True, "sheetOk": sheet_ok, "rows": sorted(hits.values(), key=lambda r: r["studentId"])[:40]}


# ── the reset itself ────────────────────────────────────────────────────── #
class ResetBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: str = Field(min_length=3, max_length=24)
    # Blank means "you choose one for me" — the mentor mostly does not want to invent one.
    password: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=200)
    # Ask them to set their own on next login. On by default: a password the mentor
    # knows should not be the one that keeps working forever.
    forceChange: bool = True
    syncSheet: bool = True


async def _audit(db, action: str, who: str, detail: dict) -> None:
    try:
        await db[ANALYTICS_AUDIT_SYNC].insert_one({"at": _now(), "studentId": who, "action": action, "detail": detail})
    except Exception as exc:  # noqa: BLE001 - an audit write never blocks a reset
        logger.warning("[password-reset] audit skipped (%s)", type(exc).__name__)


@router.post("/set")
async def set_password(body: ResetBody, claims: dict = Depends(require_mentor)):
    """Set a student's password in the app AND in the Students sheet, and show it once.

    Order matters: the app is written first (so a Google outage cannot leave the sheet
    holding a value the app has never accepted), then the sheet mirror is awaited rather
    than fired-and-forgotten, because the mentor needs to be told whether the ledger is
    now truthful or still needs a retry.
    """
    sid = str(body.studentId or "").strip().upper()
    wanted = _clean_password(body.password)
    generated = not wanted
    if generated:
        wanted = generate_password()
    db = get_db()
    acc = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": sid}, {"studentId": 1, "studentName": 1, "removedAt": 1, "accessEnabled": 1}
    )
    if not acc:
        rows, _ = await _sheet()
        in_sheet = sid in _by_sid_from_sheet(rows)
        raise HTTPException(
            status_code=404,
            detail=(
                f"{sid} has no app account yet, so there is nothing to reset. "
                + ("Add the login first (Students → import from sheet)." if in_sheet else
                   "That ID is not in the Students sheet either — check the number.")
            ),
        )
    if acc.get("removedAt"):
        raise HTTPException(status_code=409, detail=f"{sid} has been removed from the program; restore them first.")

    # passwordChanged stays True on purpose: an import from the sheet must not knock the
    # account back to whatever cell the sheet held yesterday. forcePasswordChange is what
    # makes the app ask for their own password the first time they get in.
    await db[STUDENT_ACCOUNTS].update_one(
        {"studentId": sid},
        {
            "$set": {
                "passwordHash": hash_password(wanted),
                "passwordChanged": True,
                "forcePasswordChange": bool(body.forceChange),
                "passwordResetAt": _now(),
                "passwordResetBy": str(claims.get("sub") or "mentor"),
                "passwordResetNote": str(body.note or "")[:200],
                "updatedAt": _now(),
            },
            "$unset": {"password": "", "sheetPasswordResyncPending": ""},
        },
    )

    sheet_written = None
    sheet_error = ""
    if body.syncSheet:
        try:
            # flag_changed=False: the student has not changed anything yet, and this
            # flag feeds passwordChanged on import — raising it now would freeze the
            # cell to a value nobody chose.
            sheet_written = bool(await password_sheet_sync.write_password(sid, wanted, flag_changed=False))
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            sheet_written = False
            sheet_error = type(exc).__name__
        if not sheet_written and not sheet_error:
            sheet_error = "no sheet row for this student"

    # The complaint is answered: drop them off the failing list so the queue shows who is
    # stuck NOW, not everyone who was stuck this week.
    await login_failures.clear(db, sid)
    await _audit(db, AUDIT_ACTION, str(claims.get("sub") or "mentor"), {
        "studentId": sid,
        "generated": generated,
        "length": len(wanted),
        "forceChange": bool(body.forceChange),
        "syncSheet": bool(body.syncSheet),
        "sheetWritten": sheet_written,
        "sheetError": sheet_error,
        "note": str(body.note or "")[:200],
    })
    return {
        "ok": True,
        "studentId": sid,
        "studentName": acc.get("studentName") or sid,
        # Shown once, deliberately: not stored, not logged, not pushed anywhere.
        "password": wanted,
        "generated": generated,
        "forceChange": bool(body.forceChange),
        "sheetWritten": sheet_written,
        "sheetError": sheet_error,
        "message": (
            "Password set in the app and written to the Students sheet."
            if sheet_written else
            "Password works in the app, but the sheet was NOT updated — copy the value "
            "and use 'Update the sheet cell' to retry, or type it into the sheet yourself."
        ),
    }


class SheetSyncBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    studentId: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=1, max_length=128)


@router.post("/sheet-sync")
async def sheet_sync(body: SheetSyncBody, claims: dict = Depends(require_mentor)):
    """Re-send a value the mentor is still looking at, after a failed sheet write.

    Refuses anything that is not that student's live password: the sheet is the ledger
    the welcome mail is built from, and one dead cell there is worse than a blank one.
    """
    sid = str(body.studentId or "").strip().upper()
    pwd = str(body.password or "").strip()
    db = get_db()
    acc = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid}, {"passwordHash": 1, "password": 1})
    if not acc:
        raise HTTPException(status_code=404, detail=f"{sid} has no app account.")
    from auth import verify_password

    live = str(acc.get("passwordHash") or "")
    ok_value = verify_password(pwd, live) if live else pwd == str(acc.get("password") or "")
    if not ok_value:
        raise HTTPException(status_code=400, detail="That password is not what this account accepts — it would put a dead value in the sheet.")
    written = bool(await password_sheet_sync.write_password(sid, pwd, flag_changed=False))
    if written:
        password_sheet_sync.mark_written(sid, pwd)
    await _audit(db, f"{AUDIT_ACTION}_sheet_sync", str(claims.get("sub") or "mentor"), {"studentId": sid, "written": written})
    return {"ok": written, "studentId": sid, "sheetWritten": written}


@router.get("/history")
async def password_reset_history(limit: int = 40, claims: dict = Depends(require_mentor)):
    """Who reset whom and when. Passwords are never part of this record."""
    n = max(1, min(int(limit or 40), 200))
    db = get_db()
    cursor = db[ANALYTICS_AUDIT_SYNC].find({"action": {"$regex": "^password_reset"}}).sort("at", -1)
    try:
        docs = await cursor.to_list(n)
    except AttributeError:
        docs = list(cursor)[:n]
    for doc in docs:
        doc.pop("_id", None)
    return {"ok": True, "entries": docs}
