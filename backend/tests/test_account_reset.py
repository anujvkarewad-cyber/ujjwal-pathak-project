"""Emergency four-account reset (UMP0043 / UMP0081 / UMP0088 / UMP0090).

Contract under test:
  * exactly those four accounts are reset to their Sheet password,
  * the student is forced to change the password on first login,
  * every other field of the account and every other account is untouched,
  * the migration marker makes repeat runs a no-op (idempotent).
"""
import asyncio

import pytest

from account_reset import (
    MARKER_KEY,
    RESET_STUDENT_IDS,
    parse_sheet_passwords,
    reset_accounts,
)
from auth import hash_password
from db import MIGRATIONS, STUDENT_ACCOUNTS, get_db

SHEET_PASSWORDS = {
    "UMP0043": "UPM2026@043",
    "UMP0081": "UPM2026@081",
    "UMP0088": "UPM2026@088",
    "UMP0090": "UPM2026@090",
}


def _account(student_id: str, password_hash: str, **extra) -> dict:
    doc = {
        "studentId": student_id,
        "studentName": f"Student {student_id}",
        "email": f"{student_id.lower()}@example.com",
        "caLevel": "Final",
        "group": "Group 1",
        "attempt": "May 2027",
        "batch": "Batch A",
        "phone": "9876543210",
        "address": "Patna",
        "joinedOn": "2026-01-15",
        "whatsapp": "9876543210",
        "passwordHash": password_hash,
        "passwordChanged": True,
        "createdAt": "2026-01-15T00:00:00+00:00",
    }
    doc.update(extra)
    return doc


async def _seed_accounts():
    db = get_db()
    for sid in RESET_STUDENT_IDS:
        await db[STUDENT_ACCOUNTS].insert_one(_account(sid, hash_password("stale-unknown-hash")))
    # A control account that must never be touched by the reset.
    await db[STUDENT_ACCOUNTS].insert_one(_account("UMP0001", hash_password("ControlPass#1")))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


@pytest.fixture
def seeded():
    _run(_seed_accounts())


def _login(client, student_id, password):
    return client.post(
        "/api/student-auth/login", json={"studentId": student_id, "password": password}
    ).json()["result"]


# ── password source parsing ───────────────────────────────────────────────

def test_parse_sheet_passwords_accepts_json_and_pairs():
    assert parse_sheet_passwords('{"UMP43": "a", "ump0081": "b"}') == {"UMP0043": "a", "UMP0081": "b"}
    assert parse_sheet_passwords("UMP0088:c, UMP0090:d") == {"UMP0088": "c", "UMP0090": "d"}
    assert parse_sheet_passwords("") == {}
    assert parse_sheet_passwords("not-json{") == {}


# ── the reset itself ──────────────────────────────────────────────────────

def test_reset_restores_sheet_password_and_forces_change(client, seeded):
    summary = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert summary["applied"] is True
    assert {a["studentId"] for a in summary["accounts"]} == set(RESET_STUDENT_IDS)
    assert all(a["status"] == "reset" for a in summary["accounts"])
    assert all(a["mode"] == "sheet_password_applied" for a in summary["accounts"])

    for sid, pwd in SHEET_PASSWORDS.items():
        result = _login(client, sid, pwd)
        assert result["success"] is True, (sid, result)
        assert result["forcePasswordChange"] is True
        assert _login(client, sid, "stale-unknown-hash")["success"] is False


def test_reset_preserves_every_other_field(seeded):
    _run(reset_accounts(passwords=SHEET_PASSWORDS))
    db = get_db()
    doc = _run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0043"}))
    assert doc["studentName"] == "Student UMP0043"
    assert doc["email"] == "ump0043@example.com"
    assert doc["caLevel"] == "Final"
    assert doc["group"] == "Group 1"
    assert doc["attempt"] == "May 2027"
    assert doc["batch"] == "Batch A"
    assert doc["phone"] == "9876543210"
    assert doc["address"] == "Patna"
    assert doc["joinedOn"] == "2026-01-15"
    assert doc["whatsapp"] == "9876543210"
    assert doc["createdAt"] == "2026-01-15T00:00:00+00:00"
    assert "password" not in doc


def test_reset_does_not_touch_other_accounts(client, seeded):
    _run(reset_accounts(passwords=SHEET_PASSWORDS))
    control = _login(client, "UMP0001", "ControlPass#1")
    assert control["success"] is True
    assert control["forcePasswordChange"] is False


