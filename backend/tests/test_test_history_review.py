"""Mentor-only, per-student answer review for test submissions."""
import asyncio

from db import get_db


def _seed(*, tests=(), histories=(), attempts=(), answer_files=()):
    async def run():
        db = get_db()
        if tests:
            await db["mentor_tests"].insert_many(list(tests))
        if histories:
            await db["analytics_test_history"].insert_many(list(histories))
        if attempts:
            await db["student_mcq_attempts"].insert_many(list(attempts))
        if answer_files:
            await db["answer_sheet_files"].insert_many(list(answer_files))

    asyncio.run(run())


def test_submission_review_requires_mentor_auth(client):
    response = client.get(
        "/api/test-history/review",
        params={"student_id": "UMP0001", "test_id": "T-PAPER-1"},
    )
    assert response.status_code == 401


def test_paper_review_returns_student_scan_and_reference_materials(client, mentor_headers):
    _seed(
        tests=[{
            "testId": "T-PAPER-1",
            "kind": "paper-test",
            "title": "Audit paper",
            "subject": "Audit",
            "paper_url": "https://drive.google.com/file/d/question123/view",
            "answer_sheet_url": "https://drive.google.com/file/d/key123/view",
            "answer_sheet_text": "1. Independence in mind and appearance.",
            "marking_scheme": "Award 2 marks for each required point.",
            "instructions": "Attempt all questions.",
        }],
        histories=[{
            "studentId": "UMP0001",
            "studentName": "Aarav Sharma",
            "testId": "T-PAPER-1",
            "kind": "paper-test",
            "title": "Audit paper",
            "at": "2026-11-17T10:00:00Z",
            "score": 7,
            "total": 10,
            "scorePct": 70,
            "selfMarks": True,
            "remarks": "I was unsure about Q3.",
            "answerUrl": "/api/student-tests/answer-sheet/AS-12345-abcd1234",
        }],
        answer_files=[{
            "fileId": "AS-12345-abcd1234",
            "studentId": "UMP0001",
            "testId": "T-PAPER-1",
            "filename": "aarav-audit.pdf",
            "mimeType": "application/pdf",
            "createdAt": "2026-11-17T09:59:00Z",
            "data": "not returned in the review payload",
        }],
    )

    response = client.get(
        "/api/test-history/review",
        params={"student_id": "ump0001", "test_id": "T-PAPER-1"},
        headers=mentor_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["student"] == {"studentId": "UMP0001", "studentName": "Aarav Sharma"}
    assert data["submission"]["score"] == 7
    assert data["submission"]["answerUrl"] == "/api/student-tests/answer-sheet/AS-12345-abcd1234"
    assert data["test"]["questionPaperUrl"] == "https://drive.google.com/file/d/question123/view"
    assert data["test"]["answerSheetUrl"] == "https://drive.google.com/file/d/key123/view"
    assert data["test"]["answerSheetText"].startswith("1.")
    assert data["test"]["markingScheme"].startswith("Award 2")
    assert data["answerFileName"] == "aarav-audit.pdf"
    assert "data" not in data


def test_mcq_review_returns_saved_question_answers(client, mentor_headers):
    questions = [{
        "id": "Q1",
        "prompt": "Which is correct?",
        "options": ["Option A", "Option B"],
        "answer": 1,
        "selected": 0,
        "correct": False,
        "explanation": "Option B is correct.",
        "subject": "Audit",
        "chapter": "Ethics",
    }]
    _seed(
        tests=[{"testId": "T-MCQ-1", "kind": "mcq-test", "title": "MCQ quiz", "subject": "Audit"}],
        histories=[{
            "studentId": "UMP0002", "studentName": "Khushi", "testId": "T-MCQ-1",
            "kind": "mcq-test", "title": "MCQ quiz", "at": "2026-11-17T11:00:00Z",
            "score": 0, "total": 1, "scorePct": 0,
        }],
        attempts=[{
            "studentId": "UMP0002", "attemptId": "mentor-test:T-MCQ-1:UMP0002",
            "kind": "mentor-test", "review": questions,
        }],
    )

    response = client.get(
        "/api/test-history/review",
        params={"student_id": "UMP0002", "test_id": "T-MCQ-1"},
        headers=mentor_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["reviewAvailable"] is True
    assert data["mcqReview"] == questions
    assert data["submission"]["scorePct"] == 0


def test_review_does_not_return_foreign_student_files_or_untrusted_urls(client, mentor_headers):
    _seed(
        tests=[{
            "testId": "T-PAPER-2", "kind": "paper-test", "title": "Paper",
            "paper_url": "https://evil.example/question.pdf",
            "answer_sheet_url": "javascript:alert(1)",
        }],
        histories=[{
            "studentId": "UMP0003", "testId": "T-PAPER-2", "kind": "paper-test",
            "title": "Paper", "at": "2026-11-17T12:00:00Z", "score": 3, "total": 10,
            "answerUrl": "/api/student-tests/answer-sheet/AS-FOREIGN-1",
        }],
        answer_files=[{
            "fileId": "AS-FOREIGN-1", "studentId": "UMP9999", "testId": "T-PAPER-2",
            "filename": "other-student.pdf", "mimeType": "application/pdf", "data": "secret",
        }],
    )

    response = client.get(
        "/api/test-history/review",
        params={"student_id": "UMP0003", "test_id": "T-PAPER-2"},
        headers=mentor_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["submission"]["answerUrl"] == ""
    assert data["answerFileName"] == ""
    assert data["test"]["questionPaperUrl"] == ""
    assert data["test"]["answerSheetUrl"] == ""
