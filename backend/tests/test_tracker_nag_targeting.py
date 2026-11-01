"""Tracker nags must reach ONLY the students who have not filled the day.

Owner question 2026-10-18: "tracker ka jisne submit nahi kiya usse hi ja raha hai na".
These are the four rules that make that true, per touch-point:

  23:00 tracker_night   -> skipped if a studyLog row exists for TODAY
  14:00 tracker_final   -> skipped if a studyLog row exists for YESTERDAY
  both                  -> skipped on leave/absent-excuse, and before their tracker start

The date on the row is what counts, never the time it was written: a 23:05 fill is a
fill, so the next morning's "yesterday is missing" push must not exist (the 16-Oct rule,
already pinned for the 07:00 job in test_push_quiet_gate.py - pinned here for 14:00 too).
"""
import asyncio
import datetime as dt
from datetime import date, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 10, 16)
YESTERDAY = date(2026, 10, 15)
STUDENTS = ("UMP0001", "UMP0002")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sends(monkeypatch):
    import push as push_service

    got: list = []

    # the suite must not depend on the wall clock: 23:00 and 14:00 jobs are tested for
    # their targeting, and quiet hours would block every send if the runner woke up
    # between 00:00 and 07:00 IST
    monkeypatch.setenv("PUSH_ALLOW_QUIET", "1")

    async def fake_push(student_id, title, body, link="home", tag=""):
        got.append({"studentId": student_id, "title": title, "tag": tag})
        return 1

    monkeypatch.setattr(push_service, "push_to_student", fake_push)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    async def devices():
        return list(STUDENTS)

    monkeypatch.setattr(push_service, "students_with_devices", devices)
    return got


def _seed(monkeypatch, *, rows, excused=(), starts=None):
    """Study-log rows per student, plus the two skip lists the jobs consult."""
    import behavior_push as bp
    from db import get_db

    _run(get_db()["dashboard_students"].delete_many({}))
    _run(get_db()["push_jobs"].delete_many({}))
    _run(get_db()["dashboard_students"].insert_many(
        [{"studentId": sid, "studyLog": rows.get(sid, [])} for sid in STUDENTS]
    ))

    # the 23:00 job needs a sheet template; do not depend on the exported JSON here
    monkeypatch.setitem(bp.BY_KIND, "tracker_missing", [{
        "id": -2001, "title": "🌙 Aaj ka tracker baki hai", "body": "Fill it before midnight.",
        "link": "tracker", "class": "reminder",
    }])

    async def no_starts(db, sids):
        return {sid: (starts or {}).get(sid) for sid in sids}

    async def excused_days(db, day):
        return set(excused)

    monkeypatch.setattr(bp, "_tracker_starts", no_starts)
    monkeypatch.setattr("routers.attendance.excused_students", excused_days)


def test_2300_reaches_only_the_student_who_has_not_filled_today(monkeypatch, sends):
    import behavior_push as bp

    _seed(monkeypatch, rows={
        "UMP0001": [{"date": TODAY.isoformat(), "hours": 4, "topic": "SFM"}],   # filled
        "UMP0002": [{"date": "2026-10-14", "hours": 3, "topic": "AFS"}],         # not filled today
    })
    _run(bp.job_tracker_night(dt.datetime(2026, 10, 16, 23, 5, tzinfo=IST)))
    assert [s["studentId"] for s in sends] == ["UMP0002"]
    logged = _run(__import__("db").get_db()["push_log"].find_one({"studentId": "UMP0002"}))
    assert logged["rule"] == "tracker_night" and logged["class"] == "reminder"
    assert _run(__import__("db").get_db()["push_log"].count_documents({"studentId": "UMP0001"})) == 0


def test_2300_is_quiet_for_a_student_on_leave(monkeypatch, sends):
    """A leave day is not a missing day (owner decision 14-Oct)."""
    import behavior_push as bp

    _seed(monkeypatch,
          rows={"UMP0001": [], "UMP0002": []},
          excused=["UMP0002"])
    _run(bp.job_tracker_night(dt.datetime(2026, 10, 16, 23, 5, tzinfo=IST)))
    assert [s["studentId"] for s in sends] == ["UMP0001"]


def test_2300_skips_a_student_whose_tracker_has_not_started(monkeypatch, sends):
    """Join day is never tracked, so nobody is nagged about a day before their start."""
    import behavior_push as bp

    _seed(monkeypatch,
          rows={"UMP0001": [], "UMP0002": []},
          starts={"UMP0002": TODAY + timedelta(days=1)})
    _run(bp.job_tracker_night(dt.datetime(2026, 10, 16, 23, 5, tzinfo=IST)))
    assert [s["studentId"] for s in sends] == ["UMP0001"]


def test_1400_final_skips_a_late_night_fill_of_yesterday(monkeypatch, sends):
    """Yesterday was filled at 23:58 - the 14:00 follow-up must not exist for them.

    The row's DATE decides, and this also proves the cap is not what is saving them:
    UMP0001 gets it, because their yesterday genuinely is empty.
    """
    import behavior_push as bp

    _seed(monkeypatch, rows={
        "UMP0001": [{"date": "2026-10-13", "hours": 2, "topic": "AFS"}],
        "UMP0002": [{"date": YESTERDAY.isoformat(), "hours": 5, "topic": "SFM",
                     "submissionTime": "2026-10-15T23:58:00+05:30"}],
    })
    _run(bp.job_tracker_final(dt.datetime(2026, 10, 16, 14, 5, tzinfo=IST)))
    assert [s["studentId"] for s in sends] == ["UMP0001"]
    logged = _run(__import__("db").get_db()["push_log"].find_one({"studentId": "UMP0001"}))
    assert logged["rule"] == "tracker_final"


def test_a_student_with_no_dashboard_doc_is_left_alone(monkeypatch, sends):
    """No studyLog document means nothing can be proved missing, so no send (documented
    in push_scheduler) - the rule that keeps a half-imported batch from being nagged."""
    import behavior_push as bp
    from db import get_db

    _seed(monkeypatch, rows={"UMP0001": [], "UMP0002": []})
    _run(get_db()["dashboard_students"].delete_many({"studentId": "UMP0002"}))
    _run(bp.job_tracker_night(dt.datetime(2026, 10, 16, 23, 5, tzinfo=IST)))
    assert [s["studentId"] for s in sends] == ["UMP0001"]