def test_student_can_set_a_new_password_after_reset(client, seeded):
    _run(reset_accounts(passwords=SHEET_PASSWORDS))
    res = client.post(
        "/api/student-auth/change-password",
        json={
            "studentId": "UMP0081",
            "currentPassword": SHEET_PASSWORDS["UMP0081"],
            "newPassword": "ChosenPass#9",
        },
    ).json()["result"]
    assert res["success"] is True
    after = _login(client, "UMP0081", "ChosenPass#9")
    assert after["success"] is True
    assert after["forcePasswordChange"] is False
    assert _login(client, "UMP0081", SHEET_PASSWORDS["UMP0081"])["success"] is False


# ── idempotency ───────────────────────────────────────────────────────────

def test_marker_written_once_and_second_run_is_a_noop(client, seeded):
    first = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert first["applied"] is True

    # Student picks their own password after the reset.
    client.post(
        "/api/student-auth/change-password",
        json={
            "studentId": "UMP0088",
            "currentPassword": SHEET_PASSWORDS["UMP0088"],
            "newPassword": "MyOwnPass#7",
        },
    )

    second = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert second["applied"] is False
    assert second["skipped"] is True
    assert second["reason"] == "already_applied"
    assert second["appliedAt"] == first["appliedAt"]

    # The redeploy must NOT knock the student back to the Sheet password.
    assert _login(client, "UMP0088", "MyOwnPass#7")["success"] is True
    assert _login(client, "UMP0088", SHEET_PASSWORDS["UMP0088"])["success"] is False

    db = get_db()
    markers = _run(db[MIGRATIONS].count_documents({"key": MARKER_KEY}))
    assert markers == 1


def test_force_reruns_the_reset(client, seeded):
    _run(reset_accounts(passwords=SHEET_PASSWORDS))
    client.post(
        "/api/student-auth/change-password",
        json={
            "studentId": "UMP0090",
            "currentPassword": SHEET_PASSWORDS["UMP0090"],
            "newPassword": "Temporary#1",
        },
    )
    again = _run(reset_accounts(passwords=SHEET_PASSWORDS, force=True))
    assert again["applied"] is True
    assert _login(client, "UMP0090", SHEET_PASSWORDS["UMP0090"])["success"] is True


# ── no-secret fallback: hand password authority back to the Students sheet ──

def test_without_supplied_passwords_account_awaits_sheet_resync(client, seeded, monkeypatch):
    monkeypatch.delenv("ACCOUNT_RESET_SHEET_PASSWORDS", raising=False)
    summary = _run(reset_accounts())
    assert all(a["mode"] == "awaiting_sheet_resync" for a in summary["accounts"])

    db = get_db()
    doc = _run(db[STUDENT_ACCOUNTS].find_one({"studentId": "UMP0043"}))
    assert doc["sheetPasswordResyncPending"] is True
    assert doc["passwordChanged"] is False
    assert doc["forcePasswordChange"] is True

    # The next Students-sheet import re-applies the Sheet password.
    res = client.post(
        "/api/student-auth/import",
        json={
            "students": [
                {
                    "studentId": "UMP0043",
                    "password": SHEET_PASSWORDS["UMP0043"],
                    "studentName": "Student UMP0043",
                    "attempt": "May 2027",
                }
            ]
        },
        headers={"X-UMP-Import": ""},
    )
    # Import requires mentor auth or the import key; use the direct helper when
    # the endpoint is protected in this environment.
    if res.status_code != 200:
        from routers.student_auth import StudentImportItem, upsert_student_account

        _run(
            upsert_student_account(
                StudentImportItem(
                    studentId="UMP0043",
                    password=SHEET_PASSWORDS["UMP0043"],
                    studentName="Student UMP0043",
                    attempt="May 2027",
                )
            )
        )

    login = _login(client, "UMP0043", SHEET_PASSWORDS["UMP0043"])
    assert login["success"] is True
    assert login["forcePasswordChange"] is True


# ── missing account is reported, never created ────────────────────────────

def test_missing_account_is_reported_not_created():
    summary = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert all(a["status"] == "not_found" for a in summary["accounts"])
    db = get_db()
    assert _run(db[STUDENT_ACCOUNTS].count_documents({})) == 0


def test_boot_before_accounts_exist_does_not_burn_the_marker(client):
    """A boot that finds no target account must stay retryable."""
    early = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert early["applied"] is False
    assert early["reason"] == "no_accounts_found"
    db = get_db()
    assert _run(db[MIGRATIONS].count_documents({"key": MARKER_KEY})) == 0

    # Accounts arrive later (Students-sheet import) → the reset still runs.
    _run(_seed_accounts())
    later = _run(reset_accounts(passwords=SHEET_PASSWORDS))
    assert later["applied"] is True
    assert _login(client, "UMP0043", SHEET_PASSWORDS["UMP0043"])["success"] is True
