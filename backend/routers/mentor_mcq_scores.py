"""MCQ Scores for the mentor dashboard.

The dashboard's MCQ Scores page had no endpoint: the browser kept hitting
``GET /api/mentor/mcq-scores`` and getting a 404 even though the raw data has
been syncing all along. Student MCQ attempts (daily sets, practice and mentor
tests) land in ``student_mcq_attempts`` via ``/api/student-attempts/sync`` and
the mentor-test submit path, so the mentor-side aggregate is a pure read over
that collection - no new writes, no new storage.

``GET /api/mentor/mcq-scores``
    ?range=7|30|90|all   window over ``completedAt`` (default 30)
    ?q=<text>            filter by student name / id / batch (substring)
    ?kind=daily|practice|mentor-test   optional source filter

Returns ``{ stats, students, range }`` where each student row carries
attempts, marks (sum of correct), questionsSolved (sum of questions faced),
average and best (percent per attempt) and the ISO timestamp of the last
attempt, so the page can render the table and the four stat cards without a
second round-trip.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import require_mentor
from db import STUDENT_ACCOUNTS, STUDENT_MCQ_ATTEMPTS, get_db
from routers.student_auth import normalize_student_id

router = APIRouter(prefix="/api/mentor", tags=["mentor-mcq-scores"])

RANGE_DAYS = {"7": 7, "30": 30, "90": 90}
VALID_KINDS = ("daily", "practice", "mentor-test")


def _iso_from_ms(ms: Optional[int]) -> Optional[str]:
    if not ms or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _clamp(score: int, total: int) -> int:
    return max(0, min(score, total))


@router.get("/mcq-scores")
async def mcq_scores(
    range: str = Query(default="30", alias="range"),
    q: str = Query(default=""),
    kind: Optional[str] = Query(default=None),
    claims: dict = Depends(require_mentor),
):
    """Per-student MCQ aggregate + cohort stats over a time window."""
    db = get_db()

    cutoff_ms = None
    days = RANGE_DAYS.get(str(range).strip())
    if days:
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )

    query: dict = {}
    if cutoff_ms:
        query["completedAt"] = {"$gte": cutoff_ms}
    if kind in VALID_KINDS:
        query["kind"] = kind

    # studentId -> account (name/batch/group) for the join + search filter
    accounts: dict = {}
    async for acc in db[STUDENT_ACCOUNTS].find(
        {}, {"studentId": 1, "name": 1, "batch": 1, "group": 1}
    ):
        sid = normalize_student_id(acc.get("studentId") or "")
        if sid:
            accounts[sid] = acc

    per: dict = {}
    async for row in db[STUDENT_MCQ_ATTEMPTS].find(
        query, {"studentId": 1, "score": 1, "total": 1, "completedAt": 1}
    ):
        sid = normalize_student_id(row.get("studentId") or "")
        if not sid:
            continue
        try:
            total = int(row.get("total") or 0)
            score = int(row.get("score") or 0)
            completed_at = int(row.get("completedAt") or 0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        entry = per.setdefault(
            sid, {"attempts": 0, "marks": 0, "questions": 0, "pcts": [], "last": 0}
        )
        correct = _clamp(score, total)
        entry["attempts"] += 1
        entry["marks"] += correct
        entry["questions"] += total
        entry["pcts"].append(round(100.0 * correct / total, 2))
        if completed_at > entry["last"]:
            entry["last"] = completed_at

    needle = (q or "").strip().lower()
    students = []
    all_pcts = []
    for sid, entry in per.items():
        acc = accounts.get(sid, {})
        name = acc.get("name") or sid
        batch = acc.get("batch") or ""
        if needle and not (
            needle in str(name).lower()
            or needle in sid.lower()
            or needle in batch.lower()
        ):
            continue
        pcts = entry["pcts"]
        all_pcts.extend(pcts)
        students.append(
            {
                "studentId": sid,
                "name": name,
                "batch": batch,
                "group": acc.get("group") or "",
                "attempts": entry["attempts"],
                "marks": entry["marks"],
                "questionsSolved": entry["questions"],
                "average": round(sum(pcts) / len(pcts), 1) if pcts else 0.0,
                "best": max(pcts) if pcts else 0.0,
                "lastAttempt": _iso_from_ms(entry["last"]),
            }
        )

    students.sort(key=lambda r: (-r["attempts"], -r["average"], str(r["name"]).lower()))

    stats = {
        "students": len(students),
        "attempts": sum(r["attempts"] for r in students),
        "questionsSolved": sum(r["questionsSolved"] for r in students),
        "cohortAverage": round(sum(all_pcts) / len(all_pcts), 1) if all_pcts else None,
    }

    return {"stats": stats, "students": students, "range": str(range)}
