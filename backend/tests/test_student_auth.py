"""Mongo-backed student login."""
from routers.student_auth import upsert_student_account, StudentImportItem


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

    changed = client.post(
        "/api/student-auth/change-password",
        json={"studentId": "UMP0001", "currentPassword": "UPM2026@001", "newPassword": "NewPass#1"},
    )
    assert changed.json()["result"]["success"] is True
    old = client.post("/api/student-auth/login", json={"studentId": "UMP0001", "password": "UPM2026@001"})
    assert old.json()["result"]["success"] is False
    new = client.post("/api/student-auth/login", json={"studentId": "UMP0001", "password": "NewPass#1"})
    assert new.json()["result"]["success"] is True


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
