"""Composite ranking logic (backend/routers/ranking.py).

Covers the owner decisions: composite score, always-unique ranks, per-segment
ranking, total hours deciding rank with the daily average only displayed, and
the joining-date/floor semantics shared with the daily tracker.
"""
from datetime import date

import pytest

from routers.ranking import (
    DAILY_REFERENCE_HOURS,
    StudentActivity,
    expected_days,
    mcq_coverage,
    mcq_enabled,
    period_window,
    rank_segments,
    reference_hours,
    score_student,
    weights,
)

TODAY = date(2026, 10, 7)          # Wednesday
# An explicit 3-day window, not "the running week": these tests are about window
# arithmetic (the week anchor itself is pinned by tests/test_week_window.py).
WEEK_START, WEEK_END = date(2026, 10, 5), date(2026, 10, 7)

# A complete Sun..Sat week, for tests about realistic daily rates and totals: on the
# closing day (Saturday) period_window("weekly", ...) spans exactly these seven days.
TODAY_7 = date(2026, 10, 10)       # Saturday
SEVEN_START, SEVEN_END = date(2026, 10, 4), date(2026, 10, 10)
FULL_WEEK = [date(2026, 10, d) for d in range(4, 11)]


def activity(sid, hours=0.0, days=None, correct=0, attempted=0, joined=None,
             batch="B1", group="G1"):
    """`hours` is the period TOTAL, spread evenly across `days`."""
    days = days if days is not None else []
    per_day = (hours / len(days)) if days else 0.0
    return StudentActivity(
        student_id=sid, name=f"Student {sid}", batch=batch, group=group,
        joined_on=joined, hours_by_date={d: per_day for d in days},
        submitted_dates=set(days), questions_attempted=attempted,
        questions_correct=correct,
    )


# ── expected days: floor + joining date ─────────────────────────────────────

def test_floor_applies_to_old_joiners():
    assert expected_days(date(2026, 8, 2), WEEK_START, WEEK_END) == 3


def test_later_joiner_starts_on_their_own_date():
    assert expected_days(date(2026, 10, 6), WEEK_START, WEEK_END) == 2


def test_joiner_after_the_window_is_not_expected():
    assert expected_days(date(2026, 10, 20), WEEK_START, WEEK_END) == 0


def test_missing_join_date_uses_the_window_start():
    assert expected_days(None, WEEK_START, WEEK_END) == 3


# ── periods ────────────────────────────────────────────────────────────────

def test_weekly_window_opens_on_sunday():
    """Owner decision 2026-10-17: the week is Sunday..Saturday.

    TODAY is Wed 7 Oct 2026, so the running week opened Sun 4 Oct - it does not
    start on Mon 5 Oct. That one-day shift is what keeps a Sunday log entered on
    Monday morning inside the week it belongs to.
    """
    assert period_window("weekly", TODAY) == (date(2026, 10, 4), TODAY)
    assert period_window("weekly", date(2026, 10, 4)).__class__ is tuple   # Sunday input
    assert period_window("weekly", date(2026, 10, 4))[0] == date(2026, 10, 4)
    assert period_window("weekly", date(2026, 10, 10))[0] == date(2026, 10, 4)  # Saturday
    assert period_window("weekly", date(2026, 10, 11))[0] == date(2026, 10, 11)  # next Sunday


def test_monthly_window_starts_on_the_first():
    assert period_window("monthly", TODAY) == (date(2026, 10, 1), TODAY)


def test_overall_window_respects_the_history_floor():
    assert period_window("overall", TODAY) == (date(2026, 9, 28), TODAY)


def test_monthly_is_not_a_copy_of_weekly():
    """The live defect: monthlyHours was an exact copy of weeklyHours.

    Days 1-4 Oct sit inside the month but before this week, so the two windows
    must disagree.
    """
    early_month = [date(2026, 10, d) for d in range(1, 8)]
    a = activity("UMP0001", hours=70, days=early_month, joined=date(2026, 9, 28))
    monthly = score_student(a, *period_window("monthly", TODAY), "monthly")
    weekly = score_student(a, *period_window("weekly", TODAY), "weekly")
    assert monthly.hours > weekly.hours


# ── scoring ────────────────────────────────────────────────────────────────

