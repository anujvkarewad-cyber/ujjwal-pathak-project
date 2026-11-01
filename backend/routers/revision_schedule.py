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

from routers.dashboard_access import dashboard_student, own_payload
from fastapi import APIRouter, Depends, HTTPException, Query

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
        f"Your chapter assessment puts this chapter at {strength}. "
        "Do that revision on the timer, then assess the chapter again."
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
        "revisionKey": row.get("conceptKey") or "",
        "revisionVersion": row.get("revisionVersion", 0),
        "questionAccuracy": row.get("questionAccuracy"),
        "questionAttemptedTotal": row.get("questionAttemptedTotal", 0),
        "questionCorrectTotal": row.get("questionCorrectTotal", 0),
        "lastAssessmentSource": row.get("lastAssessmentSource") or "written-grader",
        "lastRevisionCompletedAt": row.get("lastRevisionCompletedAt"),
        "scheduledRevisionRetained": row.get("scheduledRevisionRetained", False),
    }


async def record_written_mark(*, student_id: str, concept: str, subject: str = "", chapter_id: str = "", score: float = 0, confidence: str = "", event_id: str = "", question_attempted: int = 0, question_correct: int = 0, event_meta: dict = None, expected_version=None) -> dict:
    """Shared scheduler: legacy grading + explicitly shared, idempotent summaries.

    No receipt text/audio is accepted here. All writers use a revisionVersion CAS
    so a legacy written mark cannot overwrite a simultaneous target assessment.
    """
    import hashlib
    import json
    import uuid
    from pymongo.errors import DuplicateKeyError
    sid = _student_id(student_id)
    name = re.sub(r"\s+", " ", str(concept or subject or "Chapter")).strip()[:240]
    if not sid or not name:
        return {}
    from routers.target_plans import _subject_canon
    subject = _subject_canon(subject) if subject else ''
    score = max(0.0, min(10.0, float(score or 0)))
    accuracy_now = score * 10
    event_id = event_id or 'written-' + uuid.uuid4().hex
    meta = event_meta or {'source': 'written-grader'}
    payload = {'score': score, 'confidence': confidence, 'attempted': question_attempted,
               'correct': question_correct, 'meta': meta, 'subject': subject, 'concept': name}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    event_key = hashlib.sha256(event_id.encode()).hexdigest()
    collection = get_db()[PLAN]
    key = _key(name)
    for _ in range(8):
        previous = await collection.find_one({'studentId': sid, 'conceptKey': key}) or {}
        # Reuse legacy chapters, but never combine identically named chapters in
        # different subjects. No historical row is removed/re-keyed.
        same_name = lambda value: re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()
        different_name = previous.get('concept') and same_name(previous['concept']) != same_name(name)
        different_subject = previous.get('subject') and subject and _key(_subject_canon(previous['subject'])) != _key(subject)
        if different_name or different_subject:
            key = _key(name) + ':' + hashlib.sha256((subject + '\0' + name.lower()).encode()).hexdigest()[:16]
            continue
        events = dict(previous.get('assessmentEvents') or {})
        prior = events.get(event_key)
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise HTTPException(409, 'This assessment ID was already saved with different answers.')
            return dict(_public(previous), alreadyRecorded=True)
        version = previous.get('revisionVersion', 0)
        if expected_version is not None and version != expected_version:
            raise HTTPException(409, 'This revision was already updated. Refresh the revision list.')
        attempts = int(previous.get('attempts') or 0) + 1
        score_sum = float(previous.get('scoreSum') or 0) + score
        accuracy = score_sum / attempts * 10
        last = previous.get('lastAccuracy')
        repeated = accuracy_now < 40 and last is not None and float(last) < 40
        consecutive = int(previous.get('consecutiveHigh') or 0) + 1 if score >= 9 else 0
        days, reason = schedule_days(accuracy,
            high_confidence_wrong=str(confidence).lower() == 'high' and accuracy_now < 40,
            repeated_mistake=repeated, perfect_twice=consecutive >= 2)
        strength = strength_label(accuracy)
        due = (_today() + timedelta(days=days)).isoformat()
        retained = False
        # Studying/assessing a target is NOT an explicit revision completion.
        # It may bring a review earlier, but cannot postpone an already
        # scheduled review of the same chapter, even one due in the future.
        if meta.get('kind') == 'target' and previous.get('dueOn') and previous['dueOn'] <= due:
            due = previous['dueOn']
            retained = True
        qa = int(previous.get('questionAttemptedTotal') or 0) + question_attempted
        qc = int(previous.get('questionCorrectTotal') or 0) + question_correct
        events[event_key] = {**meta, 'fingerprint': fingerprint, 'score': score,
                             'attempted': question_attempted, 'correct': question_correct,
                             'completedAt': _now(), 'nextDueOn': due}
        doc = {'studentId': sid, 'conceptKey': key, 'concept': name,
               'subject': subject or previous.get('subject') or '',
               'chapterId': chapter_id or previous.get('chapterId') or '',
               'attempts': attempts, 'scoreSum': score_sum, 'lastScore': score,
               'lastAccuracy': accuracy_now, 'accuracy': round(accuracy, 1),
               'consecutiveHigh': consecutive, 'strength': strength,
               'dueOn': due, 'intervalDays': previous.get('intervalDays', days) if retained else days,
               'assessmentIntervalDays': days, 'reason': 'existing-revision-retained' if retained else reason,
               'reminder': reminder_text(name, strength, due), 'updatedAt': _now(),
               'revisionVersion': version + 1, 'assessmentEvents': events,
               'scheduledRevisionRetained': retained,
               'questionAttemptedTotal': qa, 'questionCorrectTotal': qc,
               'questionAccuracy': round(100*qc/qa, 1) if qa else None,
               'lastAssessmentSource': meta.get('source', 'written-grader'),
               'lastRevisionCompletedAt': _now() if meta.get('kind') == 'revision' else previous.get('lastRevisionCompletedAt')}
        if previous:
            expected = version if 'revisionVersion' in previous else {'$exists': False}
            result = await collection.update_one({'_id': previous['_id'], 'revisionVersion': expected}, {'$set': doc})
            if result.matched_count:
                return _public(doc)
        else:
            doc['_id'] = 'revision:' + hashlib.sha256(f'{sid}:{key}'.encode()).hexdigest()
            try:
                await collection.insert_one(doc)
                return _public(doc)
            except DuplicateKeyError:
                continue
    raise HTTPException(409, 'A concurrent assessment changed this chapter. Please retry.')


async def due_revisions(student_id: str) -> list:
    sid = _student_id(student_id)
    if not sid:
        return []
    today = _today().isoformat()
    rows = await get_db()[PLAN].find({"studentId": sid, "dueOn": {"$lte": today}}, {"_id": 0}).to_list(40)
    rows.sort(key=lambda row: (row.get("dueOn") or "", row.get("concept") or ""))
    return [_public(row) for row in rows]


@router.get("/api/revision/plan")
async def revision_plan(studentId: str = Query(min_length=1, max_length=64), principal=Depends(dashboard_student)):
    studentId = own_payload(principal, {"studentId":studentId})["studentId"]
    sid = _student_id(studentId)
    if not sid:
        raise HTTPException(status_code=400, detail="Student ID is required.")
    rows = await get_db()[PLAN].find({"studentId": sid}, {"_id": 0}).sort("dueOn", 1).to_list(80)
    return {"studentId": sid, "chapters": [_public(row) for row in rows], "due": await due_revisions(sid)}
