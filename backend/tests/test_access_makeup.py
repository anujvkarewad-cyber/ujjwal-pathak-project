"""Makeup time for students who were locked out (owner decision, 15-Oct-2026).

"What was missed must show up as soon as access is switched back on" — so:

  * a student's personal test window is extended by the time they were locked out
    INSIDE that window (capped), while every other student's view is untouched;
  * the extension is a per-student view of the same test document — the mentor's
    stored window is never rewritten;
  * an attempt made on granted time is tagged, so late-with-credit is never
    confused with on-time;
  * a locked-out student is not pinged at all (they could not open it), and the
    restore itself sends the "you missed this" notice, driven by a logged
    access timeline that is written on every real toggle.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import push as push_service
from db import (
    ANALYTICS_TEST_HISTORY,
    DEVICE_TOKENS,
    DASHBOARD_SHARED,
    MENTOR_TESTS,
    STUDENT_ACCESS_EVENTS,
    STUDENT_ACCOUNTS,
    get_db,
)
from routers import access_events as access_lib
from routers import student_tests as st

NOW = datetime.now(timezone.utc)
SID_MAKEUP = "MKUP0001"   # locked out for the whole window, restored 1 h ago
SID_CLEAN = "MKUP0002"    # never locked out
SID_BLOCKED = "MKUP0003"  # locked out right now
BATCH = "MKUPB1"
TEST_ID = "T-MKUP-1"
OPEN_ID = "T-MKUP-OPEN"   # no window_end at all: always attemptable, so nothing to credit
TEST_IDS = [TEST_ID, OPEN_ID]


def _run(coro):
    return asyncio.run(coro)


def _iso(stamp: datetime) -> str:
    return stamp.isoformat(timespec="seconds")


def _window():
    """Opened 30 h ago, closed 6 h ago. A full-day lockout inside it puts the
    affected student's own deadline 18 h in the future."""
    return _iso(NOW - timedelta(hours=30)), _iso(NOW - timedelta(hours=6))


async def _seed_board(db):
    await db[STUDENT_ACCOUNTS].insert_many([
        {"studentId": SID_MAKEUP, "studentName": "Makeup Student", "batch": BATCH, "group": "1", "attempt": "Jan 2027",
         "accessEnabled": True, "accessUpdatedAt": _iso(NOW - timedelta(hours=1))},
        {"studentId": SID_CLEAN, "studentName": "Clean Student", "batch": BATCH, "group": "1", "attempt": "Jan 2027",
         "accessEnabled": True},
        {"studentId": SID_BLOCKED, "studentName": "Blocked Student", "batch": BATCH, "group": "1", "attempt": "Jan 2027",
         "accessEnabled": False, "accessReason": "Not studying", "accessUpdatedAt": _iso(NOW - timedelta(days=1))},
    ])
    start, end = _window()
    await db[MENTOR_TESTS].insert_one({
        "testId": TEST_ID, "published": True, "kind": "paper-test", "title": "Oct revision test",
        "subject": "Audit", "batch": BATCH, "group": "1", "marks": 1, "total_marks": 1,
        "window_start": start, "window_end": end, "createdAt": _iso(NOW - timedelta(hours=32)),
    })
    await db[MENTOR_TESTS].insert_one({
        "testId": OPEN_ID, "published": True, "kind": "paper-test", "title": "Open book assignment",
        "subject": "Audit", "batch": BATCH, "group": "1", "marks": 10,
        "createdAt": _iso(NOW - timedelta(hours=32)),
    })
    await db[STUDENT_ACCESS_EVENTS].insert_many([
        {"studentId": SID_MAKEUP, "enabled": False, "at": _iso(NOW - timedelta(days=2)),
         "reason": "Not studying", "by": "mentor"},
        {"studentId": SID_MAKEUP, "enabled": True, "at": _iso(NOW - timedelta(hours=1)),
         "reason": "", "by": "mentor"},
    ])
    await db[DEVICE_TOKENS].insert_many([
        {"studentId": SID_CLEAN, "token": "tok-clean"},
        {"studentId": SID_BLOCKED, "token": "tok-blocked"},
    ])


async def _clear_board(db):
    ids = [SID_MAKEUP, SID_CLEAN, SID_BLOCKED]
    await db[STUDENT_ACCOUNTS].delete_many({"studentId": {"$in": ids}})
    await db[MENTOR_TESTS].delete_many({"testId": {"$in": TEST_IDS}})
    await db[STUDENT_ACCESS_EVENTS].delete_many({"studentId": {"$in": ids}})
    await db[ANALYTICS_TEST_HISTORY].delete_many({"studentId": {"$in": ids}})
    await db[DEVICE_TOKENS].delete_many({"studentId": {"$in": ids}})
    await db[DASHBOARD_SHARED].delete_many({"_id": "shared"})


@pytest.fixture()
def board():
    db = get_db()
    _run(_seed_board(db))
    yield db
    _run(_clear_board(db))


