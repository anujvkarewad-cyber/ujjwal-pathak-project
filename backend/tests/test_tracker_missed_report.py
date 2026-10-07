"""Mentor-only Jan 2027 missed daily-tracker report."""
import asyncio
from datetime import date, datetime

import pytest

from db import DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db
from routers.student_dashboard import (
    IST,
    TRACKER_HISTORY_FLOOR,
    _full_tracker_history_start,
    _merge_tracker_roster,
    _parse_tracker_day,
    _tracker_day_entry,
    _tracker_submission_day,
)


@pytest.fixture(autouse=True)
def avoid_live_roster_fetch(monkeypatch):
    from routers import student_dashboard

    monkeypatch.setattr(student_dashboard, "_fetch_tracker_roster_sync", lambda: [])


def test_tracker_dates_parse_sheet_values_and_reject_broken_epoch_as_study_day():
    assert _parse_tracker_day("Fri Jan 01 2027 00:00:00 GMT+0530 (India Standard Time)") == date(2027, 1, 1)
    assert _tracker_submission_day(
        "01/01/1970 05:30:00",
        "01/10/2026 00:10:32",
    ) == date(2026, 10, 1)


def test_tracker_roster_uses_sheet_name_for_each_student_id_and_keeps_joining_date():
    mongo = [{
        "studentId": "UMP0001",
        "studentName": "Stale Wrong Name",
        "joinedOn": "2026-09-30",
        "attempt": "Jan 2027",
    }]
    sheet = [{
        "studentId": "UMP0001",
        "studentName": "Correct Sheet Name",
        "group": "Group 1",
        "attempt": "Jan 2027",
        "batch": "Before Result Batch 1",
    }]
    merged = _merge_tracker_roster(mongo, sheet)
    assert merged[0]["studentId"] == "UMP0001"
    assert merged[0]["studentName"] == "Correct Sheet Name"
    assert merged[0]["joinedOn"] == "2026-09-30"


def test_tracker_day_entry_merges_form_and_mongo_without_double_counting_hours():
    entry = _tracker_day_entry(
        [{
            "hours": 6,
            "subjects": "Accounts",
            "tomorrowTarget": "Audit",
            "mentorSupport": "Yes",
            "submissionTime": "06/10/2026 09:00:00",
            "source": "form",
        }],
        [{
            "hours": 6,
            "subjects": "Accounts",
            "proofUrl": "https://example.test/proof",
            "source": "mongo",
        }],
        date(2026, 10, 6),
    )
    assert entry["submitted"] is True
    assert entry["hours"] == 6
    assert entry["tomorrowTarget"] == "Audit"
    assert entry["mentorSupport"] == "Yes"
    assert entry["proofUrl"] == "https://example.test/proof"
    assert entry["sources"] == ["form", "mongo"]


