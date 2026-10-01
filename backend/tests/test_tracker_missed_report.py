"""Mentor-only Jan 2027 missed daily-tracker report."""
import asyncio
from datetime import date

from db import STUDENT_ACCOUNTS, get_db
from routers.student_dashboard import _parse_tracker_day, _tracker_submission_day


def test_tracker_dates_parse_sheet_values_and_reject_broken_epoch_as_study_day():
    assert _parse_tracker_day("Fri Jan 01 2027 00:00:00 GMT+0530 (India Standard Time)") == date(2027, 1, 1)
    assert _tracker_submission_day(
        "01/01/1970 05:30:00",
        "01/10/2026 00:10:32",
    ) == date(2026, 10, 1)


def seed_accounts():
    async def _seed():
        await get_db()[STUDENT_ACCOUNTS].insert_many(
            [
                {
                    "studentId": "UMP0001",
                    "studentName": "Alpha Student",
                    "attempt": "Fri Jan 01 2027 00:00:00 GMT+0530 (India Standard Time)",
                    "batch": "Super 30",
                    "group": "Group 1",
                    "joinedOn": "2026-09-02",
                },
                {
                    "studentId": "UMP0002",
                    "studentName": "Beta Student",
                    "attempt": "Jan 2027",
                    "batch": "Super 30",
                    "group": "Group 2",
                    "joinedOn": "",
                },
                {
                    "studentId": "UMP0003",
                    "studentName": "May Student",
                    "attempt": "May 2027",
                    "batch": "Super 30",
                    "group": "Group 1",
                },
                {
                    "studentId": "UMP0004",
                    "studentName": "Master Account",
                    "attempt": "Jan 2027",
                    "batch": "Super 30",
                    "group": "Both",
                    "master": True,
                },
                {
                    "studentId": "UMP0005",
                    "studentName": "Gamma Student",
                    "attempt": "Jan 2027",
                    "batch": "Super 30",
                    "group": "Both",
                    "joinedOn": "",
                },
            ]
        )

    asyncio.run(_seed())


def test_missed_tracker_report_counts_unique_days_and_respects_joined_on(client, mentor_headers, monkeypatch):
    seed_accounts()

    from routers import student_dashboard

    monkeypatch.setattr(
        student_dashboard,
        "_fetch_tracker_submissions_sync",
        lambda: [
            {"studentId": "UMP0001", "date": date(2026, 9, 1)},
            {"studentId": "UMP0001", "date": date(2026, 9, 2)},
            {"studentId": "UMP0001", "date": date(2026, 9, 2)},
            {"studentId": "UMP0002", "date": date(2026, 9, 1)},
            {"studentId": "UMP0002", "date": date(2026, 9, 3)},
            {"studentId": "UMP0005", "date": date(2026, 9, 1)},
            {"studentId": "UMP0005", "date": date(2026, 9, 2)},
            {"studentId": "UMP0005", "date": date(2026, 9, 3)},
        ],
    )

    response = client.get(
        "/api/student-dashboard/tracker-missed-report?from=2026-09-01&to=2026-09-03",
        headers=mentor_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attempt"] == "Jan 2027"
    assert body["dayRule"] == "Every calendar day"
    assert body["rosterCount"] == 3
    assert body["studentsWithMissedDays"] == 2
    assert body["studentsWithNoMissedDays"] == 1
    assert body["sourceSubmissionRows"] == 8

    rows = {row["studentId"]: row for row in body["items"]}
    assert rows["UMP0001"]["expectedFrom"] == "2026-09-02"
    assert rows["UMP0001"]["expectedDays"] == 2
    assert rows["UMP0001"]["submittedDays"] == 1
    assert rows["UMP0001"]["submittedDates"] == ["2026-09-02"]
    assert rows["UMP0001"]["missedDates"] == ["2026-09-03"]
    assert rows["UMP0002"]["expectedFrom"] == "2026-09-01"
    assert rows["UMP0002"]["expectedDays"] == 3
    assert rows["UMP0002"]["submittedDays"] == 2
    assert rows["UMP0002"]["submittedDates"] == ["2026-09-01", "2026-09-03"]
    assert rows["UMP0002"]["missedDates"] == ["2026-09-02"]
    assert rows["UMP0005"]["submittedDays"] == 3
    assert rows["UMP0005"]["missedDays"] == 0
    assert rows["UMP0005"]["missedDates"] == []


def test_missed_tracker_report_requires_mentor_and_valid_range(client, mentor_headers, monkeypatch):
    denied = client.get(
        "/api/student-dashboard/tracker-missed-report?from=2026-09-01&to=2026-09-03"
    )
    assert denied.status_code == 401

    reversed_range = client.get(
        "/api/student-dashboard/tracker-missed-report?from=2026-09-03&to=2026-09-01",
        headers=mentor_headers,
    )
    assert reversed_range.status_code == 400
    assert "cannot be after" in reversed_range.json()["detail"]


def test_missed_tracker_report_fails_closed_when_sheet_is_unavailable(client, mentor_headers, monkeypatch):
    seed_accounts()

    from routers import student_dashboard

    def fail():
        raise RuntimeError("sheet unavailable")

    monkeypatch.setattr(student_dashboard, "_fetch_tracker_submissions_sync", fail)
    response = client.get(
        "/api/student-dashboard/tracker-missed-report?from=2026-09-01&to=2026-09-03",
        headers=mentor_headers,
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Tracker form data could not be loaded. No report was calculated."
