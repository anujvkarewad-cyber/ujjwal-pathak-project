"""Behavior-based push notifications ("Zomato-style") driven by the mentor's template sheet.

Every template comes from the mentor-approved sheet "Super75_Chatpate_Study_Notifications"
(183 rows, exported to notification_templates.json next to this file). The sheet also
carries the intended trigger per row; this module turns those triggers into rules.

Daily rhythm (IST), one job per moment — each job is idempotent per day via PUSH_JOBS:

  23:00  tracker_night      TODAY's study log missing -> sheet "Tracker Reminder"
  07:00  (push_scheduler)   YESTERDAY's study log missing -> streak reminder
  14:00  tracker_final      YESTERDAY still missing -> final reminder
  09:00  weekday rotation   Mon..Sun template for everyone         (mood)
  11:00  inactive           2+ days with no study log              (status)
  17:00  target_overdue     yesterday's tasks still incomplete     (status)
  18:00  evening nudge      profile-based rotation                 (mood)
  18:00  test_upcoming      test scheduled tomorrow                (status)
  20:30  target_pending / no_study_today                            (status)
  Sun 19:00  weekly_review  folded into the weekly report push     (status)

The 23:00/07:00/14:00 tracker flow only fires when the day in question was NOT
submitted yet ("agar kisine pehle hi submit kiya ho to na bheje").

Events:  all daily targets completed -> celebration (target_completed, or
         difficult_chapter on a heavy 3+ task day).

Safety rails: mood pushes max 2/day, status max 1/day, celebration max 1/day,
tracker reminders max 3/day counting ALL THREE touch-points (the 07:00 streak job
used to bypass this - it is capped and logged now), same template never repeats
within DEDUPE_DAYS per student, and NOTHING is sent between 00:00 and 06:59 IST -
enforced twice: the tick loop skips those hours and every send refuses if the clock
is inside the window. Retune without a rebuild via PUSH_CAPS="mood=1,reminder=2".
Mentor sends (announcements, material, tests, mentor notes) are never gated.
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import push as push_service
from db import DASHBOARD_STUDENTS, PUSH_JOBS, STUDENT_ACCOUNTS, get_db

logger = logging.getLogger("push.behavior")

IST = timezone(timedelta(hours=5, minutes=30))

_TEMPLATES_PATH = Path(__file__).with_name("notification_templates.json")
def load_templates(path: Path = _TEMPLATES_PATH) -> list[dict]:
    """Missing/invalid assets disable template pushes, never fabricate content."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        required = {"id", "kind", "category", "class", "title", "body", "link", "weekday", "subject"}
        if not isinstance(rows, list) or any(not isinstance(t, dict) or not required <= t.keys()
            or not isinstance(t["id"], int) or any(not isinstance(t[k], str) for k in ["kind", "category", "class", "title", "body", "link"]) for t in rows):
            raise ValueError("Invalid template schema")
        if len({t["id"] for t in rows}) != len(rows):
            raise ValueError("Duplicate template IDs")
        return rows
    except (OSError, ValueError, TypeError):
        logger.error("Notification template asset unavailable; template pushes disabled")
        return []

TEMPLATES: list[dict] = load_templates()

BY_KIND: dict[str, list[dict]] = {}
BY_CATEGORY: dict[str, list[dict]] = {}
for _t in TEMPLATES:
    BY_KIND.setdefault(_t["kind"], []).append(_t)
    BY_CATEGORY.setdefault(_t["category"], []).append(_t)

PUSH_LOG = "push_log"
DEDUPE_DAYS = 14
# Per-class daily caps, and the owner's rule of thumb made explicit: a student's day
# is at most 3 tracker reminders + 2 sheet-behaviour pushes. `PUSH_CAPS="mood=1,reminder=2"`
# retunes any of them from Cloud Run env, no rebuild.
CAPS_DEFAULT = {"mood": 2, "status": 1, "celebration": 1, "reminder": 3}


def _caps() -> dict:
    caps = dict(CAPS_DEFAULT)
    for part in (os.environ.get("PUSH_CAPS", "") or "").replace(";", ",").split(","):
        key, _, value = part.partition("=")
        try:
            if key.strip() and value.strip():
                caps[key.strip().lower()] = max(0, int(value))
        except ValueError:
            continue
    return caps


CAPS = CAPS_DEFAULT

