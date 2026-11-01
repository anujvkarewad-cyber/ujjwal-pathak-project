"""The Sunday..Saturday week rule (backend/week_window.py).

Owner decision 2026-10-17: the week used to run Mon..Sun. Students who study on
Sunday and fill the tracker on Monday morning then landed in a week that had already
closed, so their Sunday hours counted in no week they could see. Sunday is now the
first day of the week, which keeps that late fill inside the running week.

These tests pin the rule itself and every surface that must agree with it: the
weekly board window, the mentor's report cutoff, the per-week top-3 anchor, the
analytics week keys, and the day the weekly-report push fires.
"""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

import pytest

import week_window
from week_window import normalise_week_key, week_end, week_start, week_window as week_bounds

# The week of Sun 4 Oct .. Sat 10 Oct 2026.
SUNDAY = date(2026, 10, 4)
WEEK = [SUNDAY + timedelta(days=i) for i in range(7)]   # Sun, Mon, ... Sat


def test_every_day_of_the_week_anchors_to_its_sunday():
    for day in WEEK:
        assert week_start(day) == SUNDAY, day.strftime("%A")
    assert week_start(SUNDAY) == SUNDAY            # Sunday opens the week
    assert week_start(SUNDAY + timedelta(days=6)) == SUNDAY   # Saturday closes it
    assert week_start(SUNDAY + timedelta(days=7)) == SUNDAY + timedelta(days=7)  # next Sunday


def test_week_closes_on_saturday():
    assert week_end(SUNDAY) == SUNDAY + timedelta(days=6)
    assert week_end(WEEK[3]).weekday() == 5          # Wed -> that week's Saturday
    assert all((week_end(d) - d).days >= 0 for d in WEEK)


def test_live_window_never_reaches_into_the_future():
    start, end = week_bounds(WEEK[2])                # Tuesday
    assert start == SUNDAY and end == WEEK[2]
    start, end = week_bounds(WEEK[6])                # Saturday, the closing day
    assert (start, end) == (SUNDAY, WEEK[6])


def test_the_old_monday_rule_is_not_still_anywhere():
    """A day-by-day guard: under Mon..Sun, Sunday belonged to the *previous* week.

    If somebody reintroduces `today - timedelta(days=today.weekday())`, Monday stops
    pointing at Sunday and this fails.
    """
    monday = WEEK[1]                                  # Mon 5 Oct 2026
    for day in WEEK:
        assert week_start(day) == SUNDAY
        assert day - timedelta(days=day.weekday()) != SUNDAY   # the old rule: never Sunday
    assert week_start(monday) == SUNDAY                        # new: back to Sun 4 Oct
    assert monday - timedelta(days=monday.weekday()) == monday  # old: stayed on Mon 5 Oct


def test_late_sunday_fill_counts_in_the_running_week():
    """The reason for the change, end to end on the ranking window.

    Hours logged for Sun 4 Oct and entered on Tue 6 Oct must sit inside the running
    week. Under the old rule the window on Tue 6 Oct opened Mon 5 Oct, so the Sunday
    entry belonged to no visible week at all.
    """
    from routers.ranking import StudentActivity, period_window, score_student

    def act(days):
        return StudentActivity(
            student_id="UMP0001", name="Late Filler", batch="B1", group="G1",
            hours_by_date={d: 5.0 for d in days}, submitted_dates=set(days),
        )

    start, end = period_window("weekly", date(2026, 10, 6))
    assert (start, end) == (SUNDAY, date(2026, 10, 6))
    row = score_student(act([SUNDAY]), start, end, "weekly")
    assert row.hours == pytest.approx(5.0), "the late Sunday log must be inside the week"

    # and the contrast that shows the fix: a Monday-open week excludes it
    dropped = score_student(act([SUNDAY]), date(2026, 10, 5), date(2026, 10, 6), "weekly")
    assert dropped.hours == pytest.approx(0.0)


def test_week_start_constant_is_the_only_knob():
    assert week_window.WEEK_START_WEEKDAY == 6  # Python weekday(): Sunday
    assert week_window.DAYS_PER_WEEK == 7


def test_foreign_week_keys_are_re_anchored_not_dropped():
    """analytics_trends.weekStart is written by the external sync pipeline, so stored
    keys may still be Monday-anchored. Grouping must not lose them at the cutoff."""
    assert normalise_week_key("2026-10-05") == "2026-10-04"    # Mon -> previous Sun
    assert normalise_week_key("2026-10-04") == "2026-10-04"    # already Sunday
    assert normalise_week_key("2026-10-10T00:00:00Z") == "2026-10-04"
    assert normalise_week_key("") == ""
    assert normalise_week_key(None) == ""
    assert normalise_week_key("not-a-date") == "not-a-date"