@pytest.fixture()
def logged_in(monkeypatch):
    async def fake_validate(student_id, password):
        if student_id not in (SID_MAKEUP, SID_CLEAN, SID_BLOCKED):
            raise HTTPException(status_code=401, detail="Invalid Student ID or password")
        return {"studentId": student_id, "success": True}

    monkeypatch.setattr(st, "_validate_existing_student_login", fake_validate)


def _list_item(client, sid):
    res = client.post("/api/student-tests/list", json={"studentId": sid, "password": "x"})
    assert res.status_code == 200, res.text
    item = next((row for row in res.json()["tests"] if row["testId"] == TEST_ID), None)
    assert item, res.json()
    return item


# ── the credit maths ────────────────────────────────────────────────────────

def test_only_time_lost_inside_the_window_is_given_back():
    start = datetime(2026, 10, 10, tzinfo=timezone.utc)
    end = datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert access_lib.locked_out_minutes([], start, end) == 0
    assert access_lib.locked_out_minutes([(start, end)], start, end) == 2 * 24 * 60
    half = start + timedelta(days=1)
    assert access_lib.locked_out_minutes([(half, end)], start, end) == 24 * 60
    # locked out only AFTER the window shut: nothing was taken away, so nothing is owed
    assert access_lib.locked_out_minutes([(end, end + timedelta(days=3))], start, end) == 0
    # the overlap can never exceed the window itself...
    assert access_lib.locked_out_minutes([(start - timedelta(days=30), end + timedelta(days=30))], start, end) \
        == (end - start).total_seconds() / 60
    # ...and a window longer than the cap is cut down to the cap (14 days)
    long_start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    long_end = long_start + timedelta(days=30)
    assert access_lib.locked_out_minutes([(long_start, long_end)], long_start, long_end) \
        == access_lib.MAKEUP_CAP_DAYS * 24 * 60


def test_the_view_is_shifted_without_touching_the_stored_window():
    test = {"window_start": "2026-10-10T00:00", "window_end": "2026-10-12T00:00"}
    assert access_lib.shifted_view(test, 0) is test
    shifted = access_lib.shifted_view(test, 90)
    assert shifted["window_end"] == "2026-10-12T01:30"
    assert test["window_end"] == "2026-10-12T00:00", "the mentor's window must not move"
    # always-open tests need no makeup
    assert access_lib.shifted_view({"window_end": ""}, 600) == {"window_end": ""}


def test_legacy_account_with_no_events_is_credited_only_while_actually_off():
    """Toggles predate logging. `accessUpdatedAt` is the one honest anchor, and it
    only proves anything while the student is still locked out."""
    db = get_db()
    _run(_seed_board(db))
    try:
        # SID_BLOCKED: no events, accessEnabled False since yesterday
        account = _run(db[STUDENT_ACCOUNTS].find_one({"studentId": SID_BLOCKED}, {"_id": 0}))
        spans = _run(access_lib.off_intervals(db, SID_BLOCKED, account, until=NOW))
        assert len(spans) == 1 and spans[0][1] == NOW

        # SID_CLEAN: no events, access ON -> history unknown, so invent nothing
        clean = _run(db[STUDENT_ACCOUNTS].find_one({"studentId": SID_CLEAN}, {"_id": 0}))
        assert _run(access_lib.off_intervals(db, SID_CLEAN, clean, until=NOW)) == []
    finally:
        _run(_clear_board(db))


# ── what the student sees ───────────────────────────────────────────────────

def test_locked_out_window_reopens_for_that_student_only(client, board, logged_in):
    original_end = _run(board[MENTOR_TESTS].find_one({"testId": TEST_ID}, {"_id": 0}))["window_end"]
    now_ms = int(NOW.timestamp() * 1000)

    mine = _list_item(client, SID_MAKEUP)
    assert mine["makeup"] is True and mine["makeupMinutes"] == 24 * 60, mine
    assert mine["status"] == "open", mine
    assert mine["window_end"] == access_lib.shifted_view({"window_end": original_end}, 24 * 60)["window_end"]

    theirs = _list_item(client, SID_CLEAN)
    assert theirs["status"] == "closed", theirs
    assert theirs["makeup"] is False and theirs["window_end"] == original_end

    # an always-open test must not be reported as makeup time, even for a student who
    # was locked out the whole time - nothing was taken away from them
    open_item = next(row for row in client.post(
        "/api/student-tests/list", json={"studentId": SID_MAKEUP, "password": "x"}
    ).json()["tests"] if row["testId"] == OPEN_ID)
    assert open_item["status"] == "open" and open_item["makeup"] is False, open_item

    # the paper itself follows the same rule the list advertises
    ok = client.post("/api/student-tests/paper", json={"studentId": SID_MAKEUP, "password": "x", "testId": TEST_ID})
    assert ok.status_code == 200, ok.text
    denied = client.post("/api/student-tests/paper", json={"studentId": SID_CLEAN, "password": "x", "testId": TEST_ID})
    assert denied.status_code == 409, denied.text
    assert "window band" in denied.json()["detail"]