EVENING_POOLS = {
    "studied": ["Daily Hustlers", "Motivation & Emotional", "New Additions"],
    "not_studied": ["Savage & TP", "Zomato-Style", "Short Push Notifications", "New Additions"],
}

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------- helpers

def _now_ist() -> datetime:
    return datetime.now(IST)


def _today() -> date:
    return _now_ist().date()


def _day_of(now: datetime | None) -> date:
    """The day a scheduled job must use for EVERYTHING: claim key, content date and
    the per-student cap lookups.

    Jobs receive `now` from the scheduler tick, and one tick can run for several
    minutes (a push per student). Reading the wall clock again mid-job used to let a
    tick that started at 23:59 claim keys for the NEXT day - which fired the whole
    day's reminders at midnight and then skipped them all day. Never read the clock
    twice for one decision.
    """
    return (now or _now_ist()).date()


async def _claim(job_key: str) -> bool:
    """Once-per-key claim living in PUSH_JOBS (same pattern as push_scheduler)."""
    db = get_db()
    try:
        await db[PUSH_JOBS].insert_one({"_id": job_key, "at": _now_ist().isoformat()})
        return True
    except Exception:
        return False


def template_by_id(tid: int) -> dict | None:
    return next((t for t in TEMPLATES if t["id"] == tid), None)


def weekly_review_template() -> dict | None:
    return (BY_KIND.get("weekly_review") or [None])[0]


def streak_risk_template() -> dict | None:
    return (BY_KIND.get("streak_risk") or [None])[0]


async def _recent_template_ids(db, sid: str, days: int = DEDUPE_DAYS) -> set[int]:
    since = (_now_ist() - timedelta(days=days)).isoformat()
    rows = await db[PUSH_LOG].find(
        {"studentId": sid, "ts": {"$gte": since}}, {"_id": 0, "templateId": 1}
    ).to_list(200)
    return {int(r.get("templateId") or 0) for r in rows}


async def _sent_today(db, sid: str, cls: str, today: date | None = None) -> int:
    today = (today or _today()).isoformat()
    return await db[PUSH_LOG].count_documents({"studentId": sid, "date": today, "class": cls})


async def _can_push(db, sid: str, cls: str, today: date | None = None) -> bool:
    """Per-student, per-class, per-day cap. Every scheduled push goes through here,
    including the 07:00 streak job, so a rule cannot smuggle a 4th reminder in."""
    return (await _sent_today(db, sid, cls, today)) < _caps().get(cls, 1)


async def remindable(db, sid: str, now: datetime, today: date) -> bool:
    """One call that answers both questions a scheduled sender may ask: is this student
    still under their daily cap for this class, and is it a legal hour?"""
    if push_service.quiet_block_reason(at=now):
        return False
    return await _can_push(db, sid, "reminder", today)


async def log_send(db, sid: str, tmpl: dict, rule: str, cls: str, today: date) -> None:
    """Record a send that went out through a path other than _deliver, so the caps above
    and the mentor's "what did we notify them about" view stay truthful."""
    await db[PUSH_LOG].insert_one({
        "studentId": sid,
        "templateId": tmpl["id"],
        "class": cls,
        "rule": rule,
        "date": today.isoformat(),
        "ts": _now_ist().isoformat(),
    })


async def _deliver(
    db, sid: str, tmpl: dict, rule: str, cls: str | None = None, today: date | None = None
) -> bool:
    # Last gate, right before the network call: a job that runs long enough to walk
    # into the quiet window stops there instead of continuing to send at midnight.
    held = push_service.quiet_block_reason()
    if held:
        logger.info("behavior push held for %s (%s): %s", sid, rule, held)
        return False
    sent = await push_service.push_to_student(
        sid, tmpl["title"], tmpl["body"], link=tmpl.get("link") or "home", tag=f"nudge-{rule}"
    )
    if sent:
        await db[PUSH_LOG].insert_one({
            "studentId": sid,
            "templateId": tmpl["id"],
            "class": cls or tmpl["class"],
            "rule": rule,
            "date": (today or _today()).isoformat(),
            "ts": _now_ist().isoformat(),
        })
    return bool(sent)


def _pick(templates: list[dict], exclude: set[int]) -> dict | None:
    fresh = [t for t in templates if t["id"] not in exclude]
    return random.choice(fresh or templates or []) if (fresh or templates) else None