def test_full_history_starts_at_earliest_joining_or_genuine_submission():
    accounts = [
        {"studentId": "UMP0001", "attempt": "Jan 2027", "joinedOn": "2026-09-02"},
        {"studentId": "UMP0002", "attempt": "Jan 2027", "joinedOn": ""},
        {"studentId": "UMP0003", "attempt": "May 2027", "joinedOn": "2026-08-01"},
    ]
    submissions = [
        {"studentId": "UMP0002", "date": date(2026, 9, 1)},
        {"studentId": "UMP0003", "date": date(2026, 8, 1)},
    ]
    assert _full_tracker_history_start(accounts, submissions, date(2026, 10, 6)) == date(2026, 9, 1)


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
                    "joinedOn": "2026-09-29",
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
            {"studentId": "UMP0001", "date": date(2026, 9, 28)},
            {"studentId": "UMP0001", "date": date(2026, 9, 29)},
            {"studentId": "UMP0001", "date": date(2026, 9, 29)},
            {"studentId": "UMP0002", "date": date(2026, 9, 28)},
            {"studentId": "UMP0002", "date": date(2026, 9, 30)},
            {"studentId": "UMP0005", "date": date(2026, 9, 28)},
            {"studentId": "UMP0005", "date": date(2026, 9, 29)},
            {"studentId": "UMP0005", "date": date(2026, 9, 30)},
        ],
    )

    response = client.get(
        "/api/student-dashboard/tracker-missed-report?from=2026-09-28&to=2026-09-30",
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
    assert rows["UMP0001"]["expectedFrom"] == "2026-09-29"
    assert rows["UMP0001"]["expectedDays"] == 2
    assert rows["UMP0001"]["submittedDays"] == 1
    assert rows["UMP0001"]["submittedDates"] == ["2026-09-29"]
    assert rows["UMP0001"]["missedDates"] == ["2026-09-30"]
    assert rows["UMP0002"]["expectedFrom"] == "2026-09-28"
    assert rows["UMP0002"]["expectedDays"] == 3
    assert rows["UMP0002"]["submittedDays"] == 2
    assert rows["UMP0002"]["submittedDates"] == ["2026-09-28", "2026-09-30"]
    assert rows["UMP0002"]["missedDates"] == ["2026-09-29"]
    assert rows["UMP0005"]["submittedDays"] == 3
    assert rows["UMP0005"]["missedDays"] == 0
    assert rows["UMP0005"]["missedDates"] == []


def test_tracker_day_includes_current_app_mongo_submissions(client, mentor_headers, monkeypatch):
    seed_accounts()
    today = datetime.now(IST).date()

    async def _seed_logs():
        await get_db()[DASHBOARD_STUDENTS].insert_many([
            {
                "studentId": "UMP0001",
                "studyLog": [{"date": today.isoformat(), "hours": 6, "topic": "Accounts", "proof": ""}],
            },
            {
                "studentId": "UMP0002",
                "studyLog": [{"date": today.isoformat(), "hours": 4.5, "topic": "Audit", "proof": ""}],
            },
        ])

    asyncio.run(_seed_logs())

    from routers import student_dashboard

    monkeypatch.setattr(
        student_dashboard,
        "_fetch_tracker_submissions_sync",
        lambda: [{
            "studentId": "UMP0002",
            "date": today,
            "hours": 4.5,
            "subjects": "Audit",
            "tomorrowTarget": "FM",
            "source": "form",
        }],
    )

    response = client.get(
        "/api/student-dashboard/tracker-day?dayIndex=13&batch=All%20Batches",
        headers=mentor_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selectedDay"] == today.isoformat()
    assert body["submitted"] == 2
    assert body["missed"] == 1
    rows = {row["id"]: row for row in body["list"]}
    assert rows["UMP0001"]["entry"]["submitted"] is True
    assert rows["UMP0001"]["entry"]["hours"] == 6
    assert rows["UMP0002"]["entry"]["hours"] == 4.5
    assert rows["UMP0002"]["entry"]["tomorrowTarget"] == "FM"
    assert rows["UMP0005"]["entry"]["submitted"] is False
    assert body["sources"]["mongoRows"] == 2


def test_full_tracker_report_resolves_start_and_runs_through_today(client, mentor_headers, monkeypatch):
    seed_accounts()

    from routers import student_dashboard

    monkeypatch.setattr(
        student_dashboard,
        "_fetch_tracker_submissions_sync",
        lambda: [
            {"studentId": "UMP0005", "date": date(2026, 9, 28)},
            {"studentId": "UMP0001", "date": date(2026, 9, 29)},
            {"studentId": "UMP0002", "date": date(2026, 9, 30)},
        ],
    )

    response = client.get(
        "/api/student-dashboard/tracker-missed-report?scope=joined-to-date",
        headers=mentor_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "joined-to-date"
    assert body["from"] == TRACKER_HISTORY_FLOOR.isoformat()
    assert body["historyFloor"] == "2026-09-28"
    assert body["to"] >= body["from"]
    rows = {row["studentId"]: row for row in body["items"]}
    assert rows["UMP0001"]["expectedFrom"] == "2026-09-29"
    assert rows["UMP0002"]["expectedFrom"] == "2026-09-30"
    assert rows["UMP0005"]["expectedFrom"] == "2026-09-28"


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
        "/api/student-dashboard/tracker-missed-report?from=2026-09-28&to=2026-09-30",
        headers=mentor_headers,
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Tracker form data could not be loaded. No report was calculated."
