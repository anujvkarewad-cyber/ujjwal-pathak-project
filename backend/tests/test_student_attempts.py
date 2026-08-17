"""Completed MCQ attempt backup/restore with delegated student authentication."""
import pytest
from fastapi import HTTPException

from routers import student_attempts


@pytest.fixture(autouse=True)
def fake_student_login(monkeypatch):
    async def validate(student_id, password):
        if password != "secret":
            raise HTTPException(status_code=401, detail="Invalid Student ID or password")
        return {"success": True, "studentId": student_id, "studentName": "Test Student"}

    monkeypatch.setattr(student_attempts, "_validate_existing_student_login", validate)


def _daily(attempt_id="daily:2026-08-17:Group I"):
    return {
        "attemptId": attempt_id,
        "kind": "daily",
        "bankRevision": "published-r1",
        "date": "2026-08-17",
        "group": "Group I",
        "questionIds": ["q1", "q2"],
        "answers": {"q1": 0, "q2": 2},
        "startedAt": 1000,
        "completedAt": 2000,
        "score": 2,
        "total": 2,
        "durationSeconds": 60,
    }


def _practice():
    return {
        "attemptId": "practice:1234",
        "kind": "practice",
        "bankRevision": "published-r1",
        "config": {
            "group": "Combined",
            "subject": "All Subjects",
            "chapter": "All Chapters",
            "mode": "Mixed",
            "difficulty": "Mixed",
            "requestedCount": 2,
        },
        "questionIds": ["q3", "q4"],
        "answers": {"q3": 1},
        "startedAt": 3000,
        "completedAt": 4000,
        "score": 1,
        "total": 2,
        "durationSeconds": 90,
    }


def _sync_body(student_id="UMP0001", attempts=None, password="secret"):
    return {"studentId": student_id, "password": password, "attempts": attempts or []}


def _restore_body(student_id="UMP0001", password="secret"):
    return {"studentId": student_id, "password": password}


def test_completed_attempts_sync_restore_and_mentor_read(client, mentor_headers):
    response = client.post(
        "/api/student-attempts/sync",
        json=_sync_body(attempts=[_daily(), _practice()]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 2

    restored = client.post("/api/student-attempts/restore", json=_restore_body()).json()
    assert len(restored["daily"]) == 1
    assert len(restored["practice"]) == 1
    assert restored["daily"][0]["answers"] == {"q1": 0, "q2": 2}
    assert restored["practice"][0]["score"] == 1

    mentor = client.get(
        "/api/student-attempts/mentor?studentId=UMP0001",
        headers=mentor_headers,
    )
    assert mentor.status_code == 200
    assert len(mentor.json()["items"]) == 2


def test_attempts_are_isolated_by_student(client):
    client.post("/api/student-attempts/sync", json=_sync_body("UMP0001", [_daily()]))
    other = client.post("/api/student-attempts/restore", json=_restore_body("UMP0002"))
    assert other.status_code == 200
    assert other.json()["daily"] == []
    assert other.json()["practice"] == []


def test_sync_requires_valid_credentials_and_shape(client):
    denied = client.post(
        "/api/student-attempts/sync",
        json=_sync_body(attempts=[_daily()], password="wrong"),
    )
    assert denied.status_code == 401

    invalid = _daily()
    invalid["answers"]["q1"] = 8
    response = client.post(
        "/api/student-attempts/sync",
        json=_sync_body(attempts=[invalid]),
    )
    assert response.status_code == 422