async def _logged_days(db, sids: list[str], days: int, today: date | None = None) -> dict[str, set[str]]:
    """studentId -> set of ISO dates they have a studyLog row for (last N days)."""
    from routers.student_dashboard import _parse_tracker_day  # late: avoids import cycle

    cutoff = (today or _today()) - timedelta(days=days)
    out: dict[str, set[str]] = {}
    async for doc in db[DASHBOARD_STUDENTS].find(
        {"studentId": {"$in": sids}}, {"_id": 0, "studentId": 1, "studyLog": 1}
    ):
        sid = str(doc.get("studentId") or "").strip().upper()
        days_logged: set[str] = set()
        for row in doc.get("studyLog") or []:
            if not isinstance(row, dict):
                continue
            day = _parse_tracker_day(row.get("date") or "")
            if day and day >= cutoff:
                days_logged.add(day.isoformat())
        out[sid] = days_logged
    return out


async def _tracker_starts(db, sids: list[str]) -> dict:
    """sid -> first tracked day (per-student tracker start), or None if unknown.

    Tracker reminders must respect the same start rule as the mentor grid:
    join day is never tracked (starts the day after), batch-start floor for
    early joiners, mentor overrides win. Students not yet started are skipped.
    """
    from routers.student_dashboard import _effective_tracker_start, _tracker_start_config

    cfg = await _tracker_start_config(db)
    out: dict = {}
    async for acc in db[STUDENT_ACCOUNTS].find(
        {"studentId": {"$in": sorted(set(sids))}},
        {"_id": 0, "studentId": 1, "joinedOn": 1, "batch": 1},
    ):
        sid = str(acc.get("studentId") or "").strip().upper()
        start, _source = _effective_tracker_start(acc, cfg)
        out[sid] = start
    return out


async def _task_counts(db, sid: str, for_day: date) -> tuple[int, int]:
    """(due, done) mentor-target task counts for one student on one day."""
    from routers.daily_targets import _best_targets, _student_id

    student = await db[STUDENT_ACCOUNTS].find_one(
        {"studentId": _student_id(sid)},
        {"_id": 0, "studentId": 1, "group": 1, "attempt": 1, "batch": 1},
    )
    if not student:
        return (0, 0)
    window_start = (for_day - timedelta(days=2)).isoformat()
    rows = await db["daily_targets"].find(
        {"active": {"$ne": False}, "endDate": {"$gte": window_start}}, {"_id": 0}
    ).to_list(300)
    chosen = _best_targets(student, rows, for_day)
    due = sum(len(t.get("tasks") or []) for t in chosen)
    done = await db["daily_target_done"].count_documents(
        {"studentId": _student_id(sid), "date": for_day.isoformat()}
    )
    return (due, min(done, due) if due else 0)


# ---------------------------------------------------------------- scheduled jobs

async def job_weekday_rotation(now: datetime) -> None:
    """09:00 IST — one weekday template (Mon..Sun) to every registered student."""
    if now.hour < 9:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"weekday-{today.isoformat()}"):
        return
    weekday = today.weekday()
    tmpl = next((t for t in BY_KIND.get("weekday", []) if t.get("weekday") == weekday), None)
    if not tmpl:
        return
    db = get_db()
    sent = 0
    for sid in await push_service.students_with_devices():
        if not await _can_push(db, sid, "mood", today):
            continue
        if await _deliver(db, sid, tmpl, f"weekday-{WEEKDAY_NAMES[weekday]}", today=today):
            sent += 1
    logger.info("weekday rotation (%s): %s delivered", WEEKDAY_NAMES[weekday], sent)


async def job_inactive_comeback(now: datetime) -> None:
    """11:00 IST — students with 2+ days of no study log get the comeback push."""
    if now.hour < 11:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"inactive-{today.isoformat()}"):
        return
    tmpl = (BY_KIND.get("inactive") or [None])[0]
    if not tmpl:
        return
    db = get_db()
    sids = await push_service.students_with_devices()
    if not sids:
        return
    logged = await _logged_days(db, sids, days=3)
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    sent = 0
    for sid in sids:
        days_logged = logged.get(sid, set())
        gap = yesterday.isoformat() not in days_logged and day_before.isoformat() not in days_logged
        if not gap:
            continue
        if not await _can_push(db, sid, "status", today):
            continue
        if await _deliver(db, sid, tmpl, "inactive", today=today):
            sent += 1
    logger.info("inactive comeback: %s delivered", sent)


