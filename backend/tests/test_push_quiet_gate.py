"""The two things the 16-Oct complaint ("notifications sab galat ja rahe hai") came down to.

1. A job that is still working when the clock crosses midnight used to keep sending into
   the 00:00 hour even after the tick loop learned to skip quiet hours - the send itself
   was never guarded. `_deliver` now refuses, so the worst case is a job that does nothing.
2. The 18:00 rotation went to *every* registered device, so a student who had already
   submitted today's tracker and closed every target still got "go study" copy. Done-day
   students are skipped now; the reminders that track a real gap (14:00/23:00) are not.
"""
import asyncio
import datetime as dt
from datetime import date, datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 10, 16)
EVENING = datetime(2026, 10, 16, 18, 0, 30, tzinfo=IST)
STREAK_AT = datetime(2026, 10, 16, 7, 0, 5, tzinfo=IST)
YESTERDAY = date(2026, 10, 15)

import behavior_push as bp  # noqa: E402
import push as push_service  # noqa: E402
import push_scheduler as ps  # noqa: E402
from db import get_db  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sends(monkeypatch):
    got: list = []

    async def fake_push(student_id, title, body, link="home", tag=""):
        got.append({"studentId": student_id, "title": title, "tag": tag})
        return 1

    monkeypatch.setattr(push_service, "push_to_student", fake_push)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    return got


def _at(hour: int, minute: int = 30):
    return dt.datetime(2026, 10, 17, hour, minute, tzinfo=IST)


# ------------------------------------------------------------------ quiet gate


def test_quiet_window_is_the_shared_number_between_scheduler_and_send():
    assert tuple(ps.QUIET_HOURS_IST) == tuple(push_service.QUIET_HOURS_IST)
    assert list(push_service.QUIET_HOURS_IST) == [0, 1, 2, 3, 4, 5, 6]


def test_block_reason_uses_the_real_clock(monkeypatch):
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(0))}))
    assert push_service.quiet_block_reason() == "quiet hours (00:00-06:59 IST)"
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(7, 0))}))
    assert push_service.quiet_block_reason() == ""


def test_mentor_escape_hatch_is_honoured(monkeypatch):
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(2))}))
    monkeypatch.setenv("PUSH_ALLOW_QUIET", "1")
    assert push_service.quiet_block_reason() == ""
    monkeypatch.setenv("PUSH_ALLOW_QUIET", "0")
    assert push_service.quiet_block_reason() != ""


def test_deliver_refuses_once_the_clock_is_quiet(monkeypatch, sends):
    """The midnight-storm replay: the job was handed 23:59, the clock says 00:05 by now."""
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(0, 5))}))
    tmpl = {"id": 1, "title": "t", "body": "b", "link": "home", "class": "mood"}

    async def go():
        return await bp._deliver(get_db(), "UMP0001", tmpl, "weekday-monday", today=TODAY)

    assert _run(go()) is False
    assert sends == []          # nothing reached a device
    assert _run(get_db()["push_log"].count_documents({})) == 0  # and nothing was claimed as sent


def test_deliver_sends_outside_quiet_hours(monkeypatch, sends):
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(9, 15))}))
    tmpl = {"id": 2, "title": "t", "body": "b", "link": "home", "class": "mood"}

    async def go():
        return await bp._deliver(get_db(), "UMP0002", tmpl, "weekday-tuesday", today=TODAY)

    assert _run(go()) is True
    assert [s["studentId"] for s in sends] == ["UMP0002"]
    row = _run(get_db()["push_log"].find_one({"studentId": "UMP0002"}))
    assert row and row["date"] == TODAY.isoformat()


def test_weekly_broadcast_holds_itself_but_announcements_do_not(monkeypatch):
    """The streak/weekly paths call push_to_students directly - the broadcast helper is
    the one that opts into holding. A mentor's announcement must never be swallowed."""
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: _at(3, 0))}))
    calls: list = []

    async def fake_students(ids, title, body, link="", tag="", throttle_s=0.0):
        calls.append(tag)
        return len(list(ids))

    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "push_to_students", fake_students)

    async def registered():
        return ["UMP0001"]

    monkeypatch.setattr(push_service, "students_with_devices", registered)
    held = _run(push_service.push_to_all("a", "b", tag="weekly-x", hold_quiet=True))
    sent = _run(push_service.push_to_all("a", "b", tag="ann-1"))
    assert held == 0 and calls == ["ann-1"] and sent == 1


# ------------------------------------------------------- done-day students


def _seed_evening(monkeypatch, studied: set):
    async def devices():
        return ["UMP0001", "UMP0002"]

    async def logged(db, sids, days, today=None):
        return {sid: ({TODAY.isoformat()} if sid in studied else set()) for sid in sids}

    monkeypatch.setattr(push_service, "students_with_devices", devices)
    monkeypatch.setattr(bp, "_logged_days", logged)
    monkeypatch.setattr(bp, "_recent_template_ids", lambda db, sid, days=14: asyncio.sleep(0, result=set()))
    monkeypatch.setattr(bp, "_today", lambda: TODAY)
    monkeypatch.setattr(bp, "_now_ist", lambda: EVENING)
    # The delivery gate uses a separate real-clock reader. Freeze it too;
    # otherwise this evening fixture depends on when CI happens to execute.
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: EVENING)}))


