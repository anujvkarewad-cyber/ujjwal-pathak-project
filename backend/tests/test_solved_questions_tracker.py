import asyncio
from datetime import datetime, timedelta

from db import DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db
from routers import attendance as attendance_lib
from routers import student_dashboard
from routers.student_auth import StudentImportItem, upsert_student_account
from routers.student_dashboard import (
    IST,
    SOLVED_QUESTION_SUBJECTS,
    _normalize_solved_questions,
    _resolve_mentor_proof_url,
)


def _seed_cohort():
    async def _run():
        db = get_db()
        for row in (
            {
                "studentId": "UMP1001",
                "studentName": "Aarav G1",
                "password": "Pass@1001",
                "attempt": "Jan 2027",
                "batch": "Last 25 days planner batch",
                "group": "Group 1",
                "joinedOn": "2026-10-01",
            },
            {
                "studentId": "UMP1002",
                "studentName": "Bhavya G2",
                "password": "Pass@1002",
                "attempt": "Jan 2027",
                "batch": "Last 25 days planner batch",
                "group": "Group 2",
                "joinedOn": "2026-10-01",
            },
            {
                "studentId": "UMP1003",
                "studentName": "Charu Both",
                "password": "Pass@1003",
                "attempt": "Jan 2027",
                "batch": "Last 25 days planner batch",
                "group": "Both Groups",
                "joinedOn": "2026-10-01",
            },
            {
                "studentId": "UMP1004",
                "studentName": "Dev Leave",
                "password": "Pass@1004",
                "attempt": "Jan 2027",
                "batch": "Last 25 days planner batch",
                "group": "Group 1",
                "joinedOn": "2026-10-01",
            },
        ):
            await upsert_student_account(StudentImportItem(**row))
        await db[STUDENT_ACCOUNTS].insert_one(
            {
                "studentId": "UMP1005",
                "studentName": "Blocked Student",
                "attempt": "Jan 2027",
                "batch": "Last 25 days planner batch",
                "group": "Group 1",
                "accessEnabled": False,
            }
        )

    asyncio.run(_run())


def test_canonical_eight_subjects_keep_dt_and_gst_separate():
    assert SOLVED_QUESTION_SUBJECTS == (
        "Accounts",
        "Law",
        "DT",
        "GST",
        "Costing",
        "Audit",
        "FM",
        "SM",
    )
    normalized = _normalize_solved_questions(
        [
            {"subject": "Direct Tax", "count": 14, "sheetName": "PGBP Sheet 2", "proofUrl": "/api/proof-file?fileId=abc123XYZ"},
            {"subject": "GST", "count": 9, "sheetName": "ITC Sheet 1"},
            {"subject": "Accounts", "count": 6},
            {"subject": "Revision", "count": 99},
        ]
    )
    assert list(normalized.keys()) == ["Accounts", "DT", "GST"]
    assert normalized["DT"]["count"] == 14
    assert normalized["DT"]["sheetName"] == "PGBP Sheet 2"
    assert normalized["GST"]["count"] == 9
    assert _resolve_mentor_proof_url("/api/proof-file?fileId=abc123XYZ") == "https://drive.google.com/file/d/abc123XYZ/view"