async def job_target_overdue(now: datetime) -> None:
    """17:00 IST — yesterday's mentor targets still incomplete."""
    if now.hour < 17:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"overdue-{today.isoformat()}"):
        return
    tmpl = (BY_KIND.get("target_overdue") or [None])[0]
    if not tmpl:
        return
    db = get_db()
    yesterday = today - timedelta(days=1)
    sent = 0
    for sid in await push_service.students_with_devices():
        due, done = await _task_counts(db, sid, yesterday)
        if due == 0 or done >= due:
            continue
        if not await _can_push(db, sid, "status", today):
            continue
        if await _deliver(db, sid, tmpl, "target_overdue", today=today):
            sent += 1
    logger.info("target overdue: %s delivered", sent)


async def job_evening_nudge(now: datetime) -> None:
    """18:00 IST — the Zomato-style rotation push, profile-based."""
    if now.hour < 18:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"evening-{today.isoformat()}"):
        return
    db = get_db()
    sids = await push_service.students_with_devices()
    if not sids:
        return
    logged = await _logged_days(db, sids, days=1, today=today)
    today_iso = today.isoformat()
    sent = 0
    for sid in sids:
        if not await _can_push(db, sid, "mood", today):
            continue
        studied = today_iso in logged.get(sid, set())
        if studied:
            # 16-Oct complaint: "jo log tracker submit kar rahe hai unhe bhi ja rahi hai".
            # A student who already logged today AND has no target left open has done
            # everything the day asked - a "go study" nudge reads as a glitch, not care.
            due, done = await _task_counts(db, sid, today)
            if not due or done >= due:
                continue
        pool: list[dict] = []
        for cat in EVENING_POOLS["studied" if studied else "not_studied"]:
            pool.extend(BY_CATEGORY.get(cat, []))
        exclude = await _recent_template_ids(db, sid)
        tmpl = _pick(pool, exclude)
        if not tmpl:
            continue
        if await _deliver(db, sid, tmpl, "evening-studied" if studied else "evening-idle", today=today):
            sent += 1
    logger.info("evening nudge: %s delivered", sent)


async def job_test_eve(now: datetime) -> None:
    """18:00 IST — a test/exam is scheduled tomorrow: nudge its audience."""
    if now.hour < 18:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"test-eve-{today.isoformat()}"):
        return
    tmpl = (BY_KIND.get("test_upcoming") or [None])[0]
    if not tmpl:
        return
    db = get_db()
    tomorrow = (today + timedelta(days=1)).isoformat()
    tests = await db["mentor_tests"].find(
        {"test_date": tomorrow}, {"_id": 0}
    ).to_list(50)
    if not tests:
        return
    sids = await push_service.students_with_devices()
    accounts = {}
    async for acc in db[STUDENT_ACCOUNTS].find(
        {"studentId": {"$in": sids}}, {"_id": 0}
    ):
        accounts[str(acc.get("studentId") or "").strip().upper()] = acc
    sent = 0
    for sid in sids:
        acc = accounts.get(sid)
        if not acc:
            continue
        if not any(push_service.matches_audience(t, acc) for t in tests):
            continue
        if not await _can_push(db, sid, "status", today):
            continue
        if await _deliver(db, sid, tmpl, "test_upcoming", today=today):
            sent += 1
    logger.info("test eve: %s delivered for %s test(s)", sent, len(tests))


async def job_evening_status(now: datetime) -> None:
    """20:30 IST — one status push: pending targets first, else a zero-study day."""
    if now.hour < 20 or (now.hour == 20 and now.minute < 30):
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"evening-status-{today.isoformat()}"):
        return
    db = get_db()
    sids = await push_service.students_with_devices()
    if not sids:
        return
    logged = await _logged_days(db, sids, days=1, today=today)
    today_iso = today.isoformat()
    pending_tmpl = (BY_KIND.get("target_pending") or [None])[0]
    zero_tmpl = (BY_KIND.get("no_study_today") or [None])[0]
    sent = 0
    for sid in sids:
        if not await _can_push(db, sid, "status", today):
            continue
        due, done = await _task_counts(db, sid, today)
        studied = today_iso in logged.get(sid, set())
        tmpl = None
        rule = ""
        if due and done < due and pending_tmpl:
            tmpl, rule = pending_tmpl, "target_pending"
        elif not studied and not due and zero_tmpl:
            tmpl, rule = zero_tmpl, "no_study_today"
        if tmpl and await _deliver(db, sid, tmpl, rule, today=today):
            sent += 1
    logger.info("evening status: %s delivered", sent)


