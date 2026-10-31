"""Tests for the answer-sheet upload + retrieval endpoints
(POST /api/student-tests/upload, GET /api/student-tests/answer-sheet/{file_id}).

These replace the dead Apps Script `student.test.uploadSubmission` action
that paper-test students previously used.
"""
import base64
import asyncio

from db import MENTOR_TESTS, get_db


def _seed_paper_test(test_id="PAPER-001"):
    async def _do():
        db = get_db()
        await db[MENTOR_TESTS].insert_one({
            "testId": test_id,
            "title": "Mock Test 1",
            "subject": "Accounts",
            "kind": "paper-test",
            "published": True,
            "total_marks": 100,
            "question_count": 0,
            "chapters": [],
            "batch": "",
            "group": "",
        })
    asyncio.run(_do())


def _seed_student(client, mentor_headers, student_id, password, name="Test Student"):
    """Import a student via the existing mentor endpoint."""
    res = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={
            "students": [
                {
                    "studentId": student_id.lower(),
                    "password": password,
                    "studentName": name,
                    "email": f"{student_id.lower()}@test.local",
                    "attempt": "Jan 2027",
                    "batch": "Super 30",
                    "passwordChanged": "No",
                }
            ]
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["upserted"] == 1


def test_upload_and_retrieve_answer_sheet(client, mentor_headers):
    """Full flow: seed test + student, upload a PDF, retrieve it back."""
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0001", "test-pass-123")

    pdf_bytes = b"%PDF-1.4\n%fake pdf content for testing\n%%EOF"
    b64 = base64.b64encode(pdf_bytes).decode("ascii")

    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0001",
        "password": "test-pass-123",
        "testId": "PAPER-001",
        "base64": b64,
        "mimeType": "application/pdf",
        "filename": "my-answers.pdf",
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["fileId"].startswith("AS-")
    assert "/api/student-tests/answer-sheet/" in data["url"]

    # Retrieve as student (own file)
    file_id = data["fileId"]
    res2 = client.get(f"/api/student-tests/answer-sheet/{file_id}", headers={
        "X-Student-Id": "UMP0001",
        "X-Session-Password": "test-pass-123",
    })
    assert res2.status_code == 200, res2.text
    assert res2.content == pdf_bytes
    assert res2.headers["content-type"] == "application/pdf"
    assert "my-answers.pdf" in res2.headers["content-disposition"]


def test_upload_rejects_wrong_password(client, mentor_headers):
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0002", "correct-pass")

    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0002",
        "password": "wrong-password",
        "testId": "PAPER-001",
        "base64": base64.b64encode(b"data").decode(),
        "mimeType": "application/pdf",
        "filename": "x.pdf",
    })
    assert res.status_code == 401


def test_upload_rejects_unknown_test(client, mentor_headers):
    _seed_student(client, mentor_headers, "UMP0003", "pass-123")

    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0003",
        "password": "pass-123",
        "testId": "NO-SUCH-TEST",
        "base64": base64.b64encode(b"data").decode(),
        "mimeType": "application/pdf",
        "filename": "x.pdf",
    })
    assert res.status_code == 404


def test_upload_rejects_bad_mime(client, mentor_headers):
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0004", "pass-123")

    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0004",
        "password": "pass-123",
        "testId": "PAPER-001",
        "base64": base64.b64encode(b"data").decode(),
        "mimeType": "application/exe",
        "filename": "virus.exe",
    })
    assert res.status_code == 415


def test_retrieve_requires_auth(client, mentor_headers):
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0005", "pass-123")

    # Upload first
    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0005",
        "password": "pass-123",
        "testId": "PAPER-001",
        "base64": base64.b64encode(b"data").decode(),
        "mimeType": "application/pdf",
        "filename": "x.pdf",
    })
    assert res.status_code == 200
    file_id = res.json()["fileId"]

    # No auth → 401
    res2 = client.get(f"/api/student-tests/answer-sheet/{file_id}")
    assert res2.status_code == 401

    # Wrong student → 403
    res3 = client.get(f"/api/student-tests/answer-sheet/{file_id}", headers={
        "X-Student-Id": "UMP9999",
        "X-Session-Password": "pass-123",
    })
    assert res3.status_code == 403


def test_retrieve_as_mentor(client, mentor_headers):
    """Mentor JWT can retrieve any answer sheet."""
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0006", "pass-123")

    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0006",
        "password": "pass-123",
        "testId": "PAPER-001",
        "base64": base64.b64encode(b"mentor-view-data").decode(),
        "mimeType": "application/pdf",
        "filename": "x.pdf",
    })
    assert res.status_code == 200
    file_id = res.json()["fileId"]

    res2 = client.get(f"/api/student-tests/answer-sheet/{file_id}", headers=mentor_headers)
    assert res2.status_code == 200
    assert res2.content == b"mentor-view-data"


def test_retrieve_unknown_file(client, mentor_headers):
    res = client.get("/api/student-tests/answer-sheet/AS-NOPE", headers=mentor_headers)
    assert res.status_code == 404


def test_upload_rejects_oversized_file(client, mentor_headers):
    _seed_paper_test()
    _seed_student(client, mentor_headers, "UMP0007", "pass-123")

    # 11 MB of data → exceeds the 10 MB limit
    big = b"x" * (11 * 1024 * 1024)
    res = client.post("/api/student-tests/upload", json={
        "studentId": "UMP0007",
        "password": "pass-123",
        "testId": "PAPER-001",
        "base64": base64.b64encode(big).decode(),
        "mimeType": "application/pdf",
        "filename": "big.pdf",
    })
    assert res.status_code == 413
