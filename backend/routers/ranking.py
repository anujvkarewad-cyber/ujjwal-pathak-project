"""Composite ranking for the mentor and student leaderboards.

Single source of truth for rank. Both surfaces read this module:

* mentor  -> ``GET /api/student-dashboard/leaderboard`` (authenticated)
* student -> the stored leaderboard rows surfaced through
  ``POST /api/student-dashboard/get`` (``getLeaderboard`` / ``getStats``)

Pure logic only: no database, no HTTP, no clock. Callers pass dates in and get
rankings out, which is what makes this testable without Mongo.

Owner decisions encoded here (7 Oct 2026)
-----------------------------------------
1. Composite score: hours 40 + MCQ 30 + attendance 30.
2. Ranks are always unique (deterministic tie-break chain, never shared ranks).
3. Ranking happens inside a segment (Batch or Group), not globally.
4. Study hours decide rank on the period total -- "jitna daily hours submit
   hota hai, us par" -- with the daily average reported alongside for display.
   The effort yardstick is uniform across the segment on purpose: normalising
   per student by their own expected days would silently turn this back into a
   daily-rate ranking and let a 2-day joiner outrank a 68-hour grinder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from week_window import week_start
from group_bucket import bucket_of

# ---------------------------------------------------------------------------
# Tunables (env-overridable so policy can change without a code edit)
# ---------------------------------------------------------------------------


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _date_env(name: str, default: str) -> date:
    try:
        return date.fromisoformat(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return date.fromisoformat(default)


# Practical ceiling just above real behaviour (live top performer ~9.7 h/day),
# so in normal ranges every extra hour keeps earning credit.
DAILY_REFERENCE_HOURS = _float_env("RANKING_DAILY_REFERENCE_HOURS", 12.0)

W_HOURS = _float_env("RANKING_W_HOURS", 40.0)
W_MCQ = _float_env("RANKING_W_MCQ", 30.0)
W_ATTENDANCE = _float_env("RANKING_W_ATTENDANCE", 30.0)

# Historical-policy settings only. Preserve pre-cutover calculations instead of
# silently applying a new scoring rule to already published weekly podiums.
MCQ_MIN_COVERAGE = _float_env("RANKING_MCQ_MIN_COVERAGE", 0.6)
MCQ_MODE = (os.environ.get("RANKING_MCQ_MODE", "auto").strip().lower() or "auto")


def _individual_mcq_from_env() -> date | None:
    """Explicit Sunday cutover; unset means rollout has NOT been armed.

    The owner removed the cohort-coverage gate. Activation still requires an
    approved future week and verified sync, not an automatic all-board rollout.
    Invalid configuration fails closed rather than silently changing old ranks.
    """
    raw = os.environ.get("RANKING_INDIVIDUAL_MCQ_FROM", "").strip()
    if not raw:
        return None
    try:
        effective = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("RANKING_INDIVIDUAL_MCQ_FROM must be an ISO Sunday date") from exc
    if raw != effective.isoformat() or effective.weekday() != 6:
        raise ValueError("RANKING_INDIVIDUAL_MCQ_FROM must be an ISO Sunday date")
    return effective


INDIVIDUAL_MCQ_FROM = _individual_mcq_from_env()


def individual_mcq_active(start: date, end: date) -> bool:
    """Policy for this as-of window, independent of peers and wall-clock time.

    Historical weekly windows ending before cutover retain their old policy.
    Monthly/overall live views use the policy of their as-of week, matching the
    weekly live board. They must not be used to regenerate published artifacts.
    """
    return bool(end >= start and INDIVIDUAL_MCQ_FROM is not None
                and week_start(end) >= INDIVIDUAL_MCQ_FROM)


def mcq_policy_metadata(start: date, end: date) -> dict:
    individual = individual_mcq_active(start, end)
    return {
        "mcqMode": "on" if individual else MCQ_MODE,
        "mcqMinCoverage": None if individual else MCQ_MIN_COVERAGE,
        "mcqPolicy": "individual-daily-full10-v2" if individual else "legacy-coverage-v1",
        "mcqEffectiveFrom": INDIVIDUAL_MCQ_FROM.isoformat() if INDIVIDUAL_MCQ_FROM else None,
        "mcqCoverageInformational": individual,
        "mcqEligibility": "official-daily-full10" if individual else "legacy",
    }


def weights(use_mcq: bool = True) -> tuple[float, float, float]:
    """(hours, mcq, attendance) weights summing to 100.

    When MCQ is excluded the other two are scaled up, so a student who maxes the
    available components still reaches 100.
    """
    total = W_HOURS + W_ATTENDANCE + (W_MCQ if use_mcq else 0.0)
    if total <= 0:
        return 0.0, 0.0, 0.0
    scale = 100.0 / total
    return (W_HOURS * scale,
            (W_MCQ * scale) if use_mcq else 0.0,
            W_ATTENDANCE * scale)


def mcq_coverage(activities: list, start: date, end: date, floor: date | None = None) -> float:
    """Share of scored students who have any synced MCQ attempts in the window."""
    scored = [a for a in activities if expected_days(a.joined_on, start, end, floor) > 0]
    if not scored:
        return 0.0
    if individual_mcq_active(start, end):
        with_attempts = sum(any(max(start, floor or start, a.joined_on or start, INDIVIDUAL_MCQ_FROM) <= d <= end and v[0] > 0
                                for d, v in a.verified_mcq_by_date.items()) for a in scored)
    else:
        with_attempts = sum(1 for a in scored if a.questions_attempted > 0)
    return with_attempts / len(scored)


def mcq_enabled(activities: list, start: date, end: date, floor: date | None = None) -> bool:
    """Count individual MCQ work without a cohort-participation gate.

    After approved cutover even one solver gets their existing MCQ component;
    nobody else's participation can toggle their weights. Legacy environment
    overrides are consulted only for pre-cutover / not-yet-armed calculations.
    """
    if individual_mcq_active(start, end):
        return True
    if MCQ_MODE == "on":
        return True
    if MCQ_MODE == "off":
        return False
    return mcq_coverage(activities, start, end, floor) >= MCQ_MIN_COVERAGE

# Same default as the tracker's TRACKER_HISTORY_FLOOR; callers normally pass the
# tracker's own value in so the two can never drift apart.
DEFAULT_HISTORY_FLOOR = _date_env("TRACKER_HISTORY_FLOOR", "2026-09-28")

# MCQ volume gates: accuracy alone must not reward a single lucky question.
MIN_QUESTIONS = {"weekly": 20, "monthly": 80}
MIN_QUESTIONS_PER_WEEK = 20

PERIODS = ("overall", "weekly", "monthly")


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------


@dataclass
class StudentActivity:
    """Per-student inputs for one period. Dates are inclusive."""

    student_id: str
    name: str = ""
    batch: str = ""
    group: str = ""
    attempt: str = ""
    joined_on: date | None = None

    hours_by_date: dict = field(default_factory=dict)   # date -> hours
    submitted_dates: set = field(default_factory=set)   # dates with a submission
    questions_attempted: int = 0
    questions_correct: int = 0
    verified_mcq_by_date: dict = field(default_factory=dict)


@dataclass
class Ranking:
    student_id: str
    name: str
    batch: str
    group: str
    rank: int
    score: float
    hours: float
    hours_per_day: float
    accuracy: float
    attendance_rate: float
    submitted_days: int
    expected_days: int
    is_active: bool
    mcq_used: bool = True
    components: list = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    not_ranked_reason: str | None = None


# ---------------------------------------------------------------------------
# Periods and expected days
# ---------------------------------------------------------------------------


def period_window(period: str, today: date, floor: date | None = None) -> tuple[date, date]:
    """Window for a period, in IST dates. `today` is inclusive.

    "weekly" opens on Sunday - see week_window. Late Sunday fills therefore land in
    the week that is still running instead of falling behind the board.
    """
    floor = floor or DEFAULT_HISTORY_FLOOR
    if period == "weekly":
        return week_start(today), today
    if period == "monthly":
        return today.replace(day=1), today
    return min(floor, today), today


def expected_days(joined_on: date | None, start: date, end: date, floor: date | None = None) -> int:
    """Days the student was expected to submit inside [start, end].

    Encodes the deployed tracker semantics: a global floor (28 Sep 2026) plus the
    student's own joining date, whichever is later.
    """
    if end < start:
        return 0
    floor = floor or DEFAULT_HISTORY_FLOOR
    effective_start = max(start, floor)
    if joined_on is not None:
        effective_start = max(effective_start, joined_on)
    if effective_start > end:
        return 0
    return (end - effective_start).days + 1


def reference_hours(start: date, end: date, floor: date | None = None) -> float:
    """Uniform effort yardstick shared by every student in the segment."""
    floor = floor or DEFAULT_HISTORY_FLOOR
    effective_start = max(start, floor)
    if end < effective_start:
        return 0.0
    return DAILY_REFERENCE_HOURS * ((end - effective_start).days + 1)


def _min_questions(period: str, start: date, end: date, floor: date | None = None) -> int:
    if period in MIN_QUESTIONS:
        return MIN_QUESTIONS[period]
    floor = floor or DEFAULT_HISTORY_FLOOR
    weeks = max(1, ((end - max(start, floor)).days + 1) // 7)
    return MIN_QUESTIONS_PER_WEEK * weeks


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_student(
    activity: StudentActivity,
    start: date,
    end: date,
    period: str = "weekly",
    floor: date | None = None,
    use_mcq: bool = True,
) -> Ranking:
    """Composite score for one student over one window. Rank is assigned later."""
    exp_days = expected_days(activity.joined_on, start, end, floor)

    hours = round(sum(h for d, h in (activity.hours_by_date or {}).items() if start <= d <= end), 2)
    submitted = {d for d in (activity.submitted_dates or set()) if start <= d <= end}

    base = dict(
        student_id=activity.student_id,
        name=activity.name,
        batch=activity.batch,
        group=activity.group,
        hours=hours,
        submitted_days=len(submitted),
        expected_days=exp_days,
    )

    if exp_days == 0:
        return Ranking(
            **base, rank=0, score=0.0, hours_per_day=0.0, accuracy=0.0,
            attendance_rate=0.0, is_active=False, mcq_used=use_mcq,
            components=(["hours", "mcq", "attendance"] if use_mcq else ["hours", "attendance"]),
            breakdown={},
            not_ranked_reason="Not ranked - not yet enrolled in this period",
        )

    ref_hours = reference_hours(start, end, floor)
    hours_score = min(1.0, hours / ref_hours) if ref_hours else 0.0

    attempted, correct = activity.questions_attempted, activity.questions_correct
    if individual_mcq_active(start, end):
        lower = max(start, floor or start, activity.joined_on or start, INDIVIDUAL_MCQ_FROM)
        selected = [v for d, v in activity.verified_mcq_by_date.items() if lower <= d <= end]
        attempted = sum(v[0] for v in selected); correct = sum(v[1] for v in selected)
    accuracy = 100.0 * correct / attempted if attempted else 0.0
    gate = min(1.0, attempted / _min_questions(period, start, end, floor))
    mcq_score = (accuracy / 100.0) * gate

    attendance_rate = len(submitted) / exp_days
    attendance_score = min(1.0, attendance_rate)

    w_hours, w_mcq, w_attendance = weights(use_mcq)
    total = w_hours * hours_score + w_mcq * mcq_score + w_attendance * attendance_score

    return Ranking(
        **base,
        rank=0,  # assigned by rank_segments()
        score=round(total, 1),
        hours_per_day=round(hours / exp_days, 2),
        accuracy=round(accuracy, 1),
        attendance_rate=round(attendance_rate, 4),
        is_active=bool(submitted or hours or activity.questions_attempted),
        mcq_used=use_mcq,
        components=(["hours", "mcq", "attendance"] if use_mcq else ["hours", "attendance"]),
        breakdown={
            "hoursScore": round(w_hours * hours_score, 1),
            "mcqScore": round(w_mcq * mcq_score, 1),
            "attendanceScore": round(w_attendance * attendance_score, 1),
        },
    )


# ---------------------------------------------------------------------------
# Unique ranks inside a segment
# ---------------------------------------------------------------------------


def sort_key(r: Ranking):
    """Deterministic total order -- equal rows can never reshuffle between reads.

    score -> accuracy -> attendance -> hours -> student id.
    """
    return (-r.score, -r.accuracy, -r.attendance_rate, -r.hours, r.student_id)


def rank_segment(rankings: list) -> list:
    """Assign unique 1..N ranks. Students not yet enrolled keep rank 0."""
    eligible = [r for r in rankings if r.not_ranked_reason is None]
    ineligible = [r for r in rankings if r.not_ranked_reason is not None]
    ordered = sorted(eligible, key=sort_key)
    for i, row in enumerate(ordered, start=1):
        row.rank = i
    return ordered + sorted(ineligible, key=lambda r: r.student_id)


SEGMENT_MODES = ("batch", "group", "batch_group")


def segment_key(activity, segment_by: str) -> str:
    """The board a student belongs to.

    "batch" and "group" are the single-attribute views. "batch_group" is the one the
    owner asked for on 18-Oct (chocolates go to the top 3 of each group inside a batch):
    the key is "<batch> · <bucket>", where the bucket comes from the shared sheet rule
    (group_bucket), so `Both` is its own board and never a union, and a student the
    sheet cannot place lands in "(no group set)" instead of being ranked in a group
    they are not in.
    """
    if segment_by == "batch_group":
        batch = (getattr(activity, "batch", "") or "").strip() or "(no batch)"
        bucket = bucket_of(getattr(activity, "group", ""))
        return f"{batch} · {bucket}" if bucket else f"{batch} · (no group set)"
    return (getattr(activity, segment_by, "") or "").strip() or "(unassigned)"


def rank_segments(
    activities: list,
    start: date,
    end: date,
    period: str = "weekly",
    segment_by: str = "batch",
    floor: date | None = None,
) -> dict:
    """One ranked list per segment. segment_by is 'batch', 'group' or 'batch_group'.

    In the individual policy MCQ counts in every segment regardless of coverage,
    with the unchanged hours/MCQ/attendance weights. Historical windows keep the
    legacy rule. Coverage remains informational for the new policy.
    """
    buckets: dict = {}
    for activity in activities:
        key = segment_key(activity, segment_by)
        buckets.setdefault(key, []).append(activity)
    ranked = {}
    for key, members in sorted(buckets.items()):
        use_mcq = mcq_enabled(members, start, end, floor)
        ranked[key] = rank_segment(
            [score_student(a, start, end, period, floor, use_mcq) for a in members]
        )
    return ranked


def rank_lookup(rows: list) -> dict:
    """student_id -> rank, from a ranked list."""
    return {row.student_id: row.rank for row in rows}
