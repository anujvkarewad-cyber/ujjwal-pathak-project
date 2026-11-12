"""Mentor dashboard analytics must use live tracker/activity records, not stale stats."""
import asyncio
from datetime import date, datetime, timedelta, timezone


def test_dashboard_metrics_derive_from_tracker_rows_and_today_activity():
    from routers.student_dashboard import _dashboard_kpis_from_tracker

    today = date(2026, 11, 9)
    first_expected = today - timedelta(days=28)
    accounts = [
        {
            "studentId": "UMP0001",
            "studentName": "Asha",
            "batch": "Batch A",
            "joinedOn": (first_expected - timedelta(days=1)).isoformat(),
        },
        {
            "studentId": "UMP0002",
            "studentName": "Bina",
            "batch": "Batch A",
            "joinedOn": (today - timedelta(days=1)).isoformat(),
        },
        {
            "studentId": "UMP0003",
            "studentName": "Chirag",
            "batch": "Batch B",
            "joinedOn": "2026-10-01",
            "accessEnabled": False,
        },
        {"studentId": "UMP0004", "status": "removed", "studentName": "Removed"},
    ]

    rows = []
    for offset in range(29):
        day = first_expected + timedelta(days=offset)
        rows.extend([
            {"studentId": "UMP0001", "date": day, "hours": 1, "source": "mongo"},
            # Two form entries are summed, then reconciled against Mongo's daily
            # total instead of double-counting the mirrored tracker submission.
            {"studentId": "UMP0001", "date": day, "hours": 0.5, "source": "form"},
            {"studentId": "UMP0001", "date": day, "hours": 0.5, "source": "form"},
        ])
    rows.append({"studentId": "UMP0004", "date": today, "hours": 99, "source": "form"})

    payload = _dashboard_kpis_from_tracker(
        accounts,
        rows,
        today,
        tracker_cfg={"batchStarts": {}, "overrides": {}},
        app_activity_days={"UMP0002": {today}},
    )

    # No stats.attendance/submissionRate were seeded: the values still come from
    # actual tracker days, while Today's Active also recognizes today's app use.
    assert payload["total"] == 3
    assert payload["active"] == 2
    assert payload["pending"] == 1  # access-off students are not expected to submit.
    assert payload["atRisk"] == 2
    assert payload["avgHours"] == 2.3  # seven real study hours / three students
    assert payload["avgAttendance"] == 50  # access-off students are excluded from tracker rates.
    assert payload["weeklySub"] == 50
    assert {row["name"]: row["value"] for row in payload["performanceMix"]} == {
        "Excellent": 1,
        "At Risk": 2,
    }
    assert len(payload["weeklyStudy"]) == 7
    assert all(row["hours"] == 0.3 for row in payload["weeklyStudy"])
    assert payload["batchOverview"][0]["name"] == "Batch A"
    assert payload["batchOverview"][0]["attendance"] == 50
    assert payload["today"] == today.isoformat()


def test_dashboard_endpoint_counts_today_tracker_mcq_and_successful_login_activity(
    monkeypatch, client, mentor_headers
):
    from db import DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, STUDENT_MCQ_ATTEMPTS, get_db
    from routers import student_dashboard

    now = datetime.now(student_dashboard.IST)
    today = now.date()
    completed_at = int(now.astimezone(timezone.utc).timestamp() * 1000)
    successful_login = now.astimezone(timezone.utc).isoformat()

    async def seed():
        db = get_db()
        await db[STUDENT_ACCOUNTS].insert_many([
            {"studentId": "UMP0001", "studentName": "Tracker", "joinedOn": (today - timedelta(days=7)).isoformat()},
            {"studentId": "UMP0002", "studentName": "MCQ", "joinedOn": (today - timedelta(days=1)).isoformat()},
            {"studentId": "UMP0003", "studentName": "Login", "joinedOn": (today - timedelta(days=2)).isoformat()},
        ])
        await db[DASHBOARD_STUDENTS].insert_one({
            "studentId": "UMP0001",
            "studyLog": [{"date": today.isoformat(), "hours": 2}],
        })
        await db[STUDENT_MCQ_ATTEMPTS].insert_one({
            "studentId": "UMP0002", "kind": "daily", "completedAt": completed_at,
        })
        await db["login_failures"].insert_one({
            "_id": "UMP0003", "lastOkAt": successful_login,
        })

    asyncio.run(seed())
    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", lambda: [])
    response = client.get("/api/student-dashboard/dashboard/kpis", headers=mentor_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trackerDataAvailable"] is True
    assert payload["active"] == 3
    assert payload["pending"] == 2  # MCQ/login activity is not a tracker submission.
    assert {row["student"] for row in payload["recentActivity"]} == {"Tracker", "MCQ", "Login"}


def test_dashboard_kpis_do_not_turn_tracker_read_failure_into_zeroes(
    monkeypatch, client, mentor_headers
):
    from routers import student_dashboard

    def unavailable_tracker_sheet():
        raise RuntimeError("test-only tracker outage")

    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", unavailable_tracker_sheet)
    response = client.get("/api/student-dashboard/dashboard/kpis", headers=mentor_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trackerDataAvailable"] is False
    assert payload["source"] == "partial"
    assert payload["active"] is None
    assert payload["avgAttendance"] is None
    assert payload["weeklySub"] is None
    assert payload["performanceMix"] is None
    assert payload["attendanceTrend"] is None