def test_evening_nudge_skips_a_student_whose_day_is_done(monkeypatch, sends):
    """0001 logged the tracker and closed both targets; 0002 logged but still owes one."""
    _seed_evening(monkeypatch, studied={"UMP0001", "UMP0002"})

    async def counts(db, sid, for_day):
        assert for_day == TODAY
        return (2, 2) if sid == "UMP0001" else (2, 1)

    monkeypatch.setattr(bp, "_task_counts", counts)
    _run(bp.job_evening_nudge(EVENING))
    assert [s["studentId"] for s in sends] == ["UMP0002"]
    assert sends[0]["tag"].startswith("nudge-evening-studied")


def test_evening_nudge_still_warms_up_a_zero_day(monkeypatch, sends):
    _seed_evening(monkeypatch, studied=set())

    async def counts(db, sid, for_day):
        return (0, 0)

    monkeypatch.setattr(bp, "_task_counts", counts)
    _run(bp.job_evening_nudge(EVENING))
    assert sorted(s["studentId"] for s in sends) == ["UMP0001", "UMP0002"]
    assert all(s["tag"].endswith("evening-idle") for s in sends)


# --------------------------------------------------- tracker cap: 3 a day, all counted


def _seed_streak(monkeypatch, logged_ids):
    """Two registered students, one of them already filled yesterday's tracker."""
    async def devices():
        return ["UMP0001", "UMP0002"]

    async def starts(db, sids):
        return {sid: None for sid in sids}

    async def excused(db, day):
        return set()

    monkeypatch.setattr(push_service, "students_with_devices", devices)
    monkeypatch.setattr(ps.behavior_push, "_tracker_starts", starts)
    monkeypatch.setattr(ps, "_now_ist", lambda: STREAK_AT)
    monkeypatch.setattr("routers.attendance.excused_students", excused)
    # both students need a dashboard doc (a device with no studyLog is skipped by design:
    # without a log we cannot prove the day is missing) - one of them holds yesterday.
    rows = [{"studentId": sid,
             "studyLog": [{"date": (YESTERDAY if sid in logged_ids else date(2026, 10, 12)).isoformat(),
                           "hours": 4, "topic": "SFM"}]}
            for sid in ("UMP0001", "UMP0002")]
    _run(get_db()["dashboard_students"].insert_many(rows))


def test_streak_job_does_not_nag_someone_who_filled_it_last_night(monkeypatch, sends):
    """23:05 submission -> the 07:00 "yesterday is missing" push must not exist."""
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    _seed_streak(monkeypatch, logged_ids=["UMP0001"])

    _run(ps._job_streak_reminder(STREAK_AT))
    assert [s["studentId"] for s in sends] == ["UMP0002"]
    row = _run(get_db()["push_log"].find_one({"studentId": "UMP0002"}))
    assert row and row["class"] == "reminder" and row["date"] == TODAY.isoformat()
    assert row["rule"] == "streak_yesterday"


def test_streak_job_respects_the_three_reminder_cap(monkeypatch, sends):
    """The cap used to be invisible to this job - it called push_to_students directly."""
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    _seed_streak(monkeypatch, logged_ids=[])
    _run(get_db()["push_log"].insert_many([
        {"studentId": "UMP0002", "templateId": 1, "class": "reminder", "rule": "tracker_night", "date": TODAY.isoformat()},
        {"studentId": "UMP0002", "templateId": 2, "class": "reminder", "rule": "tracker_final", "date": TODAY.isoformat()},
        {"studentId": "UMP0002", "templateId": 3, "class": "reminder", "rule": "evening", "date": TODAY.isoformat()},
    ]))

    _run(ps._job_streak_reminder(STREAK_AT))
    assert [x["studentId"] for x in sends] == ["UMP0001"]   # the uncapped student still gets it
    db = get_db()
    # UMP0002 stays at exactly 3 reminders - the 4th was refused and never logged;
    # UMP0001's 07:00 send is logged, which is what makes the cap visible to this job.
    assert _run(db["push_log"].count_documents({"studentId": "UMP0002"})) == 3
    assert _run(db["push_log"].count_documents({"studentId": "UMP0001", "rule": "streak_yesterday"})) == 1


def test_streak_job_is_silent_during_the_quiet_window(monkeypatch, sends):
    """A cold start at 00:20 must not use the 07:00 job's "run once the hour came" floor."""
    monkeypatch.delenv("PUSH_ALLOW_QUIET", raising=False)
    _seed_streak(monkeypatch, logged_ids=[])
    monkeypatch.setattr(ps, "_now_ist", lambda: datetime(2026, 10, 16, 0, 20, tzinfo=IST))

    _run(ps._job_streak_reminder(datetime(2026, 10, 16, 0, 20, tzinfo=IST)))
    assert sends == []
    assert _run(get_db()["push_log"].count_documents({})) == 0


def test_caps_are_env_tunable(monkeypatch):
    monkeypatch.setenv("PUSH_CAPS", "mood=1;reminder=2,status=0")
    assert bp._caps() == {"mood": 1, "status": 0, "celebration": 1, "reminder": 2}
    assert bp.CAPS == bp.CAPS_DEFAULT  # the documented default never mutates
    monkeypatch.delenv("PUSH_CAPS")
    assert bp._caps() == bp.CAPS_DEFAULT
