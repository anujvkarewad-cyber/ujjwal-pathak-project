"""Mongo-backed student login."""
from datetime import date

from routers.student_auth import (
    StudentImportItem,
    _attempt_access_allowed,
    _attempt_ym,
    upsert_student_account,
)


def test_attempt_access_accepts_google_sheet_date_strings():
    jan = "Fri Jan 01 2027 00:00:00 GMT+0530 (India Standard Time)"
    may = "Sat May 01 2027 00:00:00 GMT+0530 (India Standard Time)"

    assert _attempt_ym(jan) == (2027, 1)
    assert _attempt_ym(may) == (2027, 5)
    assert _attempt_access_allowed(jan, today=date(2027, 1, 20)) is True
    assert _attempt_access_allowed(jan, today=date(2027, 1, 21)) is False
    assert _attempt_access_allowed(may, today=date(2027, 1, 21)) is True


def test_attempt_access_still_rejects_old_or_missing_attempts():
    assert _attempt_access_allowed("Sep 2026") is False
    assert _attempt_access_allowed("") is False


def test_student_login_roundtrip(client, mentor_headers):
    imported = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={
            "students": [
                {
                    "studentId": "ump1",
                    "password": "UPM2026@001",
                    "studentName": "Test Student",
                    "email": "a@test.local",
                    "attempt": "Jan 2027",
                    "batch": "Super 30",
                    "passwordChanged": "Yes",
                }
            ]
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["upserted"] == 1

    missed = client.post("/api/student-auth/login", json={"studentId": "UMP0001", "password": "nope"})
    assert missed.status_code == 200
    assert missed.json()["result"]["success"] is False
    assert missed.json()["result"]["code"] == "wrong_password"

    missing = client.post("/api/student-auth/login", json={"studentId": "UMP9999", "password": "x"})
    assert missing.json()["result"]["code"] == "not_found"

    ok = client.post(
        "/api/student-auth/login",
        json={"action": "validateLogin", "payload": {"studentId": "UMP0001", "password": "UPM2026@001"}},
    )
    assert ok.status_code == 200, ok.text
    result = ok.json()["result"]
    assert result["success"] is True
    assert result["studentId"] == "UMP0001"
    assert result["studentName"] == "Test Student"
    assert result["forcePasswordChange"] is False

    # A mentor reset can force one account to change its password even when a
    # later sheet import still says Password Changed = Yes. The override must
    # survive imports and clear only after the student changes the password.
    import asyncio
    from db import STUDENT_ACCOUNTS, get_db

    asyncio.run(
        get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": "UMP0001"},
            {"$set": {"forcePasswordChange": True}},
        )
    )
    forced = client.post(
        "/api/student-auth/login",
        json={"studentId": "UMP0001", "password": "UPM2026@001"},
    )
    assert forced.json()["result"]["success"] is True
    assert forced.json()["result"]["forcePasswordChange"] is True

    changed = client.post(
        "/api/student-auth/change-password",
        json={"studentId": "UMP0001", "currentPassword": "UPM2026@001", "newPassword": "NewPass#1"},
    )
    assert changed.json()["result"]["success"] is True
    old = client.post("/api/student-auth/login", json={"studentId": "UMP0001", "password": "UPM2026@001"})
    assert old.json()["result"]["success"] is False
    new = client.post("/api/student-auth/login", json={"studentId": "UMP0001", "password": "NewPass#1"})
    assert new.json()["result"]["success"] is True
    assert new.json()["result"]["forcePasswordChange"] is False


def test_trusted_import_requires_explicit_force_to_reset_changed_password(client, mentor_headers):
    original = {
        "studentId": "UMP0044",
        "password": "StudentChosen#1",
        "studentName": "Recovery Test",
        "email": "recovery@test.local",
        "attempt": "May 2027",
        "passwordChanged": True,
    }
    created = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={"students": [original]},
    )
    assert created.status_code == 200

    # A normal Sheet sync must not overwrite a password the student chose.
    sheet_sync = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={"students": [{**original, "password": "StaleSheet#1", "passwordChanged": False}]},
    )
    assert sheet_sync.status_code == 200
    still_original = client.post(
        "/api/student-auth/login",
        json={"studentId": "UMP0044", "password": "StudentChosen#1"},
    ).json()["result"]
    assert still_original["success"] is True

    # After an OTP has been verified, the trusted reset service opts in to
    # replacing the existing hash. The new password is final, not temporary.
    recovery = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={
            "students": [{
                **original,
                "password": "Recovered#2",
                "passwordChanged": True,
                "forcePasswordReset": True,
            }]
        },
    )
    assert recovery.status_code == 200
    old = client.post(
        "/api/student-auth/login",
        json={"studentId": "UMP0044", "password": "StudentChosen#1"},
    ).json()["result"]
    assert old["success"] is False
    new = client.post(
        "/api/student-auth/login",
        json={"studentId": "UMP0044", "password": "Recovered#2"},
    ).json()["result"]
    assert new["success"] is True
    assert new["forcePasswordChange"] is False


def test_import_requires_auth(client):
    denied = client.post(
        "/api/student-auth/import",
        json={"students": [{"studentId": "UMP0002", "password": "secret12"}]},
    )
    assert denied.status_code == 401


def test_upsert_helper_and_status(client, mentor_headers):
    import asyncio

    asyncio.run(
        upsert_student_account(
            StudentImportItem(studentId="UMP0003", password="abc12345", studentName="C")
        )
    )
    status = client.get("/api/student-auth/status")
    assert status.status_code == 200
    assert status.json()["accounts"] >= 1
