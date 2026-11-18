"""Per-student mentor remarks for test submissions."""
import asyncio

from fastapi import HTTPException

from db import (
    ANALYTICS_TEST_HISTORY,
    MENTOR_TEST_FEEDBACK,
    MENTOR_TESTS,
    STUDENT_ACCOUNTS,
    get_db,
)
from routers import student_tests


def _run(coro):
    return asyncio.run(coro)


def test_feedback_requires_mentor_auth_and_an_existing_submission(client, mentor_headers):
    payload = {"studentId": "UMP1001", "testId": "TEST-1", "remark": "Keep practicing."}
    assert client.post("/api/test-history/feedback", json=payload).status_code == 401

    response = client.post("/api/test-history/feedback", headers=mentor_headers, json=payload)
    assert response.status_code == 404


def test_mentor_remark_is_separate_from_student_self_evaluation_and_marks(client, mentor_headers):
    async def seed():
        db = get_db()
        await db[MENTOR_TESTS].insert_one({
            "testId": "PAPER-REMARK-1", "kind": "paper-test", "title": "Audit paper",
        })
        await db[ANALYTICS_TEST_HISTORY].insert_one({
            "id": "mentor-test:PAPER-REMARK-1:UMP1001",
            "studentId": "UMP1001", "studentName": "Aarav", "testId": "PAPER-REMARK-1",
            "kind": "paper-test", "title": "Audit paper", "score": 7, "total": 10,
            "remarks": "I was unsure about Q3.", "selfMarks": True,
        })

    _run(seed())
    saved = client.post("/api/test-history/feedback", headers=mentor_headers, json={
        "studentId": "ump1001", "testId": "PAPER-REMARK-1", "remark": "Good work. Review Q3 again.",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["studentId"] == "UMP1001"
    assert saved.json()["remark"] == "Good work. Review Q3 again."

    review = client.get("/api/test-history/review", headers=mentor_headers, params={
        "student_id": "UMP1001", "test_id": "PAPER-REMARK-1",
    })
    assert review.status_code == 200, review.text
    assert review.json()["mentorFeedback"]["remark"] == "Good work. Review Q3 again."
    assert review.json()["submission"]["remarks"] == "I was unsure about Q3."
    assert review.json()["submission"]["score"] == 7

    async def read_records():
        db = get_db()
        history = await db[ANALYTICS_TEST_HISTORY].find_one({"studentId": "UMP1001", "testId": "PAPER-REMARK-1"})
        feedback = await db[MENTOR_TEST_FEEDBACK].find_one({"studentId": "UMP1001", "testId": "PAPER-REMARK-1"})
        return history, feedback

    history, feedback = _run(read_records())
    assert history["remarks"] == "I was unsure about Q3."
    assert history["score"] == 7 and history["total"] == 10
    assert feedback["remark"] == "Good work. Review Q3 again."

    cleared = client.post("/api/test-history/feedback", headers=mentor_headers, json={
        "studentId": "UMP1001", "testId": "PAPER-REMARK-1", "remark": "  ",
    })
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["remark"] == ""
    review_after_clear = client.get("/api/test-history/review", headers=mentor_headers, params={
        "student_id": "UMP1001", "test_id": "PAPER-REMARK-1",
    })
    assert review_after_clear.json()["mentorFeedback"]["remark"] == ""


def test_student_only_receives_their_own_test_remark_in_list_and_paper(client, monkeypatch):
    allowed = {"UMP1001": "pass-one", "UMP1002": "pass-two"}

    async def validate(student_id, password):
        if allowed.get(student_id) != password:
            raise HTTPException(status_code=401, detail="Invalid student login")
        return {"studentId": student_id, "success": True}

    monkeypatch.setattr(student_tests, "_validate_existing_student_login", validate)

    async def seed():
        db = get_db()
        await db[STUDENT_ACCOUNTS].insert_many([
            {"studentId": "UMP1001", "studentName": "Student One", "batch": "B1", "group": "Group 1", "accessEnabled": True},
            {"studentId": "UMP1002", "studentName": "Student Two", "batch": "B1", "group": "Group 1", "accessEnabled": True},
        ])
        await db[MENTOR_TESTS].insert_one({
            "testId": "REMARK-SCOPE-1", "published": True, "kind": "paper-test", "title": "Paper",
            "batch": "B1", "group": "Group 1", "total_marks": 10,
        })
        await db[MENTOR_TEST_FEEDBACK].insert_many([
            {"studentId": "UMP1001", "testId": "REMARK-SCOPE-1", "remark": "Private note for one."},
            {"studentId": "UMP1002", "testId": "REMARK-SCOPE-1", "remark": "Private note for two."},
        ])

    _run(seed())
    one = client.post("/api/student-tests/list", json={"studentId": "UMP1001", "password": "pass-one"})
    two = client.post("/api/student-tests/list", json={"studentId": "UMP1002", "password": "pass-two"})
    assert one.status_code == two.status_code == 200
    one_test = next(row for row in one.json()["tests"] if row["testId"] == "REMARK-SCOPE-1")
    two_test = next(row for row in two.json()["tests"] if row["testId"] == "REMARK-SCOPE-1")
    assert one_test["mentorRemark"] == "Private note for one."
    assert two_test["mentorRemark"] == "Private note for two."

    one_paper = client.post("/api/student-tests/paper", json={
        "studentId": "UMP1001", "password": "pass-one", "testId": "REMARK-SCOPE-1",
    })
    two_paper = client.post("/api/student-tests/paper", json={
        "studentId": "UMP1002", "password": "pass-two", "testId": "REMARK-SCOPE-1",
    })
    assert one_paper.status_code == two_paper.status_code == 200
    assert one_paper.json()["test"]["mentorRemark"] == "Private note for one."
    assert two_paper.json()["test"]["mentorRemark"] == "Private note for two."
