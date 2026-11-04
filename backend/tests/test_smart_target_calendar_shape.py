"""The smart-target view must survive every stored snapshot shape.

A student whose history contains a CALENDAR plan (mode "calendar", day dates
on the day rows, no personal startDate/extensions) used to crash the whole
dashboard with a KeyError, which surfaced as a 500 on
/api/smart-targets/student/dashboard (12 failures on 04-Nov-2026 across
revisions 00041-00049). Personal plans (mode "personal") carry startDate,
extensions and includedBackupDays instead.

Both shapes are pinned here so neither can break again.
"""
from datetime import date

import pytest

from routers.smart_target_engine import view

TODAY = date(2026, 11, 4)


def _calendar_state():
    """Exactly the shape stored for the Super 75 calendar plan."""
    return {
        "studentId": "UMP0141",
        "planId": "tp-c40628956cd1",
        "name": "CA Inter Super 75",
        "mode": "calendar",
        "days": [
            {"day": 24, "date": "2026-10-27",
             "tasks": [{"id": "t1", "mandatory": True}], "completions": {}},
            {"day": 25, "date": "2026-10-28",
             "tasks": [{"id": "t2", "mandatory": True}], "completions": {}},
        ],
        "version": 0,
    }


def _personal_state():
    """Exactly the shape a personal plan snapshot has."""
    return {
        "studentId": "UMP9900",
        "planId": "tp-demo-tutorial",
        "name": "Demo Plan",
        "mode": "personal",
        "startDate": "2026-10-29",
        "startedAt": "2026-10-29T00:00:00Z",
        "days": [
            {"day": 1, "tasks": [{"id": "t1", "mandatory": True}], "completions": {}},
        ],
        "extensions": [],
        "includedBackupDays": 0,
        "revisionBudgetMinutes": 30,
        "version": 0,
    }


def test_calendar_snapshot_renders_instead_of_raising():
    result = view(_calendar_state(), TODAY)
    assert result["planId"] == "tp-c40628956cd1"
    assert result["totalDays"] == 2
    # The first day's own date anchors the calendar.
    assert result["startDate"] == "2026-10-27"
    assert result["currentDay"] == 24
    assert result["days"] and result["days"][0]["day"] == 24


def test_personal_snapshot_still_renders():
    result = view(_personal_state(), TODAY)
    assert result["planId"] == "tp-demo-tutorial"
    assert result["startDate"] == "2026-10-29"
    assert result["totalDays"] == 1
    assert result["currentDay"] == 1


def test_calendar_snapshot_with_completed_day_keeps_the_real_date():
    state = _calendar_state()
    state["days"][0]["completions"] = {"t1": {"at": "2026-10-27T10:00:00Z"}}
    state["days"][0]["completedOn"] = "2026-10-27"
    result = view(state, TODAY)
    assert result["completedDays"] == 1
    assert result["days"][0]["completedOn"] == "2026-10-27"
    assert result["days"][0]["done"] is True


def test_extensions_and_backup_days_default_to_zero_for_calendar_snapshots():
    result = view(_calendar_state(), TODAY)
    assert result["extensions"] == []
    assert result["includedBackupDays"] == 0
    assert result["approvedExtensionDays"] == 0