def test_perfect_student_scores_100():
    a = activity("UMP0010", hours=DAILY_REFERENCE_HOURS * 3, days=[date(2026, 10, 5),
                 date(2026, 10, 6), date(2026, 10, 7)], correct=40, attempted=40)
    row = score_student(a, WEEK_START, WEEK_END, "weekly")
    assert row.score == 100.0
    assert row.rank == 0  # assigned by rank_segments()


def test_zero_activity_scores_zero_and_is_still_rankable():
    row = score_student(activity("UMP0011"), WEEK_START, WEEK_END, "weekly")
    assert row.score == 0.0
    assert row.is_active is False
    assert row.not_ranked_reason is None


def test_one_lucky_question_is_not_a_perfect_score():
    """1/1 correct must not beat real work: the volume gate applies."""
    row = score_student(activity("UMP0013", correct=1, attempted=1),
                        WEEK_START, WEEK_END, "weekly")
    assert row.score == pytest.approx(1.5)


def test_not_yet_enrolled_is_unranked_rather_than_penalised():
    row = score_student(activity("UMP0014", joined=date(2026, 10, 20)),
                        WEEK_START, WEEK_END, "weekly")
    assert row.rank == 0
    assert "not yet enrolled" in row.not_ranked_reason


def test_joining_date_protects_attendance():
    a = activity("UMP0015", joined=date(2026, 10, 6), hours=24,
                 days=[date(2026, 10, 6), date(2026, 10, 7)])
    row = score_student(a, WEEK_START, WEEK_END, "weekly")
    assert row.expected_days == 2
    assert row.attendance_rate == 1.0


# ── hours: total decides rank, daily rate is displayed ─────────────────────

def test_more_submitted_hours_rank_higher_no_flat_cap():
    grinder = activity("UMP0020", hours=68, days=FULL_WEEK)      # 9.7 h/day
    lighter = activity("UMP0021", hours=30, days=FULL_WEEK)      # 4.3 h/day
    rows = rank_segments([lighter, grinder], *period_window("weekly", TODAY_7),
                         "weekly", "batch")["B1"]
    assert [r.student_id for r in rows] == ["UMP0020", "UMP0021"]
    assert rows[0].score - rows[1].score > 10


def test_no_two_real_hour_totals_flatten_together():
    window = period_window("weekly", TODAY_7)
    a = score_student(activity("UMP0022", hours=40, days=FULL_WEEK), *window, "weekly")
    b = score_student(activity("UMP0023", hours=50, days=FULL_WEEK), *window, "weekly")
    assert b.score > a.score


def test_total_hours_beat_a_better_daily_rate():
    """Owner decision: rank on total hours. 68 h beats 20 h in 2 days."""
    grinder = activity("UMP0030", hours=68, days=FULL_WEEK)                     # 9.71 h/day
    joiner = activity("UMP0031", hours=20, days=[date(2026, 10, 9), date(2026, 10, 10)],
                      joined=date(2026, 10, 9))                                 # 10.0 h/day
    rows = rank_segments([grinder, joiner], *period_window("weekly", TODAY_7),
                         "weekly", "batch")["B1"]
    assert rows[0].student_id == "UMP0030"
    # ...even though the joiner's daily rate is the better of the two.
    assert rows[0].hours_per_day == 9.71
    assert rows[1].hours_per_day == 10.0


def test_effort_yardstick_is_uniform_across_the_segment():
    """Same total hours -> same hours credit, whatever the shape or joining date.

    The total score may legitimately differ (a student who submitted on only 3 of
    7 expected days loses attendance credit), but the hours component must not,
    otherwise the ranking is secretly a daily-rate ranking again.
    """
    three_days = [date(2026, 10, d) for d in (5, 6, 7)]
    same_total_a = activity("UMP0032", hours=42, days=three_days, joined=date(2026, 10, 5))
    same_total_b = activity("UMP0033", hours=42, days=FULL_WEEK)
    start, end = period_window("weekly", TODAY_7)
    a = score_student(same_total_a, start, end, "weekly")
    b = score_student(same_total_b, start, end, "weekly")
    assert a.breakdown["hoursScore"] == b.breakdown["hoursScore"] == 20.0
    # ...while attendance still reflects the different submission coverage.
    assert b.score > a.score


# ── ranks: unique and deterministic ────────────────────────────────────────