def test_leaderboard_display_dates_run_sunday_to_saturday():
    from routers.student_dashboard import _week_dates

    start, end = _week_dates(date(2026, 10, 7))
    assert date.fromisoformat(start) == SUNDAY
    assert date.fromisoformat(end) == SUNDAY + timedelta(days=6)
    assert date.fromisoformat(start).weekday() == 6
    assert date.fromisoformat(end).weekday() == 5


def test_mentor_report_cutoff_lands_on_a_sunday():
    from routers.analytics import _range_cutoff

    week_cut = _range_cutoff("week")
    assert week_cut.weekday() == 6, f"week cutoff is a {week_cut.strftime('%A')}, not Sunday"
    assert _range_cutoff("month") == week_cut - timedelta(weeks=4)
    assert _range_cutoff("month").weekday() == 6
    assert _range_cutoff("all") is None


def test_the_report_week_is_the_one_that_just_closed():
    """Owner decision 2026-10-18, with the real dates of that weekend.

    The week Sun 11 -> Sat 17 Oct closes at midnight; the report goes out on Sunday
    18, and the *new* week starts on that same Sunday 18.
    """
    report_day = date(2026, 10, 18)                      # Sunday
    assert week_start(report_day) == report_day          # next week starts today
    closed = week_start(report_day - timedelta(days=1))  # Sat 17 -> its own week
    assert (closed, week_end(closed)) == (date(2026, 10, 11), date(2026, 10, 17))


def test_weekly_report_push_is_sent_on_sunday_not_saturday(monkeypatch):
    """Why this test exists: the job was retimed to Saturday once, and a deploy at
    23:44 IST on a Saturday fired it to 118 devices the minute the container came up.
    The report belongs to the day after the week closes, and a late deploy must not
    turn the closing evening into a send."""
    import asyncio

    import push as push_service
    import push_scheduler

    sent: list = []
    claimed: list = []

    async def fake_claim(key):
        claimed.append(key)
        return True

    async def fake_push_all(title, body, link=None, tag=None, hold_quiet=False):
        sent.append({"title": title, "body": body, "link": link, "tag": tag})
        return 118

    monkeypatch.setattr(push_scheduler, "_claim", fake_claim)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "push_to_all", fake_push_all)
    monkeypatch.setattr(push_scheduler.behavior_push, "weekly_review_template", lambda: None)

    # Sunday 18 Oct 19:30 IST - send, and it describes the week that just closed
    asyncio.run(push_scheduler._job_weekly_report(datetime(2026, 10, 18, 19, 30, tzinfo=IST)))
    assert sent == [{
        "title": "\U0001F4CA Your weekly report is ready",
        "body": "See your hours, accuracy and rank for last week in the Reports tab.",
        "link": "reports",
        "tag": "weekly-2026-10-11",
    }], sent
    assert claimed == ["weekly-report-2026-10-18"]

    # Saturday night - the closing evening itself: nothing goes out (the old bug)
    sent.clear(); claimed.clear()
    asyncio.run(push_scheduler._job_weekly_report(datetime(2026, 10, 17, 23, 44, tzinfo=IST)))
    assert sent == [] and claimed == []

    # Sunday afternoon is too early; the day is not over yet
    sent.clear(); claimed.clear()
    asyncio.run(push_scheduler._job_weekly_report(datetime(2026, 10, 18, 12, 0, tzinfo=IST)))
    assert sent == [] and claimed == []

    # Monday - the window has passed, no late send
    sent.clear(); claimed.clear()
    asyncio.run(push_scheduler._job_weekly_report(datetime(2026, 10, 19, 9, 0, tzinfo=IST)))
    assert sent == [] and claimed == []

def test_the_owner_can_hold_the_weekly_report(monkeypatch):
    """"push mai bolu tabhi karna" - WEEKLY_REPORT_HOLD=1 must be enough to stop it.

    The hold is checked before the daily claim, so releasing it the same evening still
    sends the report instead of skipping a whole week.
    """
    import asyncio

    import push as push_service
    import push_scheduler

    sent: list = []
    claimed: list = []

    async def fake_claim(key):
        claimed.append(key)
        return True

    async def fake_push_all(title, body, link=None, tag=None, hold_quiet=False):
        sent.append(tag)
        return 118

    monkeypatch.setattr(push_scheduler, "_claim", fake_claim)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "push_to_all", fake_push_all)
    monkeypatch.setattr(push_scheduler.behavior_push, "weekly_review_template", lambda: None)
    sunday = datetime(2026, 10, 18, 19, 30, tzinfo=IST)

    monkeypatch.setenv("WEEKLY_REPORT_HOLD", "1")
    asyncio.run(push_scheduler._job_weekly_report(sunday))
    assert sent == [] and claimed == [], "held: nothing sent and nothing claimed"

    monkeypatch.setenv("WEEKLY_REPORT_HOLD", "0")
    asyncio.run(push_scheduler._job_weekly_report(sunday))
    assert sent == ["weekly-2026-10-11"], "released: the same evening still goes out"