def test_granted_time_is_tagged_so_late_is_not_read_as_on_time(client, board, logged_in):
    submit = client.post("/api/student-tests/submit", json={
        "studentId": SID_MAKEUP, "password": "x", "testId": TEST_ID,
        "selfMarks": 1, "remarks": "checked with the scheme", "answerUrl": "",
    })
    assert submit.status_code == 200, submit.text
    assert submit.json()["scorePct"] == 100

    mine = _run(board[ANALYTICS_TEST_HISTORY].find_one({"studentId": SID_MAKEUP}, {"_id": 0}))
    assert mine["makeup"] is True, mine

    # /submit has no deadline of its own, so a clean student can still submit late -
    # and that attempt must NOT be laundered as makeup time.
    late = client.post("/api/student-tests/submit", json={
        "studentId": SID_CLEAN, "password": "x", "testId": TEST_ID, "selfMarks": 1,
    })
    assert late.status_code == 200, late.text
    theirs = _run(board[ANALYTICS_TEST_HISTORY].find_one({"studentId": SID_CLEAN}, {"_id": 0}))
    assert theirs["makeup"] is False, theirs


# ── pushes ──────────────────────────────────────────────────────────────────

def test_a_locked_out_student_is_never_pinged(board, monkeypatch):
    """They cannot open the app, so "New test published" only upsets them."""
    sent: list = []

    async def fake_send(token, title, body, data):
        sent.append(token)
        return True

    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "_send_to_token", fake_send)

    assert _run(push_service.push_to_student(SID_BLOCKED, "📝 New test", "body")) == 0
    assert sent == [], "a blocked student must not receive the push at all"

    assert _run(push_service.push_to_student(SID_CLEAN, "📝 New test", "body")) == 1
    assert sent == ["tok-clean"]


def test_restoring_access_logs_the_toggle_and_sends_the_missed_work_notice(client, mentor_headers, monkeypatch):
    db = get_db()
    blocked = "MKUP0004"
    notices: list = []

    async def fake_push(student_id, title, body, *, link="", tag=""):
        notices.append({"studentId": student_id, "title": title, "body": body, "link": link})
        return 2

    async def seed():
        await db[STUDENT_ACCOUNTS].insert_one({
            "studentId": blocked, "studentName": "Coming Back", "batch": BATCH, "group": "1",
            "accessEnabled": False, "accessReason": "Not studying",
            "accessUpdatedAt": _iso(NOW - timedelta(days=2)),
        })
        await db[MENTOR_TESTS].insert_one({
            "testId": "T-MKUP-2", "published": True, "kind": "paper-test",
            "title": "Missed revision test", "subject": "Audit", "batch": BATCH, "group": "1",
            "marks": 10, "createdAt": _iso(NOW),
        })
        await db[DASHBOARD_SHARED].insert_one({"_id": "shared", "notes": [
            {"id": "N-MKUP", "title": "Nov plan", "date": NOW.strftime("%Y-%m-%d"),
             "audience": BATCH, "group": "1"},
        ]})

    _run(seed())
    try:
        import routers.student_dashboard as dashboard

        monkeypatch.setattr(dashboard.push_service, "push_to_student", fake_push)
        monkeypatch.setattr(dashboard, "_mirror_access_to_sheet", lambda *a, **k: asyncio.sleep(0.0, result=False))

        res = client.post(f"/api/student-dashboard/students/{blocked}/access",
                          headers=mentor_headers, json={"enabled": True})
        assert res.status_code == 200, res.text
        out = res.json()
        assert out["accessEnabled"] is True and out["accessChanged"] is True, out
        assert out["restoreNoticeSent"] == 2, out

        assert len(notices) == 1, notices
        assert "1 test" in notices[0]["body"] and "1 new note" in notices[0]["body"], notices[0]
        assert notices[0]["link"] == "tests"

        events = _run(db[STUDENT_ACCESS_EVENTS].find({"studentId": blocked}).to_list(10))
        assert [e["enabled"] for e in events] == [True], events
        assert _run(db[STUDENT_ACCOUNTS].find_one({"studentId": blocked}, {"_id": 0}))["accessEnabled"] is True

        # a second ON is not a change: no new event, no second nag
        again = client.post(f"/api/student-dashboard/students/{blocked}/access",
                            headers=mentor_headers, json={"enabled": True})
        assert again.json()["accessChanged"] is False, again.json()
        assert len(notices) == 1
        assert _run(db[STUDENT_ACCESS_EVENTS].count_documents({"studentId": blocked})) == 1
    finally:
        async def cleanup():
            await db[STUDENT_ACCOUNTS].delete_many({"studentId": blocked})
            await db[MENTOR_TESTS].delete_many({"testId": "T-MKUP-2"})
            await db[STUDENT_ACCESS_EVENTS].delete_many({"studentId": blocked})
            await db[DASHBOARD_SHARED].delete_many({"_id": "shared"})
        _run(cleanup())
