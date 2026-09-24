"""Revision dates from marked receipt answers.

Groq marks the written answer. It does not pick the date. The date follows the
rule already fixed with the mentor:

  below 40%  weak     1 day
  40-70%     average  3 days
  70-85%     strong   7 days
  above 85%  strong   14 days

A wrong answer given with high confidence, or the same miss twice, comes back
in 1 day. Two strong answers in a row wait 21 days. A missing mark is not saved.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from db import get_db

router = APIRouter(tags=["revision"])

PLAN = "revision_plan"
IST = ZoneInfo("Asia/Kolkata")


def _today():
    return datetime.now(IST).date()


def _now() -> str:
    return datetime.now(IST).isoformat()


def _key(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return text[:120] or "chapter"


def strength_label(accuracy: float) -> str:
    if accuracy >= 70:
        return "strong"
    if accuracy >= 40:
        return "average"
    return "weak"


def schedule_days(accuracy: float, *, high_confidence_wrong: bool = False, repeated_mistake: bool = False, perfect_twice: bool = False):
    if high_confidence_wrong:
        return 1, "wrong-high-confidence"
    if repeated_mistake and accuracy < 70:
        return 1, "repeated-mistake"
    if perfect_twice:
        return 21, "perfect-twice"
    if accuracy > 85:
        return 14, "above-85"
    if accuracy >= 70:
        return 7, "70-85"
    if accuracy >= 40:
        return 3, "40-70"
    return 1, "below-40"


def reminder_text(concept: str, strength: str, due_on: str) -> str:
    return (
        f"Revise {concept} on {due_on}. "
        f"Your receipt answers put this chapter at {strength}. "
        "Do that revision on the timer, then answer the receipt questions again."
    )


def _student_id(value: str) -> str:
    value = re.sub(r"\s+", "", str(value or "")).upper()
    match = re.match(r"^UMP(\d+)$", value)
    if match:
        return "UMP" + match.group(1).zfill(4)
    return value


def _public(row: dict) -> dict:
    return {
        "concept": row.get("concept") or "",
        "subject": row.get("subject") or "",
        "chapterId": row.get("chapterId") or "",
        "strength": row.get("strength") or "weak",
        "accuracy": row.get("accuracy") or 0,
        "attempts": row.get("attempts") or 0,
        "dueOn": row.get("dueOn") or "",
        "intervalDays": row.get("intervalDays") or 0,
        "reason": row.get("reason") or "",
        "reminder": row.get("reminder") or "",
        "updatedAt": row.get("updatedAt") or "",
    }


async def record_written_mark(*, student_id: str, concept: str, subject: str = "", chapter_id: str = "", score: float = 0, confidence: str = "") -> dict:
    """Save one marked answer and set the next revision date. Score is 0-10."""
    sid = _student_id(student_id)
    name = re.sub(r"\s+", " ", str(concept or subject or "Chapter")).strip()[:160]
    if not sid or not name:
        return {}
    score = max(0.0, min(10.0, float(score or 0)))
    accuracy_now = score * 10
    db = get_db()
    key = _key(name)
    previous = await db[PLAN].find_one({"studentId": sid, "conceptKey": key}, {"_id": 0}) or {}
    attempts = int(previous.get("attempts") or 0) + 1
    score_sum = float(previous.get("scoreSum") or 0) + score
    accuracy = (score_sum / attempts) * 10
    confident = str(confidence or "").strip().lower() == "high"
    high_confidence_wrong = confident and accuracy_now < 40
    repeated = accuracy_now < 40 and float(previous.get("lastAccuracy") or 100) < 40
    consecutive_high = int(previous.get("consecutiveHigh") or 0)
    consecutive_high = consecutive_high + 1 if score >= 9 else 0
    perfect_twice = consecutive_high >= 2
    days, reason = schedule_days(
        accuracy,
        high_confidence_wrong=high_confidence_wrong,
        repeated_mistake=repeated,
        perfect_twice=perfect_twice,
    )
    strength = strength_label(accuracy)
    due_on = (_today() + timedelta(days=days)).isoformat()
    doc = {
        "studentId": sid,
        "conceptKey": key,
        "concept": name,
        "subject": str(subject or previous.get("subject") or "").strip(),
        "chapterId": str(chapter_id or previous.get("chapterId") or "").strip(),
        "attempts": attempts,
        "scoreSum": score_sum,
        "lastScore": score,
        "lastAccuracy": accuracy_now,
        "accuracy": round(accuracy, 1),
        "consecutiveHigh": consecutive_high,
        "strength": strength,
        "dueOn": due_on,
        "intervalDays": days,
        "reason": reason,
        "reminder": reminder_text(name, strength, due_on),
        "updatedAt": _now(),
    }
    await db[PLAN].update_one({"studentId": sid, "conceptKey": key}, {"$set": doc}, upsert=True)
    return _public(doc)


async def due_revisions(student_id: str) -> list:
    sid = _student_id(student_id)
    if not sid:
        return []
    today = _today().isoformat()
    rows = await get_db()[PLAN].find({"studentId": sid, "dueOn": {"$lte": today}}, {"_id": 0}).to_list(40)
    rows.sort(key=lambda row: (row.get("dueOn") or "", row.get("concept") or ""))
    return [_public(row) for row in rows]


@router.get("/api/revision/plan")
async def revision_plan(studentId: str = Query(min_length=1, max_length=64)):
    sid = _student_id(studentId)
    if not sid:
        raise HTTPException(status_code=400, detail="Student ID is required.")
    rows = await get_db()[PLAN].find({"studentId": sid}, {"_id": 0}).sort("dueOn", 1).to_list(80)
    return {"studentId": sid, "chapters": [_public(row) for row in rows], "due": await due_revisions(sid)}
