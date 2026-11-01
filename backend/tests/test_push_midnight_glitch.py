"""Regression tests for the midnight push storm.

One scheduler tick runs for minutes (a network call per student). It used to read the
clock ONCE for all jobs but mint its claim key from the wall clock per job, so a tick
that started at 23:00 and was still working at 00:05 passed every "hour has come"
guard while writing keys for the NEXT day: the whole day's reminders fired at
midnight (440 pushes to 98 students on 16-Oct-2026) and the real schedule was then
already claimed and silent.

Rules now enforced: a job uses one clock reading for guard, claim key, content date
and caps, and nothing runs between 00:00 and 07:00 IST.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))
DAY1 = date(2026, 10, 15)
DAY2 = date(2026, 10, 16)
TICK_AT = datetime(2026, 10, 15, 23, 59, 50, tzinfo=IST)   # started before midnight
CLOCK_NOW = datetime(2026, 10, 16, 0, 5, 30, tzinfo=IST)   # wall clock crossed midnight

import behavior_push as bp  # noqa: E402
import push as push_service  # noqa: E402
import push_scheduler as ps  # noqa: E402
from db import PUSH_JOBS, get_db  # noqa: E402

PUSH_LOG = "push_log"


@pytest.fixture
def no_sending(monkeypatch):
    sent: list = []

    async def fake_push(student_id, title, body, link="home", tag=""):
        sent.append({"studentId": student_id, "title": title, "tag": tag})
        return 1

    monkeypatch.setattr(push_service, "push_to_student", fake_push)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    return sent


@pytest.fixture
def midnight_clock(monkeypatch):
    """The wall clock says it is already the next day, whatever the job was given."""
    monkeypatch.setattr(bp, "_now_ist", lambda: CLOCK_NOW)
    monkeypatch.setattr(bp, "_today", lambda: DAY2)


def _run(coro):
    return asyncio.run(coro)


def _claim_keys():
    async def go():
        return await get_db()[PUSH_JOBS].find({}, {"_id": 1}).to_list(200)

    return {d["_id"] for d in _run(go())}


def _logged():
    async def go():
        return await get_db()[PUSH_LOG].find({}, {"_id": 0}).to_list(200)

    return _run(go())


def _seed_devices(monkeypatch, sids):
    async def fake():
        return list(sids)

    monkeypatch.setattr(push_service, "students_with_devices", fake)


def test_tick_that_straddles_midnight_claims_nothing_for_the_new_day(midnight_clock, no_sending, monkeypatch):
    """The exact failure: hour guard satisfied by an old reading, key minted from a new one."""
    _run(get_db()[PUSH_JOBS].insert_one({"_id": f"weekday-{DAY1.isoformat()}", "at": TICK_AT.isoformat()}))
    _seed_devices(monkeypatch, ["UMP0001", "UMP0002"])

    _run(bp.job_weekday_rotation(TICK_AT))

    keys = _claim_keys()
    assert f"weekday-{DAY1.isoformat()}" in keys            # the already-claimed slot
    assert f"weekday-{DAY2.isoformat()}" not in keys        # never touched again
    assert no_sending == [] and _logged() == []


def test_a_fresh_morning_tick_still_runs_its_job(no_sending, monkeypatch):
    _seed_devices(monkeypatch, ["UMP0001"])
    now = datetime(2026, 10, 16, 9, 0, 30, tzinfo=IST)
    # This is a fresh-morning fixture, not a stale tick entering quiet hours.
    monkeypatch.setattr(push_service, "datetime", type("DT", (), {"now": staticmethod(lambda tz: now)}))

    async def go():
        await bp.job_weekday_rotation(now)

    _run(go())
    assert f"weekday-{DAY2.isoformat()}" in _claim_keys()
    assert len(no_sending) == 1
    rows = _logged()
    assert rows and rows[0]["date"] == DAY2.isoformat()


def test_caps_are_counted_for_the_job_day_not_the_wall_clock(midnight_clock):
    """A student who already received 3 reminders 'today' by the wall clock was pushed
    yesterday's set: the cap must follow the day the job is about."""
    async def seed():
        await get_db()[PUSH_LOG].insert_many([
            {"studentId": "UMP0001", "templateId": 1, "class": "reminder", "rule": "x", "date": DAY1.isoformat()},
            {"studentId": "UMP0001", "templateId": 2, "class": "reminder", "rule": "x", "date": DAY1.isoformat()},
            {"studentId": "UMP0001", "templateId": 3, "class": "reminder", "rule": "x", "date": DAY1.isoformat()},
        ])

    _run(seed())
    assert _run(bp._sent_today(get_db(), "UMP0001", "reminder", DAY1)) == 3
    assert _run(bp._can_push(get_db(), "UMP0001", "reminder", DAY1)) is False
    # and the day the job is about (its own date) is genuinely empty
    assert _run(bp._can_push(get_db(), "UMP0001", "reminder", DAY2)) is True


def test_day_of_ignores_the_wall_clock(midnight_clock):
    assert bp._day_of(TICK_AT) == DAY1
    assert bp._day_of(None) == DAY2  # event callers may still ask for "now"


def test_quiet_hours_block_every_job(monkeypatch):
    calls = []

    async def spy(now):
        calls.append(now)

    monkeypatch.setattr(ps, "_now_ist", lambda: datetime(2026, 10, 16, 0, 30, tzinfo=IST))
    monkeypatch.setattr(ps, "_JOBS", (spy, spy, spy))
    _run(ps._tick())
    assert calls == []

    monkeypatch.setattr(ps, "_now_ist", lambda: datetime(2026, 10, 16, 7, 0, tzinfo=IST))
    _run(ps._tick())
    assert len(calls) == 3  # 07:00 is the first legal minute


def test_clock_is_reread_for_every_job(monkeypatch):
    """A long job must not hand its stale reading to the next one."""
    seen = []
    times = iter([
        datetime(2026, 10, 15, 23, 59, 55, tzinfo=IST),
        datetime(2026, 10, 16, 0, 0, 20, tzinfo=IST),
    ])
    monkeypatch.setattr(ps, "_now_ist", lambda: next(times))

    async def first(now):
        seen.append(now.hour)

    async def second(now):
        seen.append(now.hour)

    monkeypatch.setattr(ps, "_JOBS", (first, second))
    _run(ps._tick())
    # second job was offered 00:00 -> blocked by quiet hours, and never got 23 again
    assert seen == [23]


def test_kill_switch_stops_the_whole_scheduler(monkeypatch):
    calls = []

    async def spy(now):
        calls.append(now)

    monkeypatch.setenv("PUSH_SCHEDULER", "0")
    monkeypatch.setattr(ps, "_now_ist", lambda: datetime(2026, 10, 16, 9, 0, tzinfo=IST))
    monkeypatch.setattr(ps, "_JOBS", (spy,))
    _run(ps._tick())
    assert calls == []
    assert ps.disabled() is True

    monkeypatch.setenv("PUSH_SCHEDULER", "1")
    assert ps.disabled() is False
    _run(ps._tick())
    assert calls == [datetime(2026, 10, 16, 9, 0, tzinfo=IST)]
