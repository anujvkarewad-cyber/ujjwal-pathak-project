"""On-leave / self-reported-absent days (owner spec, 14 Oct 2026).

Behaviour under test:
  * the student declares leave (range) or absent (single day) himself;
  * the tracker labels those days Leave/Absent instead of Missed;
  * both are excluded from the attendance % (owner decision: "dono exclude")
    but are reported separately, so the mentor sees WHY a day was empty;
  * the 23:00 / 07:00 / 14:00 missing-tracker reminders skip excused days;
  * the mentor can cancel a record (mentor override wins).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routers import attendance as attendance_lib
from routers.student_dashboard import _build_missed_tracker_report, _tracker_day_entry

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()
TEST_SIDS = ["ATTTEST1", "ATTTEST2"]


def _run(coro):
    return asyncio.run(coro)


async def _fake_ensure_student(db, sid):
    """Test ids are not real accounts - skip the existence check."""
    return None


def _purge():
    from db import get_db

    async def _wipe():
        db = get_db()
        await db[attendance_lib.STUDENT_ABSENT].delete_many({"studentId": {"$in": TEST_SIDS}})
        await db[attendance_lib.STUDENT_LEAVE].delete_many({"studentId": {"$in": TEST_SIDS}})

    _run(_wipe())


@pytest.fixture()
def att(monkeypatch):
    monkeypatch.setattr(attendance_lib, "_ensure_student", _fake_ensure_student)
    _purge()
    yield attendance_lib
    _purge()


def _db():
    from db import get_db

    return get_db()


# ── absent ──────────────────────────────────────────────────────────────────


def test_mark_absent_today_then_index_then_cancel(att):
    db = _db()
    out = _run(att.mark_absent(db, TEST_SIDS[0], None, "Fever", source="student"))
    assert out["success"] is True and out["kind"] == "absent"

    index = _run(att.attendance_index(db, TODAY, TODAY))
    assert index[(TEST_SIDS[0], TODAY)]["kind"] == "absent"
    assert index[(TEST_SIDS[0], TODAY)]["reason"] == "Fever"

    assert TEST_SIDS[0] in _run(att.excused_students(db, TODAY))

    cancelled = _run(att.cancel_leave(db, TEST_SIDS[0], None, TODAY, actor="mentor"))
    assert cancelled["status"] == "cancelled"
    assert _run(att.attendance_index(db, TODAY, TODAY)) == {}


def test_absent_rejects_future_and_too_old_dates(att):
    db = _db()
    with pytest.raises(HTTPException):
        _run(att.mark_absent(db, TEST_SIDS[0], TODAY + timedelta(days=1), "", source="student"))
    with pytest.raises(HTTPException):
        _run(
            att.mark_absent(
                db, TEST_SIDS[0], TODAY - timedelta(days=att.BACKFILL_DAYS + 1), "", source="student"
            )
        )
    # backfill window itself is allowed
    out = _run(
        att.mark_absent(db, TEST_SIDS[0], TODAY - timedelta(days=att.BACKFILL_DAYS), "purani", source="student")
    )
    assert out["success"] is True


# ── leave ───────────────────────────────────────────────────────────────────


def test_leave_range_is_indexed_for_every_day(att):
    db = _db()
    start = TODAY
    end = TODAY + timedelta(days=2)
    out = _run(att.request_leave(db, TEST_SIDS[1], start, end, "Ghar gaya", source="student"))
    assert out["success"] is True and out["days"] == 3

    index = _run(att.attendance_index(db, start, end))
    for offset in range(3):
        day = start + timedelta(days=offset)
        assert index[(TEST_SIDS[1], day)]["kind"] == "leave"

    # outside the range nothing is excused
    assert _run(att.attendance_index(db, end + timedelta(days=1), end + timedelta(days=1))) == {}


def test_overlapping_leave_extends_one_record(att):
    db = _db()

    async def _count():
        return await db[attendance_lib.STUDENT_LEAVE].count_documents({"studentId": TEST_SIDS[1]})

    first = _run(att.request_leave(db, TEST_SIDS[1], TODAY + timedelta(days=1), TODAY + timedelta(days=2), "a"))
    second = _run(att.request_leave(db, TEST_SIDS[1], TODAY + timedelta(days=3), TODAY + timedelta(days=4), "b"))
    assert second["leaveId"] == first["leaveId"]  # extended, not duplicated
    assert second["days"] == 4
    assert _run(_count()) == 1


def test_leave_validation(att):
    db = _db()
    with pytest.raises(HTTPException):
        _run(att.request_leave(db, TEST_SIDS[1], TODAY + timedelta(days=2), TODAY + timedelta(days=1), ""))
    with pytest.raises(HTTPException):
        _run(
            att.request_leave(
                db,
                TEST_SIDS[1],
                TODAY,
                TODAY + timedelta(days=attendance_lib.MAX_LEAVE_DAYS),
                "",
            )
        )
    with pytest.raises(HTTPException):
        _run(
            att.request_leave(
                db,
                TEST_SIDS[1],
                TODAY - timedelta(days=attendance_lib.BACKFILL_DAYS + 2),
                TODAY - timedelta(days=attendance_lib.BACKFILL_DAYS + 1),
                "",
            )
        )


def test_absent_inside_a_leave_range_stays_leave(att):
    db = _db()
    _run(att.request_leave(db, TEST_SIDS[0], TODAY, TODAY + timedelta(days=1), "leave"))
    out = _run(att.mark_absent(db, TEST_SIDS[0], TODAY, "duplicate", source="student"))
    assert out["kind"] == "leave"
    index = _run(att.attendance_index(db, TODAY, TODAY))
    assert index[(TEST_SIDS[0], TODAY)]["kind"] == "leave"


def test_student_status_payload_for_the_app(att):
    db = _db()
    _run(att.request_leave(db, TEST_SIDS[0], TODAY, TODAY + timedelta(days=3), "Kahi ja raha hoon"))
    status = _run(att.student_status(db, TEST_SIDS[0]))
    assert status["status"] == "leave"
    assert status["leaves"][0]["days"] == 4
    assert status["leaves"][0]["active"] is True
    assert status["limits"]["maxLeaveDays"] == attendance_lib.MAX_LEAVE_DAYS


# ── tracker wiring ──────────────────────────────────────────────────────────


def test_tracker_day_entry_labels_leave_and_absent_instead_of_missed():
    leave = _tracker_day_entry([], [], TODAY, {"kind": "leave", "reason": "Ghar"})
    assert leave["status"] == "leave" and leave["excused"] is True and leave["submitted"] is False

    absent = _tracker_day_entry([], [], TODAY, {"kind": "absent", "reason": "Fever"})
    assert absent["status"] == "absent" and absent["excused"] is True

    plain = _tracker_day_entry([], [], TODAY, None)
    assert plain["status"] == "missed" and plain["excused"] is False

    # a submitted log always wins over a leave declaration
    present = _tracker_day_entry([{"date": TODAY, "hours": 2}], [], TODAY, {"kind": "leave"})
    assert present["status"] == "present" and present["submitted"] is True


def _account(sid: str) -> dict:
    return {
        "studentId": sid,
        "studentName": sid,
        "group": "Group 1",
        "batch": "Before Result Batch 1",
        "attempt": "2027-01-01",
        "joinedOn": (TODAY - timedelta(days=30)).isoformat(),
        "master": False,
    }


def test_missed_report_excludes_leave_and_absent_days():
    sid = TEST_SIDS[0]
    from_day = TODAY - timedelta(days=2)
    submissions = [{"studentId": sid, "date": from_day}]  # day 1: present
    attendance = {
        (sid, from_day + timedelta(days=1)): {"kind": "leave", "reason": "shaadi"},
        (sid, TODAY): {"kind": "absent", "reason": "fever"},
    }
    cfg = {"overrides": {sid: from_day.isoformat()}}
    report = _build_missed_tracker_report(
        [_account(sid)], submissions, from_day, TODAY, cfg=cfg, attendance=attendance
    )
    row = report["items"][0]
    assert row["expectedDays"] == 3
    assert row["submittedDays"] == 1
    assert row["missedDays"] == 0 and row["missedDates"] == []
    assert row["leaveDays"] == 1 and row["leaveDates"] == [(from_day + timedelta(days=1)).isoformat()]
    assert row["absentDays"] == 1 and row["absentDates"] == [TODAY.isoformat()]
    assert report["studentsWithMissedDays"] == 0


def test_missed_report_still_counts_a_real_gap():
    sid = TEST_SIDS[1]
    from_day = TODAY - timedelta(days=2)
    cfg = {"overrides": {sid: from_day.isoformat()}}
    report = _build_missed_tracker_report(
        [_account(sid)],
        [{"studentId": sid, "date": from_day}],
        from_day,
        TODAY,
        cfg=cfg,
        attendance={(sid, from_day + timedelta(days=1)): {"kind": "leave", "reason": "x"}},
    )
    row = report["items"][0]
    assert row["missedDays"] == 1  # today, no leave/absent declared
    assert row["missedDates"] == [TODAY.isoformat()]


# ── endpoint level (app <-> gateway <-> backend wiring) ─────────────────────


def test_app_can_write_leave_absent_and_read_the_status_back(client, monkeypatch, mentor_headers):
    from test_student_dashboard import seed_student_auth
    actors = [seed_student_auth(client, mentor_headers, sid) for sid in TEST_SIDS]
    monkeypatch.setattr(attendance_lib, "_ensure_student", _fake_ensure_student)
    sid = TEST_SIDS[0]
    end = TODAY + timedelta(days=2)

    write = client.post("/api/student-dashboard/write", headers=actors[0],
        json={
            "action": "attendance.requestLeave",
            "payload": {"studentId": sid, "from": TODAY.isoformat(), "to": end.isoformat(), "reason": "Ghar"},
        },
    )
    assert write.status_code == 200, write.text
    assert write.json()["ok"] is True

    read = client.post("/api/student-dashboard/get", headers=actors[0], json={"action": "attendance.status", "payload": {"studentId": sid}}
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["found"] is True
    assert body["result"]["status"] == "leave"
    assert body["result"]["leaves"][0]["days"] == 3

    absent = client.post("/api/student-dashboard/write", headers=actors[1],
        json={"action": "attendance.markAbsent", "payload": {"studentId": TEST_SIDS[1], "reason": "Fever"}},
    )
    assert absent.json()["ok"] is True
    read_absent = client.post("/api/student-dashboard/get", headers=actors[1],
        json={"action": "attendance.status", "payload": {"studentId": TEST_SIDS[1]}},
    ).json()
    assert read_absent["result"]["status"] == "absent"

    leave_id = body["result"]["leaves"][0]["leaveId"]
    cancel = client.post("/api/student-dashboard/write", headers=actors[0],
        json={"action": "attendance.cancelLeave", "payload": {"studentId": sid, "leaveId": leave_id}},
    )
    assert cancel.json()["ok"] is True
    after = client.post("/api/student-dashboard/get", headers=actors[0], json={"action": "attendance.status", "payload": {"studentId": sid}}
    ).json()
    assert after["result"]["status"] == "none"


def test_write_reports_a_clear_error_instead_of_crashing(client, monkeypatch, mentor_headers):
    """Students must never get a 500/HTML for a bad date."""
    from test_student_dashboard import seed_student_auth
    actors = [seed_student_auth(client, mentor_headers, sid) for sid in TEST_SIDS]
    monkeypatch.setattr(attendance_lib, "_ensure_student", _fake_ensure_student)
    res = client.post("/api/student-dashboard/write", headers=actors[0],
        json={
            "action": "attendance.markAbsent",
            "payload": {"studentId": TEST_SIDS[0], "date": (TODAY + timedelta(days=5)).isoformat()},
        },
    )
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert "aage" in res.json()["result"]["message"]


def test_tracker_day_shows_leave_and_excludes_it_from_the_rate(client, mentor_headers, monkeypatch):
    from routers import student_dashboard

    sid = TEST_SIDS[0]
    account = {
        "studentId": sid,
        "studentName": "Attendance Test",
        "group": "Group 1",
        "batch": "Before Result Batch 1",
        "attempt": "2027-01-01",
        "joinedOn": (TODAY - timedelta(days=30)).isoformat(),
        "master": False,
    }
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_roster_sync", lambda: [account])
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", lambda: [])
    monkeypatch.setattr(attendance_lib, "_ensure_student", _fake_ensure_student)
    _run(attendance_lib.request_leave(_db(), sid, TODAY, TODAY + timedelta(days=1), "Ghar", source="student"))

    res = client.get(
        "/api/student-dashboard/tracker-day",
        params={"dayIndex": 13, "batch": "All Batches"},
        headers=mentor_headers,
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    row = next((item for item in payload["list"] if item["id"] == sid), None)
    assert row is not None, payload["list"]
    assert row["entry"]["status"] == "leave"
    assert row["entry"]["excused"] is True
    assert payload["onLeave"] == 1
    assert payload["missed"] == 0
    assert payload["countable"] == 0
    assert payload["rate"] == 0
