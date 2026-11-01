"""Mentor access ON/OFF history + the makeup time it unlocks.

Why this exists (15-Oct-2026): a test published while a student's access was OFF could
not be opened at all — login blocks with `access_blocked` — but the window still ran
out. So un-blocking them later fixed nothing, and the phone had already buzzed with
"New test published". Students experienced that as the app losing their test.

Contract here:
  * every access toggle is logged (one place writes it: set_student_access);
  * a student's personal test window is extended by exactly the time they were locked
    out *inside* that window — never more, and capped (owner decision: automatic);
  * the mentor's own view is never shifted, only the affected student's.

Timestamps are ISO-8601 UTC strings, the same shape `student_accounts.accessUpdatedAt`
already uses, so a mixed history (legacy rows without events) still compares sanely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from db import (
    ANALYTICS_TEST_HISTORY,
    DASHBOARD_SHARED,
    MENTOR_TESTS,
    STUDENT_ACCESS_EVENTS,
)

MAKEUP_CAP_DAYS = 14
_ZERO = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value) -> Optional[datetime]:
    """Best-effort ISO parser for both `...T18:00` (window fields) and full
    `...+00:00` timestamps. Naive values are read as UTC, which is what
    window_state() already assumes."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in (text[:19], text):
        try:
            stamp = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp
    try:  # date-only, e.g. "2026-10-14"
        return datetime.fromisoformat(text[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def as_utc(value, *, end_of_day: bool = False) -> Optional[datetime]:
    """`datetime` stays, ISO strings are parsed. `end_of_day` rounds a bare date up
    to 23:59 so a window stored as a date is not treated as over at 00:01."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    stamp = parse_ts(value)
    if stamp is None:
        return None
    text = str(value).strip()
    if end_of_day and len(text) == 10:
        stamp = stamp.replace(hour=23, minute=59, second=59)
    return stamp


async def log_access_event(db, student_id: str, enabled: bool, *, reason: str = "",
                           by: str = "", at: Optional[str] = None) -> dict:
    """Append one toggle. Only real changes are logged by the caller, so the list of
    events is a true ON/OFF timeline."""
    doc = {
        "studentId": student_id,
        "enabled": bool(enabled),
        "at": at or _now_iso(),
        "reason": (reason or "")[:300],
        "by": by or "mentor",
    }
    await db[STUDENT_ACCESS_EVENTS].insert_one(dict(doc))
    return doc


async def off_intervals(db, student_id: str, account: Optional[dict] = None,
                        until: Optional[datetime] = None) -> list[tuple[datetime, datetime]]:
    """Periods this student's access was OFF, oldest first, the open one closed at `until`.

    Legacy students have no events (toggles predate logging). Their one known anchor is
    `accessUpdatedAt`: if they are OFF right now, that is when the lockout started, so the
    interval is real. If they are ON with no events, history is genuinely unknown and we
    invent nothing — no credit, no false makeup.
    """
    now = until or datetime.now(timezone.utc)
    rows = await db[STUDENT_ACCESS_EVENTS].find({"studentId": student_id}).sort("at", 1).to_list(1000)
    spans: list[tuple[datetime, datetime]] = []
    open_from: Optional[datetime] = None
    for row in rows:
        stamp = as_utc(row.get("at"))
        if stamp is None:
            continue
        if row.get("enabled"):
            if open_from is not None:
                spans.append((open_from, stamp))
                open_from = None
        else:
            open_from = stamp
    if open_from is not None:
        spans.append((open_from, now))
    if spans or not account or account.get("accessEnabled") is not False:
        return spans
    legacy_start = as_utc(account.get("accessUpdatedAt")) or _ZERO
    return [(legacy_start, now)]


def locked_out_minutes(spans: Iterable[tuple[datetime, datetime]], start: datetime,
                       end: datetime) -> int:
    """Minutes of `spans` that fall inside [start, end], capped at MAKEUP_CAP_DAYS.

    Only time lost *inside* the window counts: being locked out after a window closed
    takes nothing away that the student could have used, so it must not buy extra days.
    """
    if not start or not end or end <= start:
        return 0
    total = 0.0
    for from_stamp, to_stamp in spans:
        overlap_from = max(start, from_stamp)
        overlap_to = min(end, to_stamp)
        if overlap_to > overlap_from:
            total += (overlap_to - overlap_from).total_seconds() / 60.0
    if total <= 0:
        return 0
    return int(min(total, MAKEUP_CAP_DAYS * 24 * 60))


def shifted_view(test: dict, extra_minutes: int) -> dict:
    """The test as THIS student should see it: same document, closing moment pushed
    out by their makeup credit. One definition, so the list, the paper and the submit
    guard can never disagree about whether the window is still open for them.
    """
    if extra_minutes <= 0 or not test.get("window_end"):
        return test
    end = as_utc(test.get("window_end"), end_of_day=True)
    if end is None:
        return test
    return {**test, "window_end": (end + timedelta(minutes=extra_minutes)).strftime("%Y-%m-%dT%H:%M")}


def credit_for(spans, test: dict, now: Optional[datetime] = None) -> int:
    """Minutes this student should get back for one test, from a pre-read timeline.

    The whole rule lives here so the list, the paper gate and the submit tag cannot
    drift apart: no `window_end` means the test is always open (nothing was missed),
    and a window that has not closed yet is not overdues either.
    """
    end = as_utc(test.get("window_end"), end_of_day=True)
    if not end:
        return 0
    moment = now or datetime.now(timezone.utc)
    if end > moment:
        return 0
    start = as_utc(test.get("window_start")) or as_utc(test.get("createdAt")) or _ZERO
    return locked_out_minutes(spans, start, end)


async def makeup_minutes(db, student_id: str, test: dict, account: Optional[dict] = None,
                         until: Optional[datetime] = None) -> int:
    """`credit_for` with the student's lockout timeline read from Mongo."""
    spans = await off_intervals(db, student_id, account, until=until)
    return credit_for(spans, test, until)


async def pending_after_restore(db, account: dict, since=None) -> dict:
    """What is waiting for a student the moment access comes back on.

    Used only for the welcome-back push text, so it is deliberately forgiving: an
    unread note or a stale test count never blocks the restore itself.
    """
    import push as push_service  # local import: push reads accounts, no cycle

    sid = str(account.get("studentId") or "").strip().upper()
    since_stamp = as_utc(since)
    tests = 0
    test_titles: list[str] = []
    rows = await db[ANALYTICS_TEST_HISTORY].find({"studentId": sid}, {"_id": 0, "testId": 1}).to_list(5000)
    attempted = {str(row.get("testId") or "") for row in rows}
    published = await db[MENTOR_TESTS].find(
        {"published": True}, {"_id": 0, "testId": 1, "title": 1, "batch": 1, "group": 1}
    ).to_list(500)
    for test in published:
        tid = str(test.get("testId") or "")
        if not tid or tid in attempted:
            continue
        if push_service.matches_audience(test, account):
            tests += 1
            if len(test_titles) < 3:
                test_titles.append(str(test.get("title") or "Test"))

    notes = 0
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}, {"_id": 0, "notes": 1}) or {}
    for row in shared.get("notes") or []:
        if not isinstance(row, dict):
            continue
        date = as_utc(row.get("date"))
        if since_stamp and date and date < since_stamp:
            continue
        if push_service.matches_audience(row, account):
            notes += 1
    return {"tests": tests, "notes": notes, "testTitles": test_titles}


def restore_message(counts: dict) -> tuple[str, str]:
    tests = int(counts.get("tests") or 0)
    notes = int(counts.get("notes") or 0)
    if not tests and not notes:
        return "🔓 Access restored", "Your app is open again. Open it to continue your study log."
    bits = []
    if tests:
        bits.append(f"{tests} test{'' if tests == 1 else 's'} waiting")
    if notes:
        bits.append(f"{notes} new note{'' if notes == 1 else 's'}")
    return "🔓 Access restored — you missed work", " and ".join(bits) + ". Open the app to catch up."


__all__ = [
    "MAKEUP_CAP_DAYS",
    "as_utc",
    "get_db",
    "credit_for",
    "locked_out_minutes",
    "log_access_event",
    "makeup_minutes",
    "pending_after_restore",
    "shifted_view",
    "off_intervals",
    "restore_message",
]