def test_student_write_persists_subject_wise_solved_questions_and_updates_same_day(client, mentor_headers, monkeypatch):
    _seed_cohort()
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", lambda: [])
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_roster_sync", lambda: [])
    today = datetime.now(IST).date().isoformat()

    student_headers = {
        "X-Student-Id": "UMP1001",
        "X-Session-Password": "Pass@1001",
    }

    # First submission: DT=10, GST=8
    res1 = client.post(
        "/api/student-dashboard/write",
        headers=student_headers,
        json={
            "action": "addStudyLog",
            "payload": {
                "studentId": "UMP1001",
                "date": today,
                "hours": 5.0,
                "studiedAsPlanned": "Yes",
                "subjects": "DT, GST",
                "targetCompleted": "Yes",
                "tomorrowTarget": "Accounts Ch 3",
                "proofUrl": "/api/proof-file?fileId=sheetFileOne123",
                "solvedQuestions": [
                    {"subject": "DT", "count": 10, "sheetName": "DT Sheet 1"},
                    {"subject": "GST", "count": 8, "sheetName": "GST Sheet 1"},
                ],
            },
        },
    )
    assert res1.status_code == 200, res1.text
    body1 = res1.json()["result"]
    assert body1["success"] is True
    assert body1["totalSolved"] == 18

    # Second submission same day with updated hours & DT=15 (must NOT double count 10+15=25)
    res2 = client.post(
        "/api/student-dashboard/write",
        headers=student_headers,
        json={
            "action": "addStudyLog",
            "payload": {
                "studentId": "UMP1001",
                "date": today,
                "hours": 6.5,
                "studiedAsPlanned": "Yes",
                "subjects": "DT, GST",
                "targetCompleted": "Yes",
                "proofUrl": "/api/proof-file?fileId=sheetFileTwo456",
                "solvedQuestions": [
                    {"subject": "DT", "count": 15, "sheetName": "DT Sheet 1+2", "proofUrl": "/api/proof-file?fileId=dtSpecific789"},
                    {"subject": "GST", "count": 8, "sheetName": "GST Sheet 1"},
                ],
            },
        },
    )
    assert res2.status_code == 200, res2.text

    # Student reads own study log back
    read_res = client.post(
        "/api/student-dashboard/get",
        headers=student_headers,
        json={"action": "getStudyLog", "payload": {"studentId": "UMP1001"}},
    )
    assert read_res.status_code == 200
    logs = read_res.json()["result"]
    assert logs[0]["totalSolved"] == 23
    assert logs[0]["solvedQuestions"]["DT"]["count"] == 15

    # Leave for UMP1004 today; hours-only log (old APK style) for UMP1002
    asyncio.run(
        attendance_lib.request_leave(get_db(), "UMP1004", today, today, "Family function", "student")
    )
    asyncio.run(
        get_db()[DASHBOARD_STUDENTS].insert_one(
            {
                "studentId": "UMP1002",
                "studyLog": [{"date": today, "hours": 4.0, "topic": "Costing", "proof": "https://example.test/cost-proof.pdf"}],
            }
        )
    )

    # Mentor solved-questions-report (All Subjects)
    rep = client.get(
        f"/api/student-dashboard/solved-questions-report?from={today}&to={today}",
        headers=mentor_headers,
    )
    assert rep.status_code == 200, rep.text
    report = rep.json()
    assert report["summary"]["expectedCount"] == 4  # UMP1005 is access-off
    assert report["summary"]["submittedSolvedCount"] == 1  # UMP1001
    assert report["summary"]["loggedOnlyCount"] == 1  # UMP1002
    assert report["summary"]["excusedCount"] == 1  # UMP1004 on leave
    assert report["summary"]["notSubmittedCount"] == 1  # UMP1003 missed
    assert report["summary"]["totalQuestionsSolved"] == 23

    by_id = {item["studentId"]: item for item in report["items"]}
    assert by_id["UMP1001"]["status"] == "submitted"
    assert by_id["UMP1001"]["bySubject"]["DT"] == 15
    assert by_id["UMP1001"]["bySubject"]["GST"] == 8
    assert by_id["UMP1001"]["latestMentorProofUrl"] == "https://drive.google.com/file/d/sheetFileTwo456/view"
    assert any(
        s["subject"] == "DT" and s["mentorProofUrl"] == "https://drive.google.com/file/d/dtSpecific789/view"
        for s in by_id["UMP1001"]["sheets"]
    )
    assert by_id["UMP1002"]["status"] == "logged_only"
    assert by_id["UMP1003"]["status"] == "not_submitted"
    assert by_id["UMP1004"]["status"] == "leave"

    # Subject-specific filter: DT -> excludes Group 2-only UMP1002 so they aren't falsely flagged
    dt_rep = client.get(
        f"/api/student-dashboard/solved-questions-report?from={today}&to={today}&subject=DT",
        headers=mentor_headers,
    )
    assert dt_rep.status_code == 200, dt_rep.text
    dt_ids = {item["studentId"]: item["status"] for item in dt_rep.json()["items"]}
    assert "UMP1002" not in dt_ids
    assert dt_ids["UMP1001"] == "submitted"
    assert dt_ids["UMP1003"] == "not_submitted"
    assert dt_ids["UMP1004"] == "leave"


def test_multi_day_aggregation_and_mentor_reminder(client, mentor_headers, monkeypatch):
    _seed_cohort()
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", lambda: [])
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_roster_sync", lambda: [])
    today = datetime.now(IST).date()
    yesterday = today - timedelta(days=1)

    async def _seed_two_days():
        await get_db()[DASHBOARD_STUDENTS].insert_one(
            {
                "studentId": "UMP1003",
                "studyLog": [
                    {
                        "date": today.isoformat(),
                        "hours": 5,
                        "topic": "DT, Costing",
                        "proof": "",
                        "solvedQuestions": {"DT": {"count": 12}, "Costing": {"count": 7}},
                        "totalSolved": 19,
                    },
                    {
                        "date": yesterday.isoformat(),
                        "hours": 4,
                        "topic": "DT, Audit",
                        "proof": "",
                        "solvedQuestions": {"DT": {"count": 8}, "Audit": {"count": 5}},
                        "totalSolved": 13,
                    },
                ],
            }
        )

    asyncio.run(_seed_two_days())

    rep = client.get(
        f"/api/student-dashboard/solved-questions-report?from={yesterday.isoformat()}&to={today.isoformat()}",
        headers=mentor_headers,
    )
    assert rep.status_code == 200, rep.text
    by_id = {item["studentId"]: item for item in rep.json()["items"]}
    assert by_id["UMP1003"]["bySubject"]["DT"] == 20
    assert by_id["UMP1003"]["bySubject"]["Costing"] == 7
    assert by_id["UMP1003"]["bySubject"]["Audit"] == 5
    assert by_id["UMP1003"]["totalSolved"] == 32

    # Mentor sends reminder to non-submitters (UMP1001, UMP1002, and access-off UMP1005 which must be skipped)
    rem = client.post(
        "/api/student-dashboard/solved-questions-remind",
        headers=mentor_headers,
        json={
            "studentIds": ["UMP1001", "UMP1002", "UMP1005"],
            "date": today.isoformat(),
            "subject": "DT",
        },
    )
    assert rem.status_code == 200, rem.text
    rem_body = rem.json()
    assert rem_body["ok"] is True
    assert rem_body["remindedCount"] == 2
    assert set(rem_body["studentIds"]) == {"UMP1001", "UMP1002"}

    # Verify in-app feedback was recorded for UMP1001
    fb_res = client.post(
        "/api/student-dashboard/get",
        headers={"X-Student-Id": "UMP1001", "X-Session-Password": "Pass@1001"},
        json={"action": "getStudentFeedback", "payload": {"studentId": "UMP1001"}},
    )
    assert fb_res.status_code == 200
    feedback_items = fb_res.json()["result"]
    assert len(feedback_items) == 1
    assert "DT" in feedback_items[0]["message"]