def test_ranks_are_unique_and_contiguous():
    tie_a = activity("UMP0040", hours=36, days=[WEEK_START, date(2026, 10, 6), WEEK_END],
                     correct=20, attempted=20)
    tie_b = activity("UMP0041", hours=36, days=[WEEK_START, date(2026, 10, 6), WEEK_END],
                     correct=20, attempted=20)
    other = activity("UMP0042", hours=18, days=[WEEK_START, date(2026, 10, 6)])
    rows = rank_segments([tie_b, other, tie_a], WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert sorted(r.rank for r in rows) == [1, 2, 3]          # unique, no shared rank
    assert [r.student_id for r in rows] == ["UMP0040", "UMP0041", "UMP0042"]


def test_tie_break_chain_uses_accuracy_then_id():
    days = [WEEK_START, date(2026, 10, 6), WEEK_END]
    sharper = activity("UMP0050", hours=18, days=days, correct=9, attempted=10)
    duller = activity("UMP0051", hours=18, days=days, correct=4, attempted=10)
    rows = rank_segments([duller, sharper], WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert [r.student_id for r in rows] == ["UMP0050", "UMP0051"]


def test_order_does_not_depend_on_input_order():
    students = [
        activity("UMP0060", hours=36, days=[WEEK_START, WEEK_END]),
        activity("UMP0061"),
        activity("UMP0062", hours=9, days=[WEEK_START]),
    ]
    forward = rank_segments(students, WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    reverse = rank_segments(list(reversed(students)), WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert [(r.student_id, r.rank) for r in forward] == [(r.student_id, r.rank) for r in reverse]


def test_inactive_students_rank_last_and_are_flagged():
    rows = rank_segments([activity("UMP0070"), activity("UMP0071", hours=36, days=[WEEK_START])],
                         WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert rows[0].student_id == "UMP0071"
    assert rows[1].student_id == "UMP0070"
    assert rows[1].rank == 2
    assert rows[1].is_active is False


# ── segments ───────────────────────────────────────────────────────────────

def test_ranking_is_per_segment_not_global():
    students = [
        activity("UMP0080", hours=36, days=[WEEK_START], batch="B1"),
        activity("UMP0081", hours=18, days=[WEEK_START], batch="B1"),
        activity("UMP0082", hours=6, days=[WEEK_START], batch="B2"),   # weakest overall
    ]
    per_batch = rank_segments(students, WEEK_START, WEEK_END, "weekly", "batch")
    assert per_batch["B1"][0].student_id == "UMP0080"
    assert per_batch["B2"][0].student_id == "UMP0082"
    assert per_batch["B2"][0].rank == 1          # #1 inside B2, not #3 globally


def test_group_segmentation_produces_different_ranks():
    students = [
        activity("UMP0090", hours=36, days=[WEEK_START], batch="B1", group="G1"),
        activity("UMP0091", hours=30, days=[WEEK_START], batch="B1", group="G2"),
        activity("UMP0092", hours=6, days=[WEEK_START], batch="B1", group="G2"),
    ]
    per_group = rank_segments(students, WEEK_START, WEEK_END, "weekly", "group")
    assert per_group["G2"][0].student_id == "UMP0091"
    assert per_group["G1"][0].rank == 1


def test_unassigned_students_are_not_dropped():
    rows = rank_segments([activity("UMP0099", batch="", group="")],
                         WEEK_START, WEEK_END, "weekly", "batch")
    assert "(unassigned)" in rows
    assert rows["(unassigned)"][0].student_id == "UMP0099"


# ── breakdown reporting ────────────────────────────────────────────────────

def test_breakdown_components_are_reported_and_capped():
    row = score_student(
        activity("UMP0100", hours=DAILY_REFERENCE_HOURS * 30, days=[WEEK_START],
                 correct=99, attempted=99),
        WEEK_START, WEEK_END, "weekly",
    )
    assert row.breakdown["hoursScore"] == 40.0      # capped at the weight
    assert row.breakdown["mcqScore"] == 30.0
    assert row.breakdown["attendanceScore"] < 30.0  # only 1 of 3 days submitted
    assert row.score == round(sum(row.breakdown.values()), 1)


def test_reference_hours_scales_with_the_window():
    assert reference_hours(WEEK_START, WEEK_END) == DAILY_REFERENCE_HOURS * 3


# ── MCQ component: conditional on real coverage ────────────────────────────
#
# MCQ is 30 of 100 points but the app only syncs attempts for a small minority of
# students. Scoring it everywhere would reward the handful whose attempts synced
# and cap everyone else below 100 for reasons outside their control.

def test_weights_sum_to_100_with_mcq():
    hours, mcq, attendance = weights(True)
    assert (hours, mcq, attendance) == (40.0, 30.0, 30.0)
    assert round(hours + mcq + attendance, 6) == 100.0


def test_weights_renormalise_when_mcq_is_out():
    hours, mcq, attendance = weights(False)
    assert mcq == 0.0
    assert round(hours + attendance, 6) == 100.0
    assert hours > 40.0 and attendance > 30.0     # scaled up, not simply dropped


def test_full_marks_possible_without_mcq():
    """A student who maxes hours and attendance must still reach 100."""
    row = score_student(
        activity("UMP0200", hours=DAILY_REFERENCE_HOURS * 3,
                 days=[WEEK_START, date(2026, 10, 6), WEEK_END]),
        WEEK_START, WEEK_END, "weekly", use_mcq=False,
    )
    assert row.score == 100.0
    assert row.mcq_used is False
    assert row.components == ["hours", "attendance"]
    assert row.breakdown["mcqScore"] == 0.0


def test_coverage_is_measured_over_students_who_can_be_scored():
    with_attempts = activity("UMP0210", hours=6, days=[WEEK_START], correct=8, attempted=10)
    without = activity("UMP0211", hours=6, days=[WEEK_START])
    assert mcq_coverage([with_attempts, without], WEEK_START, WEEK_END) == 0.5
    assert mcq_coverage([with_attempts], WEEK_START, WEEK_END) == 1.0
    # a student who has not joined yet must not drag coverage down
    not_yet = activity("UMP0212", joined=date(2026, 12, 1))
    assert mcq_coverage([with_attempts, not_yet], WEEK_START, WEEK_END) == 1.0


def test_mcq_is_dropped_when_coverage_is_thin(monkeypatch):
    monkeypatch.setattr("routers.ranking.MCQ_MODE", "auto")
    monkeypatch.setattr("routers.ranking.MCQ_MIN_COVERAGE", 0.6)
    students = [activity(f"UMP022{i}", hours=18, days=[WEEK_START]) for i in range(4)]
    students[0].questions_attempted = 20          # 1 of 4 covered = 0.25 < 0.6
    students[0].questions_correct = 15
    rows = rank_segments(students, WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert all(r.mcq_used is False for r in rows)
    assert all(r.breakdown["mcqScore"] == 0.0 for r in rows)
    # Identical hours and attendance must now score identically: the student whose
    # MCQ happened to sync can no longer out-rank peers on unearned points.
    assert len({r.score for r in rows}) == 1


def test_mcq_counts_when_coverage_is_real(monkeypatch):
    monkeypatch.setattr("routers.ranking.MCQ_MODE", "auto")
    monkeypatch.setattr("routers.ranking.MCQ_MIN_COVERAGE", 0.6)
    students = [activity(f"UMP023{i}", hours=18, days=[WEEK_START], correct=18, attempted=20)
                for i in range(4)]
    rows = rank_segments(students, WEEK_START, WEEK_END, "weekly", "batch")["B1"]
    assert all(r.mcq_used is True for r in rows)
    assert rows[0].breakdown["mcqScore"] > 0


def test_mcq_mode_can_be_forced(monkeypatch):
    students = [activity("UMP0240", hours=6, days=[WEEK_START])]
    monkeypatch.setattr("routers.ranking.MCQ_MODE", "on")
    assert mcq_enabled(students, WEEK_START, WEEK_END) is True
    monkeypatch.setattr("routers.ranking.MCQ_MODE", "off")
    assert mcq_enabled(students, WEEK_START, WEEK_END) is False


def test_scores_stay_within_zero_and_one_hundred_in_both_modes():
    monsters = [activity(f"UMP025{i}", hours=DAILY_REFERENCE_HOURS * 30,
                         days=[WEEK_START, date(2026, 10, 6), WEEK_END],
                         correct=99, attempted=99) for i in range(2)]
    for use_mcq in (True, False):
        rows = rank_segments(monsters, WEEK_START, WEEK_END, "weekly", "batch")
        for row in rows["B1"]:
            assert 0.0 <= row.score <= 100.0
