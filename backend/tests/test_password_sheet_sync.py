"""The sheet must end up holding the password the student actually uses.

Contract:
  * a successful login hands the plaintext to the sheet writer (that is the only
    moment the value exists anywhere), and a failed login does not,
  * the change-password response is not delayed by, and cannot be broken by, the
    sheet write,
  * one value is written once - the next login with the same password is a no-op,
  * the write is targeted by header names, not by hardcoded column letters,
  * PASSWORD_SHEET_SYNC=0 switches every write off.
"""
import asyncio
import os

import password_sheet_sync as pss
from auth import hash_password
from db import STUDENT_ACCOUNTS, get_db

HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch",
          "Passwords", "Password Changed", "Access Enabled"]
IDS = [["Student ID"], ["UMP0001"], ["UMP0132"], ["UMP0040"]]


def _stub(monkeypatch, writes):
    """Replace the two Google calls with recorders."""
    pss.reset_cache()

    async def fake_read(rng):
        # _read_range returns rows, so the header range is a sheet with one row
        return [HEADER] if rng.startswith("A1:U1") else IDS

    async def fake_write(cell, value):
        writes.append((cell, value))
        return True

    monkeypatch.setattr(pss, "_read_range", fake_read)
    monkeypatch.setattr(pss, "_write_cell", fake_write)


def test_write_targets_the_columns_named_in_the_header(monkeypatch):
    writes = []
    _stub(monkeypatch, writes)
    assert asyncio.run(pss.write_password("ump0132", "MyNewPass1")) is True
    # 'Passwords' is column H, 'Password Changed' is column I; UMP0132 is sheet row 3
    assert writes == [("H3", "MyNewPass1"), ("I3", "Yes")]
    writes.clear()
    # a login mirror must not raise the 'Password Changed' flag - it is only about
    # the value, or every login would freeze the flag on for that student
    asyncio.run(pss.write_password("UMP0132", "MyNewPass1", flag_changed=False))
    assert writes == [("H3", "MyNewPass1")]


def test_unknown_student_and_empty_value_write_nothing(monkeypatch):
    writes = []
    _stub(monkeypatch, writes)
    assert asyncio.run(pss.write_password("UMP7777", "x")) is False
    assert asyncio.run(pss.write_password("UMP0132", "")) is False
    assert writes == []


def test_same_password_is_written_only_once(monkeypatch):
    writes = []
    _stub(monkeypatch, writes)
    pss.queue_sync("UMP0132", "First12345")   # no running loop -> runs inline
    pss.queue_sync("UMP0132", "First12345")   # already mirrored
    pss.queue_sync("UMP0132", "Second12345")  # changed again -> written
    assert [w for w in writes if w[0].startswith("H")] == [
        ("H3", "First12345"), ("H3", "Second12345")
    ]


def test_a_google_failure_never_surfaces_to_the_caller(monkeypatch):
    _stub(monkeypatch, [])

    async def boom(cell, value):
        raise RuntimeError("Google is down")

    monkeypatch.setattr(pss, "_write_cell", boom)
    pss.queue_sync("UMP0132", "Whatever12")  # must not raise
    assert pss._written.get("UMP0132") is None  # and must not claim it was written


def test_switch_off_means_no_writes(monkeypatch):
    writes = []
    _stub(monkeypatch, writes)
    monkeypatch.setattr(pss, "ENABLED", False)
    pss.queue_sync("UMP0132", "Quiet12345")
    assert writes == []


# ── the routes ──────────────────────────────────────────────────────────────
PASSWORD = "UPM2026@132"


def _seed():
    async def go():
        await get_db()[STUDENT_ACCOUNTS].delete_many({})
        await get_db()[STUDENT_ACCOUNTS].insert_one({
            "studentId": "UMP0132", "studentName": "Khushi", "batch": "Before Result Batch 1",
            "passwordHash": hash_password(PASSWORD), "passwordChanged": True,
            "attempt": "Jan 2027", "caLevel": "CA Intermediate", "group": "Group 1",
            "accessEnabled": True,
        })

    asyncio.run(go())


def test_login_reports_the_password_only_when_it_is_correct(monkeypatch):
    _seed()
    calls = []
    monkeypatch.setattr(pss, "queue_sync", lambda sid, pwd, **kw: calls.append((sid, pwd, kw)))

    from routers.student_auth import student_login, StudentLoginBody

    bad = asyncio.run(student_login(StudentLoginBody(studentId="UMP0132", password="nope")))
    assert bad["result"]["success"] is False and calls == []

    ok = asyncio.run(student_login(StudentLoginBody(studentId="UMP0132", password=PASSWORD)))
    assert ok["result"]["success"] is True
    # the login path mirrors the value only - no flag
    assert calls == [("UMP0132", PASSWORD, {})]


def test_change_password_queues_the_new_value_after_writing_mongo(monkeypatch):
    _seed()
    calls = []
    monkeypatch.setattr(pss, "queue_sync", lambda sid, pwd, **kw: calls.append((sid, pwd, kw)))

    from routers.student_auth import student_change_password, ChangePasswordBody

    res = asyncio.run(student_change_password(
        ChangePasswordBody(studentId="UMP0132", currentPassword=PASSWORD, newPassword="BrandNew99")
    ))
    assert res["result"]["success"] is True
    # a real change raises the flag too
    assert calls == [("UMP0132", "BrandNew99", {"flag_changed": True})]

    doc = asyncio.run(get_db()[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0132"}))
    assert hash_password("BrandNew99") != doc["passwordHash"]  # rotated, not stored plainly
    from auth import verify_password

    assert verify_password("BrandNew99", doc["passwordHash"]) is True
    assert verify_password(PASSWORD, doc["passwordHash"]) is False


def test_module_imports_without_env_and_defaults_to_on():
    assert pss.ENABLED is (os.environ.get("PASSWORD_SHEET_SYNC", "1").strip().lower()
                           not in ("0", "false", "no", "off"))
    assert pss.SHEET_ID  # a real sheet id is configured
