"""Per-student tracker start rules, joinedOn backfill and the soft-remove flow.

Owner rules (2026-10-13):
  * Join day is never tracked — the tracker starts the DAY AFTER joining.
  * Students who joined before their batch started begin on the batch start day.
  * Mentor manual overrides win over both.
  * Soft-removed students leave every roster view and cannot log in, but their
    data is kept so a restore brings the account back.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from db import DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db
from routers.student_dashboard import (
    _effective_tracker_start,
    backfill_missing_joined_on,
)


@pytest.fixture(autouse=True)
def avoid_live_fetches(monkeypatch):
    from routers import student_dashboard

    monkeypatch.setattr(student_dashboard, "_fetch_tracker_roster_sync", lambda: [])
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", lambda: [])


CFG = {
    "batchStarts": {"Before Result Batch 2": "2026-10-05"},
    "overrides": {"UMP0099": "2026-10-01"},
}


def test_pre_batch_joiner_starts_on_batch_start():
    account = {"studentId": "UMP0001", "joinedOn": "2026-09-28", "batch": "Before Result Batch 2"}
    start, source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-05"
    assert source == "batch"


def test_post_batch_joiner_starts_the_day_after_joining():
    account = {"studentId": "UMP0155", "joinedOn": "2026-10-12", "batch": "Before Result Batch 2"}
    start, source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-13"  # join day 12th is never counted
    assert source == "joined"


def test_join_on_batch_start_day_skips_that_day():
    account = {"studentId": "UMP0140", "joinedOn": "2026-10-05", "batch": "Before Result Batch 2"}
    start, _source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-06"


def test_missing_joined_on_falls_back_to_batch_start():
    account = {"studentId": "UMP0002", "joinedOn": "", "batch": "Before Result Batch 2"}
    start, source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-05"
    assert source == "batch"


def test_no_batch_start_uses_joining_next_day():
    account = {"studentId": "UMP0003", "joinedOn": "2026-10-02", "batch": "Some Other Batch"}
    start, source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-03"
    assert source == "joined"


def test_manual_override_wins_over_everything():
    account = {"studentId": "UMP0099", "joinedOn": "2026-10-12", "batch": "Before Result Batch 2"}
    start, source = _effective_tracker_start(account, CFG)
    assert start.isoformat() == "2026-10-01"
    assert source == "override"


def test_backfill_uses_created_at_for_recent_accounts():
    db = get_db()
    created = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
        "studentId": "UMP0160", "studentName": "New Kid", "batch": "Before Result Batch 2",
        "createdAt": created,
    }))
    result = asyncio.run(backfill_missing_joined_on(db))
    assert result["fixed"] == 1
    doc = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0160"}))
    assert doc["joinedOn"] == "2026-10-12"  # the day they were added (IST)


def test_backfill_keeps_existing_and_uses_earlier_activity_for_bulk_imports():
    db = get_db()
    asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
        "studentId": "UMP0001", "joinedOn": "2026-09-01", "createdAt": datetime(2026, 10, 8, tzinfo=timezone.utc),
    }))
    # Bulk-import artifact: activity predates the account row.
    asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
        "studentId": "UMP0002", "joinedOn": "", "createdAt": datetime(2026, 10, 8, tzinfo=timezone.utc),
    }))
    asyncio.run(db[DASHBOARD_STUDENTS].insert_one({
        "studentId": "UMP0002",
        "studyLog": [{"date": "2026-10-02", "hours": 3}, {"date": "2026-10-06", "hours": 2}],
    }))
    result = asyncio.run(backfill_missing_joined_on(db))
    assert result["fixed"] == 1
    untouched = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0001"}))
    assert untouched["joinedOn"] == "2026-09-01"  # never blanked or rewritten
    bulk = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0002"}))
    # First activity 2 Oct must stay visible under the +1 rule -> join day 1 Oct.
    assert bulk["joinedOn"] == "2026-10-01"


def test_remove_blocks_login_and_hides_from_tracker_then_restores(client, mentor_headers):
    db = get_db()

    def _seed(sid, name, joined):
        asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
            "studentId": sid, "studentName": name, "batch": "Before Result Batch 2",
            "group": "Group 1", "attempt": "Jan 2027", "joinedOn": joined,
            "passwordHash": "x", "passwordChanged": True,
        }))

    _seed("UMP0201", "Stayer", "2026-10-01")
    _seed("UMP0202", "Leaver", "2026-10-01")

    res = client.post(
        "/api/student-dashboard/students/UMP0202/remove",
        headers=mentor_headers,
        json={"confirm": "UMP0202"},
    )
    assert res.status_code == 200, res.text

    # Login blocked with a clear message.
    doc = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0202"}))
    assert doc["status"] == "removed"
    assert doc.get("removedAt")

    # Tracker day view no longer lists the removed student.
    res = client.get("/api/student-dashboard/tracker-day?dayIndex=13&batch=All%20Batches", headers=mentor_headers)
    assert res.status_code == 200, res.text
    ids = [row["id"] for row in res.json()["list"]]
    assert "UMP0201" in ids
    assert "UMP0202" not in ids

    # Removed list shows them; restore brings them back.
    res = client.get("/api/student-dashboard/students/removed", headers=mentor_headers)
    assert [r["studentId"] for r in res.json()["removed"]] == ["UMP0202"]

    res = client.post("/api/student-dashboard/students/UMP0202/restore", headers=mentor_headers)
    assert res.status_code == 200
    doc = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0202"}))
    assert doc["status"] == "Active"
    assert not doc.get("removedAt")

    res = client.get("/api/student-dashboard/tracker-day?dayIndex=13&batch=All%20Batches", headers=mentor_headers)
    ids = [row["id"] for row in res.json()["list"]]
    assert "UMP0202" in ids


def test_removed_student_never_gets_pushes(client, mentor_headers, monkeypatch):
    import push as push_service

    db = get_db()
    asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
        "studentId": "UMP0203", "studentName": "Gone", "status": "removed", "removedAt": "2026-10-13",
    }))
    sent = asyncio.run(push_service.push_to_student("UMP0203", "Hi", "There"))
    assert sent == 0

    # And the learner cannot authenticate.
    from routers.student_auth import authenticate_student

    result = asyncio.run(authenticate_student("UMP0203", "anything"))
    assert result["success"] is False
    assert result["code"] == "removed"


def test_import_never_blanks_joined_on():
    from routers.student_auth import StudentImportItem, upsert_student_account

    db = get_db()
    asyncio.run(db[STUDENT_ACCOUNTS].insert_one({
        "studentId": "UMP0204", "joinedOn": "2026-10-06", "passwordHash": "h",
    }))
    item = StudentImportItem(studentId="UMP0204", password="pwd123", studentName="Keeper", joinedOn="")
    asyncio.run(upsert_student_account(item))
    doc = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0204"}))
    assert doc["joinedOn"] == "2026-10-06"

    # A brand-new account with no join date defaults to the import day (IST).
    item = StudentImportItem(studentId="UMP0205", password="pwd123", studentName="Fresh", joinedOn="")
    asyncio.run(upsert_student_account(item))
    doc = asyncio.run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0205"}))
    assert len(doc["joinedOn"]) == 10


# --- Notes group visibility (2026-10-14) -------------------------------------
# Students sheet stores group as 'Both' (not 'Both Groups'). Group 1 notes must
# still reach Both students; exact-string matching against 'Both Groups' broke
# exactly that.


def test_notes_group_visibility_for_both_students():
    from routers.student_dashboard import _notes_for_student

    notes = [
        {"title": "Acc", "group": "Group 1", "audience": "All Batches"},
        {"title": "Cost", "group": "Group 2", "audience": "All Batches"},
        {"title": "Mix", "group": "Both Groups", "audience": "All Batches"},
        {"title": "Old", "group": "", "audience": "All Batches"},
    ]
    jan = {"attempt": "Jan 2027", "batch": "Before Result Batch 2"}

    both = _notes_for_student(notes, {**jan, "group": "Both"})
    assert [n["title"] for n in both] == ["Acc", "Cost", "Mix", "Old"]

    g1 = _notes_for_student(notes, {**jan, "group": "Group 1"})
    assert [n["title"] for n in g1] == ["Acc", "Mix", "Old"]

    g2 = _notes_for_student(notes, {**jan, "group": "Group 2"})
    assert [n["title"] for n in g2] == ["Cost", "Mix", "Old"]

    both_full = _notes_for_student(notes, {**jan, "group": "Both Groups"})
    assert [n["title"] for n in both_full] == ["Acc", "Cost", "Mix", "Old"]

    # Batch targeting still respected.
    g1_other_batch = _notes_for_student(
        [{"title": "B1 only", "group": "Group 1", "audience": "Before Result Batch 1"}],
        {**jan, "group": "Group 1"},
    )
    assert g1_other_batch == []


def test_notes_hidden_for_sept_2026_attempt_but_master_sees_everything():
    from routers.student_dashboard import _notes_for_student

    notes = [
        {"title": "Acc", "group": "Group 1", "audience": "All Batches"},
        {"title": "Mix", "group": "Both Groups", "audience": "All Batches"},
    ]

    # Sept 2026 attempt (old cohort, e.g. Super 30 batch): nothing at all.
    sept = _notes_for_student(notes, {"group": "Group 1", "batch": "Super 30", "attempt": "Sept 2026"})
    assert sept == []

    # Jan 2027 (current cohort): visible.
    jan = _notes_for_student(notes, {"group": "Group 1", "batch": "Before Result Batch 1", "attempt": "Jan 2027"})
    assert len(jan) == 2

    # May 2027 (later attempt): visible.
    may = _notes_for_student(notes, {"group": "Both", "batch": "Before Result Batch 1", "attempt": "May 2027"})
    assert len(may) == 2

    # Master test account keeps full visibility.
    master = _notes_for_student(notes, {"group": "", "batch": "", "attempt": "", "master": True})
    assert len(master) == 2
