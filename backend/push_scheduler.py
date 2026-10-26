"""Best-effort push scheduler living inside the API process.

Cloud Run scales to zero when idle, so a classic cron is not available.
Instead every tick (and shortly after each cold start) checks for jobs whose
IST window has already passed TODAY and has not run yet — a Mongo `push_jobs`
guard document makes each job fire exactly once per day/week even across
restarts and multiple instances. If the instance was asleep at 07:00, the job
runs late on the first morning traffic instead of being skipped.

Jobs (IST):
  07:00 every day    streak reminder  — registered students missing yesterday's
                                        study log (capped: it is one of the 3 tracker
                                        reminders a student may get in a day)
  08:00 every day    rank refresh     — force-rebuild the leaderboard; the
                                        rebuild itself fires "you were
                                        overtaken" pushes for rank drops
  19:00 every Sunday weekly report    — the finished Sun..Sat week, sent the day after it closes
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from db import DASHBOARD_STUDENTS, DEVICE_TOKENS, PUSH_JOBS, get_db
import push as push_service
import behavior_push
from week_window import week_start

logger = logging.getLogger("push.scheduler")
IST = ZoneInfo("Asia/Kolkata")
TICK_SECONDS = 60
STARTUP_DELAY_SECONDS = 15

# Nothing may fire between midnight and 07:00 IST. Every job guards with an hour
# FLOOR ("run once the hour has come"), so a tick that is still running when the
# clock crosses midnight used to pass every guard while minting claim keys for the
# NEXT day - one such night sent 440 pushes to 98 students in nine minutes and then
# skipped the entire real schedule. A tick that straddles midnight must do nothing.
# The window itself lives in push.py (QUIET_HOURS_IST) so the send path and the
# job loop can never disagree about when a student may be woken.
QUIET_HOURS_IST = push_service.QUIET_HOURS_IST


def hold_quiet(now: datetime | None = None) -> str:
    """Why scheduled sending must stop right now, "" when it may go ahead.

    Takes the tick's own reading so a long-running tick is judged on the clock it
    was handed, and a test can drive one clock instead of two."""
    return push_service.quiet_block_reason(QUIET_HOURS_IST, at=now or _now_ist())


def _weekly_report_held() -> bool:
    """WEEKLY_REPORT_HOLD=1 keeps the Sunday weekly report back.

    Owner decision 2026-10-18: "push mai bolu tabhi karna" - that broadcast goes out
    only on his word. The hold is checked BEFORE the daily claim, so clearing the env
    later the same evening still releases the report instead of losing a whole week.
    """
    return (os.environ.get("WEEKLY_REPORT_HOLD", "") or "").strip().lower() in ("1", "true", "yes", "on")


def disabled() -> bool:
    """PUSH_SCHEDULER=0 stops every scheduled push without a rebuild."""
    return (os.environ.get("PUSH_SCHEDULER", "1") or "1").strip().lower() in ("0", "false", "no", "off")

_task: Optional[asyncio.Task] = None


def _now_ist() -> datetime:
    return datetime.now(IST)


async def _claim(job_key: str) -> bool:
    """True for the single caller allowed to run this job (find-then-insert;
    the rare double-fire race is acceptable for best-effort pushes)."""
    try:
        db = get_db()
        existing = await db[PUSH_JOBS].find_one({"_id": job_key})
        if existing:
            return False
        await db[PUSH_JOBS].insert_one(
            {"_id": job_key, "claimedAt": datetime.now(IST).isoformat()}
        )
        return True
    except Exception as exc:
        logger.warning("claim %s failed: %s", job_key, exc)
        return False


async def _job_streak_reminder(now: datetime) -> None:
    today = now.date()
    if now.hour < 7:  # never before 07:00 IST, even on cold-start catch-up
        return
    if not push_service.configured():
        return
    if not await _claim(f"streak-{today.isoformat()}"):
        return
    from routers.student_dashboard import _parse_tracker_day

    db = get_db()
    registered = set(await push_service.students_with_devices())
    if not registered:
        logger.info("streak reminder: no registered devices yet")
        return
    yesterday = today - timedelta(days=1)
    starts = await behavior_push._tracker_starts(db, sorted(registered))
    targets: list[str] = []
    async for doc in db[DASHBOARD_STUDENTS].find(
        {"studentId": {"$in": sorted(registered)}}, {"studentId": 1, "studyLog": 1}
    ):
        sid = str(doc.get("studentId") or "").strip().upper()
        if sid not in registered:
            continue
        start = starts.get(sid)
        if start and start > yesterday:
            continue  # yesterday was before their tracker start (join-day skip)
        logged = False
        for row in doc.get("studyLog") or []:
            if not isinstance(row, dict):
                continue
            day = _parse_tracker_day(row.get("date") or "")
            if day == yesterday:
                logged = True
                break
        if not logged:
            targets.append(sid)
    # On-leave / self-reported-absent students were not missing anything yesterday.
    from routers import attendance as attendance_lib  # late: avoids import cycle

    excused = await attendance_lib.excused_students(db, yesterday)
    if excused:
        targets = [sid for sid in targets if sid not in excused]
    # Students with a device but no dashboard doc are skipped on purpose:
    # without a studyLog we cannot prove yesterday is missing.
    # 7:00 IST = the "yesterday's tracker" touch of the 3-step tracker reminder
    # flow (23:00 today / 07:00 yesterday / 14:00 yesterday-final). Copy must
    # reference YESTERDAY (owner decision 2026-10-13).
    #
    # This used to be one unguarded blast to `push_to_students`: no cap, no push_log,
    # so the "max 3 reminders a day" rule (owner, 16-Oct) silently excluded it and a
    # student who filled the log at 23:05 could still collect 07:00 + 14:00 anyway.
    # Each send is now checked against the cap and written to push_log like the others.
    tmpl = {
        "id": -1000,
        "title": "🔥 Yesterday's study log is missing",
        "body": "Add it now and keep your streak alive.",
        "link": "tracker",
    }
    sent = 0
    for sid in targets:
        if not await behavior_push.remindable(db, sid, now, today):
            continue
        if not await push_service.push_to_student(
            sid, tmpl["title"], tmpl["body"], link=tmpl["link"], tag=f"streak-{today.isoformat()}"
        ):
            continue
        await behavior_push.log_send(db, sid, tmpl, "streak_yesterday", "reminder", today)
        sent += 1
    logger.info("streak reminder: %s targeted, %s delivered", len(targets), sent)


async def _job_rank_refresh(now: datetime) -> None:
    today = now.date()
    if now.hour < 8:
        return
    if not await _claim(f"rankcheck-{today.isoformat()}"):
        return
    try:
        from routers.student_dashboard import _leaderboard_snapshot

        db = get_db()
        await _leaderboard_snapshot(db, force=True)
        logger.info("rank refresh done (rank-drop pushes fired from rebuild)")
    except Exception as exc:
        logger.warning("rank refresh failed: %s", exc)


async def _job_weekly_report(now: datetime) -> None:
    """Weekly report: sent on **Sunday**, about the week that closed Saturday night.

    Owner decision 2026-10-18. The week runs Sun..Sat (week_window) and the report must
    go out only once that week is finished, so the students who fill "yesterday's"
    tracker on Sunday morning still land inside the week being reported. This is also a
    standing rule for deploys: the job fires on the first tick after 19:00 IST on a
    Sunday, so shipping this on a Sunday evening sends it immediately - deploy it any
    other day, or hold it until the owner says go.
    """
    today = now.date()
    if today.weekday() != 6:  # Sunday - the day after the Sun..Sat week closes
        return
    if now.hour < 19:  # not before 19:00 IST
        return
    if not push_service.configured():
        return
    if _weekly_report_held():
        logger.info("weekly report HELD by WEEKLY_REPORT_HOLD - nothing sent for %s", today.isoformat())
        return
    if not await _claim(f"weekly-report-{today.isoformat()}"):
        return
    reported = week_start(today - timedelta(days=1))   # the Sunday that opened the closed week
    tmpl = behavior_push.weekly_review_template() or {
        "title": "📊 Your weekly report is ready",
        "body": "See your hours, accuracy and rank for last week in the Reports tab.",
    }
    sent = await push_service.push_to_all(
        tmpl["title"],
        tmpl["body"],
        link="reports",
        tag=f"weekly-{reported.isoformat()}",
        hold_quiet=True,
    )
    logger.info(
        "weekly report push (%s..%s): %s delivered",
        reported.isoformat(), (reported + timedelta(days=6)).isoformat(), sent,
    )


_JOBS: tuple[Callable[[datetime], Awaitable[None]], ...] = (
    _job_streak_reminder,
    _job_rank_refresh,
    _job_weekly_report,
    *behavior_push.BEHAVIOR_JOBS,
)


async def _tick() -> None:
    if disabled():
        return
    for job in _JOBS:
        # The clock is read per job on purpose. A tick runs for minutes (one network
        # call per student), so the value handed to the first job is stale by the
        # time the last one starts - and a stale value next to a fresh claim key is
        # exactly how midnight produced a whole day of reminders.
        now = _now_ist()
        if hold_quiet(now):
            return
        try:
            await job(now)
        except Exception as exc:
            logger.warning("push job %s failed: %s", getattr(job, "__name__", job), exc)


async def _run() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            await _tick()
        except Exception as exc:
            logger.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(TICK_SECONDS)


def start() -> None:
    global _task
    if _task is not None:
        return
    if disabled():
        logger.warning("push scheduler DISABLED by PUSH_SCHEDULER=0 - no scheduled pushes will run")
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _task = loop.create_task(_run())
    logger.info(
        "push scheduler started (tracker 23:00/07:00/14:00, rank 08:00, weekday 09:00, comeback 11:00, "
        "overdue 17:00, evening nudge/test 18:00, weekly Sun 19:00, status 20:30 IST)"
    )


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
