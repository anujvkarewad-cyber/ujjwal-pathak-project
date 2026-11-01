"""One definition of "this week" for every ranking, report, export and push.

Owner decision 2026-10-17: the week runs **Sunday -> Saturday**, not Monday -> Sunday.

Reason: a lot of students study on Sunday and fill the tracker on Monday morning.
Under a Mon..Sun window, Monday is already the start of the *next* week by then, so
Sunday's hours belong to a week nobody can see any more - the day simply vanished
from their weekly total and from the weekly board. Making Sunday the FIRST day of the
week keeps that late entry inside the week that is still running.

Every calendar-week calculation must come from here. A local
``today - timedelta(days=today.weekday())`` is the old Monday rule and will silently
disagree with the leaderboard, the Reports tab and the mentor's tracker export.
"""

from __future__ import annotations

from datetime import date, timedelta

#: Python's ``date.weekday()``: Monday is 0 ... Sunday is 6.
WEEK_START_WEEKDAY = 6  # Sunday
DAYS_PER_WEEK = 7

#: Monday anchor kept only where a key comes from outside this app (see below).
_LEGACY_WEEK_START_WEEKDAY = 0


def week_start(day: date) -> date:
    """The Sunday that opens the calendar week containing ``day``."""
    return day - timedelta(days=(day.weekday() - WEEK_START_WEEKDAY) % DAYS_PER_WEEK)


def week_end(day: date) -> date:
    """The Saturday that closes the calendar week containing ``day``."""
    return week_start(day) + timedelta(days=DAYS_PER_WEEK - 1)


def week_window(day: date) -> tuple[date, date]:
    """``(week_start, today)`` for the running week, ``(start, end)`` for a past one.

    A live window never reaches into the future: on Wednesday the current week is
    Sun..Wed, which is what ``expected_days`` and the progress bars are measured on.
    """
    start = week_start(day)
    return start, min(start + timedelta(days=DAYS_PER_WEEK - 1), day)


def week_start_iso(day: date) -> str:
    return week_start(day).isoformat()


def normalise_week_key(value) -> str:
    """Re-anchor a week key to this rule.

    ``analytics_trends.weekStart`` is written by the external sync pipeline, so the
    stored keys may still be Monday-anchored. Grouping on the raw string while the
    cutoff uses Sunday keys would silently drop the current week from the cohort
    report; snapping every key here keeps the join and the filter on one anchor
    whatever the producer wrote.
    """
    raw = str(value or "")[:10]
    if len(raw) != 10:
        return ""
    try:
        return week_start_iso(date.fromisoformat(raw))
    except ValueError:
        return raw
