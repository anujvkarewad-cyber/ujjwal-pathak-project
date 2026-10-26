"""The progress meter for "every student's sheet cell holds a usable password".

The rule under test is classification only - the mirror that shrinks the pending
list lives in the login path and is tested in test_password_sheet_sync.py.
"""
import asyncio

import bcrypt

import password_sheet_sync as pss

from db import STUDENT_ACCOUNTS, get_db

HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch",
          "Passwords", "Password Changed"]
KNOWN = "KnownGood123"


def _hash(text=KNOWN):
    return bcrypt.hashpw(text.encode(), bcrypt.gensalt(rounds=4)).decode()


def _rows(*pairs):
    out = [HEADER]
    for sid, value in pairs:
        out.append([sid, f"Name {sid}", "x@y.z", "IP", "Group 1", "Jan 2027", "Before Result Batch 1", value, ""])
    return out


def _acc(sid, hashed, **extra):
    return {"studentId": sid, "studentName": f"Name {sid}", "batch": "Before Result Batch 1",
            "passwordHash": hashed, **extra}


def test_classifies_valid_marker_stale_and_blank():
    hashed = _hash()
    accounts = [
        _acc("UMP0132", hashed),
        _acc("UMP0040", hashed),
        _acc("UMP0041", hashed),
        _acc("UMP0043", hashed),
    ]
    rows = _rows(
        ("UMP0132", KNOWN),                                     # valid
        ("UMP0040", "CHANGED-IN-APP 15-Oct-2026 (old value invalid)"),  # marked
        ("UMP0041", "UPM2026@041"),                              # stale: a dead typed password
        ("UMP0043", ""),                                         # blank
    )
    out = pss.coverage_of(rows, accounts)
    assert (out["valid"], out["marked"], out["stale"], out["blank"]) == (1, 1, 1, 1)
    assert out["total"] == 4
    states = {row["studentId"]: row["state"] for row in out["pending"]}
    assert states == {"UMP0040": "marked", "UMP0041": "stale", "UMP0043": "blank"}


def test_a_valid_cell_is_not_pending_even_when_the_flag_cell_is_empty():
    hashed = _hash("Rotat3d!ok")
    rows = _rows(("UMP0087", "Rotat3d!ok"))
    out = pss.coverage_of(rows, [_acc("UMP0087", hashed)])
    assert out["valid"] == 1 and out["pending"] == []


def test_master_and_removed_students_are_never_counted():
    hashed = _hash()
    rows = _rows(
        ("UMP0000", "whatever1"), ("UMP9999", "whatever2"),
        ("UMP0039", "deadpass1"),            # soft-removed
        ("UMP0040", KNOWN),
    )
    accounts = [
        _acc("UMP0039", hashed, removedAt="2026-10-14T06:59:22+00:00"),
        _acc("UMP0040", hashed),
    ]
    out = pss.coverage_of(rows, accounts)
    assert out["total"] == 1 and out["valid"] == 1 and out["pending"] == []


def test_legacy_plaintext_accounts_still_count_as_valid():
    """Accounts from before the bcrypt migration store plaintext - the same test must pass."""
    rows = _rows(("UMP0045", "LegacyPass1"))
    out = pss.coverage_of(rows, [{"studentId": "UMP0045", "studentName": "Namrata", "password": "LegacyPass1"}])
    assert out["valid"] == 1 and out["pending"] == []


def test_sheet_without_the_columns_says_so_instead_of_claiming_zero_pending():
    out = pss.coverage_of([["Student ID", "Name"]], [])
    assert out["skipped"]["noHeader"] is True


# ── the mentor route ────────────────────────────────────────────────────────
def test_coverage_route_reports_the_numbers(client, mentor_headers, monkeypatch):
    hashed = _hash()

    async def go():
        await get_db()[STUDENT_ACCOUNTS].delete_many({})
        await get_db()[STUDENT_ACCOUNTS].insert_many([
            _acc("UMP0132", hashed),
            _acc("UMP0040", hashed),
        ])

    asyncio.run(go())

    async def fake_rows():
        return _rows(("UMP0132", KNOWN), ("UMP0040", "CHANGED-IN-APP 15-Oct-2026 (old value invalid)"))

    monkeypatch.setattr("routers.student_auth._sheet_students_rows", fake_rows)

    res = client.get("/api/student-auth/students/password-coverage?refresh=1", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2 and body["valid"] == 1 and body["marked"] == 1
    assert body["usablePct"] == 50.0
    assert [p["studentId"] for p in body["pending"]] == ["UMP0040"]

    # after that student signs in and the mirror writes, the same call reports no work left
    async def fixed():
        return _rows(("UMP0132", KNOWN), ("UMP0040", KNOWN))

    monkeypatch.setattr("routers.student_auth._sheet_students_rows", fixed)
    again = client.get("/api/student-auth/students/password-coverage?refresh=1", headers=mentor_headers).json()
    assert again["pending"] == [] and again["valid"] == 2 and again["usablePct"] == 100.0


def test_coverage_route_needs_a_mentor(client):
    assert client.get("/api/student-auth/students/password-coverage").status_code in (401, 403)
