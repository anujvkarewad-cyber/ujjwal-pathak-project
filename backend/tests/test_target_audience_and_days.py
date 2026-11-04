"""Audience and day-list rules for student targets (04-Nov-2026).

Three bugs were reported by students on 04-Nov:

1. A Group 2 student was shown Group 1 papers (and the other way round), because a
   "Both Groups" plan publishes every paper for the whole batch.
2. One day listed more tasks than the mentor published, with a task repeated -
   a cancelled plan keeps its target rows active, so two plans merged into one day.
3. The day strip showed the same day twice ("Day 1, Day 1"), because the plan id
   was part of the bucket key.

The helpers are read straight out of `routers/daily_targets.py` so the test needs
no FastAPI/database import, and it fails if the rules are ever reverted.
"""

import pathlib
import re

import pytest

SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "routers" / "daily_targets.py").read_text(encoding="utf-8")

NAMESPACE = {"re": re}
for _name in ("_norm", "_is_all", "_group_key", "_batch_key", "_attempt_key", "_subject_key",
              "_subject_group", "_subject_allowed", "_audience_matches", "from_live_plan"):
    _match = re.search(rf"^def {_name}\(.*?(?=^def |\Z)", SOURCE, re.S | re.M)
    assert _match, f"helper {_name} not found in daily_targets.py"
    exec(_match.group(0), NAMESPACE)

subject_group = NAMESPACE["_subject_group"]
subject_allowed = NAMESPACE["_subject_allowed"]
from_live_plan = NAMESPACE["from_live_plan"]
audience_matches = NAMESPACE["_audience_matches"]


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Advanced Accounting", "g1"),
        ("Corporate and Other Laws", "g1"),
        ("Taxation", "g1"),
        ("Cost and Management Accounting", "g2"),
        ("Auditing and Assurance", "g2"),
        ("All", ""),
        ("", ""),
    ],
)
def test_subject_group_map(subject, expected):
    assert subject_group(subject) == expected


def test_group_2_student_never_sees_group_1_papers():
    assert subject_allowed("g2", "Taxation") is False
    assert subject_allowed("g2", "Advanced Accounting") is False
    assert subject_allowed("g2", "Corporate and Other Laws") is False
    assert subject_allowed("g2", "Cost and Management Accounting") is True
    assert subject_allowed("g2", "Auditing and Assurance") is True
    assert subject_allowed("g2", "All") is True  # revision belongs to everyone


def test_group_1_student_never_sees_group_2_papers():
    assert subject_allowed("g1", "Auditing and Assurance") is False
    assert subject_allowed("g1", "Cost and Management Accounting") is False
    assert subject_allowed("g1", "Taxation") is True
    assert subject_allowed("both", "Auditing and Assurance") is True
    assert subject_allowed("both", "Taxation") is True


def test_both_group_plan_no_longer_crosses_papers():
    student = {"attempt": "Jan 2027", "batch": "After Result Batch 1", "group": "Group 2"}
    g1_row = {"attempt": "Jan 2027", "batch": "After Result Batch 1", "group": "Both", "subject": "Taxation"}
    g2_row = {"attempt": "Jan 2027", "batch": "After Result Batch 1", "group": "Both",
              "subject": "Cost and Management Accounting"}
    assert audience_matches(student, g1_row) is False
    assert audience_matches(student, g2_row) is True


def test_single_group_plan_stays_inside_its_group():
    student_g1 = {"attempt": "Jan 2027", "batch": "Before Result Batch 1", "group": "Group 1"}
    student_g2 = {"attempt": "Jan 2027", "batch": "Before Result Batch 1", "group": "Group 2"}
    plan = {"attempt": "Jan 2027", "batch": "Before Result Batch 1", "group": "Group 1", "subject": "Taxation"}
    assert audience_matches(student_g1, plan) is True
    assert audience_matches(student_g2, plan) is False


def test_batch_and_attempt_still_have_to_match():
    student = {"attempt": "Jan 2027", "batch": "After Result Batch 1", "group": "Group 1"}
    other_batch = {"attempt": "Jan 2027", "batch": "After Result Batch 2", "group": "Both", "subject": "Taxation"}
    other_attempt = {"attempt": "Sept 2026", "batch": "After Result Batch 1", "group": "Both", "subject": "Taxation"}
    assert audience_matches(student, other_batch) is False
    assert audience_matches(student, other_attempt) is False


def test_cancelled_plan_rows_are_dropped_but_legacy_rows_kept():
    live = {"tp-active"}
    assert from_live_plan({"planId": "tp-active"}, live) is True
    assert from_live_plan({"planId": "tp-cancelled"}, live) is False
    assert from_live_plan({"planId": None}, live) is True      # hand-published legacy row
    assert from_live_plan({"planId": "tp-x"}, set()) is True   # lookup failed: never blank the screen


def test_day_strip_has_one_bucket_per_day_not_per_plan():
    """The bucket key must not contain the plan id, or a day appears twice."""
    block = re.search(r"rows = await db\[TARGETS\]\.find\(.*?if not buckets:", SOURCE, re.S).group(0)
    key_line = re.search(r"key = \(.*?\)", block).group(0)
    assert "planId" not in key_line, f"day bucket still keyed by plan id: {key_line}"
    assert "day" in key_line and "date_iso" in key_line


def test_a_day_takes_tasks_from_one_plan_only():
    """The timeline keeps the newest plan per day and never repeats a task id."""
    progress = (pathlib.Path(__file__).resolve().parents[1] / "routers" / "student_target_progress.py").read_text(encoding="utf-8")
    assert "from_live_plan(row, live)" in progress, "timeline does not drop cancelled-plan rows"
    assert "newest" in progress and "by_day.setdefault(day_number, []).extend" in progress
    assert "if not task_id or task_id in seen" in progress, "timeline can repeat a task id"