async def job_tracker_night(now: datetime) -> None:
    """23:00 IST — the day is ending and TODAY's tracker was never filled."""
    if now.hour < 23:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"tracker-night-{today.isoformat()}"):
        return
    tmpl = (BY_KIND.get("tracker_missing") or [None])[0]
    if not tmpl:
        return
    db = get_db()
    sids = await push_service.students_with_devices()
    if not sids:
        return
    logged = await _logged_days(db, sids, days=1, today=today)
    starts = await _tracker_starts(db, sids)
    # On-leave / self-reported-absent students are NOT missing anything: never
    # nag them at 23:00 (owner decision 14-Oct-2026).
    from routers import attendance as attendance_lib  # late: avoids import cycle

    excused = await attendance_lib.excused_students(db, today)
    today_iso = today.isoformat()
    sent = 0
    for sid in sids:
        if sid not in logged or today_iso in logged[sid]:
            continue  # already filled today (or no study log doc to judge)
        if sid in excused:
            continue
        start = starts.get(sid)
        if start and start > today:
            continue  # their tracker has not started yet (join-day skip)
        if not await _can_push(db, sid, "reminder", today):
            continue
        if await _deliver(db, sid, tmpl, "tracker_night", cls="reminder", today=today):
            sent += 1
    logger.info("tracker night (today): %s delivered", sent)


async def job_tracker_final(now: datetime) -> None:
    """14:00 IST — final reminder: YESTERDAY's tracker still not filled."""
    if now.hour < 14:
        return
    if not push_service.configured():
        return
    today = _day_of(now)  # the tick's own clock, never the wall clock mid-run
    if not await _claim(f"tracker-final-{today.isoformat()}"):
        return
    tmpl = {
        "id": -1001,
        "title": "⏰ Final reminder — yesterday's tracker",
        "body": ("Yesterday's study log is still missing. Fill it now so your "
                 "streak and progress stay accurate."),
        "link": "tracker",
    }
    db = get_db()
    sids = await push_service.students_with_devices()
    if not sids:
        return
    logged = await _logged_days(db, sids, days=2, today=today)
    starts = await _tracker_starts(db, sids)
    yesterday_day = today - timedelta(days=1)
    from routers import attendance as attendance_lib  # late: avoids import cycle

    excused = await attendance_lib.excused_students(db, yesterday_day)
    yesterday = yesterday_day.isoformat()
    sent = 0
    for sid in sids:
        if sid not in logged or yesterday in logged[sid]:
            continue  # yesterday already filled (or no study log doc to judge)
        if sid in excused:
            continue
        start = starts.get(sid)
        if start and start > yesterday_day:
            continue  # yesterday was before their tracker start
        if not await _can_push(db, sid, "reminder", today):
            continue
        if await _deliver(db, sid, tmpl, "tracker_final", cls="reminder", today=today):
            sent += 1
    logger.info("tracker final (yesterday): %s delivered", sent)


# ---------------------------------------------------------------- events

async def on_target_completed(sid: str) -> None:
    """Called after POST /api/targets/complete. Celebrates when the day is done."""
    try:
        if not push_service.configured():
            return
        db = get_db()
        due, done = await _task_counts(db, sid, _today())
        if due == 0 or done < due:
            return
        if not await _can_push(db, sid, "celebration"):
            return
        # A heavy day (3+ tasks) earns the "boss level cleared" copy.
        kind = "difficult_chapter" if due >= 3 and random.random() < 0.5 else "target_completed"
        pool = BY_KIND.get(kind) or BY_KIND.get("target_completed") or []
        exclude = await _recent_template_ids(db, sid)
        tmpl = _pick(pool, exclude)
        if tmpl:
            await _deliver(db, sid, tmpl, "target_completed")
    except Exception as exc:
        logger.warning("on_target_completed failed: %s", exc)


# ---------------------------------------------------------------- registration

BEHAVIOR_JOBS = (
    job_weekday_rotation,
    job_inactive_comeback,
    job_target_overdue,
    job_evening_nudge,
    job_test_eve,
    job_evening_status,
    job_tracker_night,
    job_tracker_final,
)
