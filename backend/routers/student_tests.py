"""Student-facing side of mentor tests — the missing delivery channel.

The dashboard can now create and publish a test (``mentor_tests``), but nothing
carries it to a student and nothing carries the attempt back:

* student app  →  had ``web-tests.js`` as an empty engine (``UMP_WEB_TESTS = []``)
  because there was no endpoint to ask for papers or to submit them.
* mentor dashboard → Tests page reads ``analytics_test_history``, which the
  student app never wrote to (no ``/api/test-history/sync`` call anywhere).

This router closes both halves with three student-authenticated calls
(studentId + password, same pattern as ``/api/student-attempts/*`` — so the
frozen APK, which loads this web app, needs no rebuild):

* ``POST /api/student-tests/list``     → published tests for this student
* ``POST /api/student-tests/paper``    → the question paper (deterministic per
  test + student, sampled from the published content bank)
* ``POST /api/student-tests/submit``   → server-side grading; the attempt is
  written to BOTH ``analytics_test_history`` (what the mentor Tests page reads)
  and ``student_mcq_attempts`` with kind ``mentor-test`` (what MCQ Scores reads)

Everything is additive: if the student app never calls these, nothing changes.
"""
from __future__ import annotations


import hashlib
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse, quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from db import (
    ANALYTICS_TEST_HISTORY,
    CONTENT_QUESTIONS,
    MENTOR_TESTS,
    STUDENT_ACCOUNTS,
    STUDENT_MCQ_ATTEMPTS,
    get_db,
)
from routers import access_events as access_lib
from routers.student_attempts import _validate_existing_student_login

router = APIRouter(prefix="/api/student-tests", tags=["student-tests"])

APPROVED_SET = ("approved", "release_candidate", "published")
MAX_QUESTIONS = 100
LETTERS = "ABCDEFGH"


class StudentLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    studentId: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class PaperRequest(StudentLogin):
    testId: str = Field(min_length=2, max_length=96)


class SubmitRequest(PaperRequest):
    answers: dict[str, str] = Field(default_factory=dict)
    durationSeconds: int = Field(default=0, ge=0, le=24 * 3600)
    # paper-test ke liye: student apne marks khud bharta hai (answer sheet +
    # marking scheme dekh kar) — wahi TestHistoryItem.selfMarks ban jaata hai.
    selfMarks: Optional[float] = Field(default=None, ge=0, le=1000)
    remarks: Optional[str] = Field(default=None, max_length=500)
    answerUrl: Optional[str] = Field(default=None, max_length=1000)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def option_index(value) -> Optional[int]:
    """'B' | 2 | '2' → 2 ; unknown → None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().upper()
    if len(text) == 1 and text in LETTERS:
        return LETTERS.index(text)
    if text.isdigit():
        return int(text)
    return None


def option_id(index: int) -> str:
    return LETTERS[index] if 0 <= index < len(LETTERS) else str(index)


def pick_questions(rows: list[dict], want: int, seed: str) -> list[dict]:
    """Deterministic sample: same test + same student → same paper on reload.

    ``rows`` must already be candidate questions; sorting by id first keeps the
    result stable regardless of Mongo's natural order.
    """
    ordered = sorted(rows, key=lambda r: str(r.get("id") or ""))
    if want <= 0 or want >= len(ordered):
        return ordered
    return random.Random(seed).sample(ordered, want)


def public_question(row: dict, marks: float) -> dict:
    options = []
    for i, opt in enumerate(row.get("options") or []):
        if isinstance(opt, dict):
            options.append({"id": str(opt.get("id") or option_id(i)), "text": str(opt.get("text") or "")})
        else:
            options.append({"id": option_id(i), "text": str(opt)})
    return {
        "id": str(row.get("id") or ""),
        "prompt": row.get("prompt") or "",
        "options": options,
        "marks": marks,
        "subject": row.get("subject") or "",
        "chapter": row.get("chapter") or row.get("chapterTitle") or "",
        "difficulty": row.get("difficulty") or "",
    }


def correct_index(row: dict) -> Optional[int]:
    """Works for both bank shapes: ``correctOptionId`` ('B') and ``answer`` (1)."""
    if row.get("correctOptionId") not in (None, ""):
        return option_index(row.get("correctOptionId"))
    return option_index(row.get("answer"))


def grade(rows: list[dict], answers: dict, total_marks: Optional[int]) -> dict:
    """Server-side marking. Returns score/total/pct + per-question review."""
    n = len(rows)
    review = []
    correct_count = 0
    for row in rows:
        qid = str(row.get("id") or "")
        answer = correct_index(row)
        selected = option_index(answers.get(qid))
        is_correct = answer is not None and selected == answer
        if is_correct:
            correct_count += 1
        options = []
        for i, opt in enumerate(row.get("options") or []):
            options.append(str(opt.get("text")) if isinstance(opt, dict) else str(opt))
        review.append({
            "id": qid,
            "prompt": row.get("prompt") or "",
            "options": options,
            "answer": answer,
            "selected": selected,
            "correct": is_correct,
            "explanation": row.get("explanation") or "",
            "subject": row.get("subject") or "",
            "chapter": row.get("chapter") or row.get("chapterTitle") or "",
            "difficulty": row.get("difficulty") or "",
        })
    if total_marks and n:
        score = round(correct_count * float(total_marks) / n, 2)
        total = float(total_marks)
    else:
        score, total = correct_count, n
    pct = int(round((score / total) * 100)) if total else None
    return {"score": score, "total": total, "scorePct": pct, "correctCount": correct_count, "review": review}


def paper_submission(test: dict, self_marks: Optional[float], remarks: Optional[str], answerUrl: Optional[str]) -> dict:
    total = float(test.get("total_marks") or 0)
    if self_marks is None:
        return {"error": "Marks obtained bharo (answer sheet check karne ke baad)"}
    if total > 0 and float(self_marks) > total:
        return {"error": f"Marks {total:g} se zyada nahi ho sakte"}
    score = float(self_marks)
    pct = int(round((score / total) * 100)) if total > 0 else None
    return {
        "score": score,
        "total": total,
        "scorePct": pct,
        "selfMarks": True,
        "remarks": (remarks or "").strip()[:500],
        "answerUrl": answerUrl or "",
    }


def window_state(test: dict, now_ms: int) -> str:
    """open | upcoming | closed — plain string compare, dates are ISO-ish.

    A student who was locked out during the window is handed a shifted copy of the
    test (access_lib.shifted_view) instead of a second rule here, so the list, the
    paper and the makeup flag can never disagree about their deadline."""
    start = test.get("window_start")
    end = test.get("window_end")
    now_iso = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")
    if start and now_iso < str(start)[:16]:
        return "upcoming"
    if end and now_iso > str(end)[:16]:
        return "closed"
    return "open"


_DRIVE_FILE_PATTERNS = (
    re.compile(r"https?://drive\.google\.com/file/d/([^/?#]+)"),
    re.compile(r"https?://drive\.google\.com/open\?id=([^&#]+)"),
    re.compile(r"https?://drive\.google\.com/uc\?(?:[^#]*&)?id=([^&#]+)"),
)


def direct_download_url(url) -> str:
    """Drive *share* links hand raw fetchers an HTML viewer page, which the
    in-app PDF viewer rejects with 'Invalid PDF structure' (web browsers never
    noticed because they render Drive's own viewer). Rewrite share links to
    the direct-download endpoint that serves the actual bytes."""
    if not url:
        return url or ""
    text = str(url)
    for pat in _DRIVE_FILE_PATTERNS:
        m = pat.search(text)
        if m:
            resource_key = parse_qs(urlparse(text).query).get("resourcekey", [""])[0]
            suffix = "&resourcekey=" + quote(resource_key, safe="") if resource_key else ""
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}{suffix}"
    return text


def matches_target(test: dict, account: dict) -> bool:
    """Batch/group targeting — blank on the test means 'everyone'."""
    if test.get("exclusiveGroup"):
        from routers.mentor_workspace import group_key
        if not test.get("batch") or test.get("batch") != account.get("batch"):
            return False
        wanted = group_key(test.get("group"))
        return wanted != "unknown" and wanted == group_key(account.get("group"))
    want_batch = (test.get("batch") or "").strip().lower()
    want_group = (test.get("group") or "").strip().lower()
    have_batch = str(account.get("batch") or "").strip().lower()
    have_group = str(account.get("group") or "").strip().lower()
    if want_batch and want_batch not in ("all batches", "all", "both"):
        if want_batch != have_batch:
            return False
    if want_group and want_group not in ("both", "both groups", "all"):
        if want_group != have_group:
            return False
    return True


# --------------------------------------------------------------------------- #
# db helpers
# --------------------------------------------------------------------------- #
def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _account(db, student_id: str) -> dict:
    doc = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id}) or {}
    if not doc:
        doc = await db["dashboard_students"].find_one({"studentId": student_id}) or {}
    return doc


async def _candidates(db, test: dict) -> list[dict]:
    """Published questions for the test's subject/chapters."""
    query: dict = {"status": {"$in": list(APPROVED_SET)}}
    subject = (test.get("subject") or "").strip()
    if subject and subject.lower() != "full syllabus":
        query["subject"] = subject
    query["id"] = {"$exists": True}
    rows: list[dict] = []
    async for q in db[CONTENT_QUESTIONS].find(query).limit(5000):
        rows.append(q)
    chapters = [c.strip().lower() for c in (test.get("chapters") or []) if str(c).strip()]
    if chapters:
        narrowed = [
            q for q in rows
            if str(q.get("chapter") or "").strip().lower() in chapters
            or str(q.get("chapterTitle") or "").strip().lower() in chapters
            or any(c in str(q.get("chapter") or "").strip().lower() for c in chapters)
        ]
        if narrowed:
            rows = narrowed
    return rows


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@router.post("/list")
async def list_tests(body: StudentLogin):
    """Published tests for this student, newest first, with attempt status."""
    sid = body.studentId.strip().upper()
    
    await _validate_existing_student_login(sid, body.password)
    db = get_db()
    account = await _account(db, sid)
    now = _now_ms()

    done: dict[str, dict] = {}
    async for row in db[ANALYTICS_TEST_HISTORY].find({"studentId": sid}):
        tid = str(row.get("testId") or "")
        if tid and int(row.get("at_ms") or 0) >= int(done.get(tid, {}).get("at_ms") or 0):
            done[tid] = row

    # One read of this student's lockout timeline, then a per-test credit: a window
    # that closed while their access was OFF must not stay closed after the mentor
    # unlocks them (owner decision 15-Oct-2026: "access on karte hi unhe dikhna chahiye").
    lockouts = await access_lib.off_intervals(db, sid, account)
    items = []
    async for test in db[MENTOR_TESTS].find({"published": True}).sort("createdAt", -1).limit(200):
        if not matches_target(test, account):
            continue
        tid = test.get("testId")
        previous = done.get(tid)
        extra = access_lib.credit_for(lockouts, test)
        view = access_lib.shifted_view(test, extra)
        items.append({
            "testId": tid,
            "title": test.get("title"),
            "kind": test.get("kind") or "mcq-test",
            "subject": test.get("subject") or "",
            "group": test.get("group") or "",
            "batch": test.get("batch") or "",
            "test_date": test.get("test_date") or "",
            "window_start": view.get("window_start") or "",
            "window_end": view.get("window_end") or "",
            "makeup": bool(extra),
            "makeupMinutes": int(extra),
            "durationMinutes": test.get("duration_minutes") or 0,
            "maxMarks": test.get("total_marks") or 0,
            "questionCount": test.get("question_count") or 0,
            "instructions": test.get("instructions") or "",
            "hasAnswerSheet": bool(test.get("answer_sheet_url") or test.get("answer_sheet_text")),
            "hasMarkingScheme": bool(test.get("marking_scheme")),
            "hasPaper": bool(test.get("paper_url")),
            "status": window_state(view, now),
            "attempted": bool(previous),
            "lastScore": previous.get("score") if previous else None,
            "lastTotal": previous.get("total") if previous else None,
            "lastAt": previous.get("at") if previous else None,
        })
    return {"ok": True, "studentId": sid, "tests": items, "batch": account.get("batch") or ""}


@router.post("/paper")
async def paper(body: PaperRequest):
    """The question paper for one test — answers stay on the server."""
    sid = body.studentId.strip().upper()
    
    await _validate_existing_student_login(sid, body.password)
    db = get_db()
    test = await db[MENTOR_TESTS].find_one({"testId": body.testId, "published": True})
    if not test:
        raise HTTPException(status_code=404, detail="Test nahi mila ya abhi publish nahi hua")

    account = await _account(db, sid)
    if not matches_target(test, account):
        raise HTTPException(status_code=403, detail="Ye test aapke batch/group ke liye nahi hai")

    view = access_lib.shifted_view(test, await access_lib.makeup_minutes(db, sid, test, account))
    state = window_state(view, _now_ms())
    if state == "closed":
        raise HTTPException(status_code=409, detail="Is test ki window band ho gayi")

    if (test.get("kind") or "mcq-test") == "paper-test":
        # Paper test: app me solve karne ke liye questions nahi hote — student
        # khud paper karta hai, phir answer sheet + marking scheme se check karke
        # apne marks bharta hai.
        # NOTE: payload is mirrored under BOTH `test` and `meta` keys. `test` is
        # what the web app and v45+ native read; `meta` exists so the shipped
        # v1.15.0/44 APK (which parsed `data.meta`) also receives paperUrl
        # without needing an app update. Additive only - safe for all clients.
        paper_meta = {
            "testId": test.get("testId"),
            "title": test.get("title"),
            "kind": "paper-test",
            "subject": test.get("subject") or "",
            "durationMinutes": test.get("duration_minutes") or 0,
            "maxMarks": test.get("total_marks") or 0,
            "questionCount": test.get("question_count") or 0,
            "instructions": test.get("instructions") or "",
            "paperUrl": direct_download_url(test.get("paper_url") or ""),
            "answerSheetUrl": direct_download_url(test.get("answer_sheet_url") or ""),
            "answerSheetText": test.get("answer_sheet_text") or "",
            "markingScheme": test.get("marking_scheme") or "",
            "markingSchemeUrl": direct_download_url(test.get("marking_scheme_url") or ""),
            "status": state,
        }
        return {
            "ok": True,
            "selfEvaluate": True,
            "test": paper_meta,
            "meta": paper_meta,
            "questions": [],
        }

    rows = await _candidates(db, test)
    if not rows:
        raise HTTPException(status_code=409, detail="Is test ke liye abhi published questions nahi hain")

    want = int(test.get("question_count") or 0) or min(10, len(rows))
    want = max(1, min(want, MAX_QUESTIONS, len(rows)))
    chosen = pick_questions(rows, want, f"{body.testId}:{sid}")
    marks_each = (float(test.get("total_marks")) / len(chosen)) if test.get("total_marks") else 1.0

    return {
        "ok": True,
        "test": {
            "testId": test.get("testId"),
            "title": test.get("title"),
            "kind": test.get("kind") or "mcq-test",
            "subject": test.get("subject") or "",
            "durationMinutes": test.get("duration_minutes") or 0,
            "maxMarks": test.get("total_marks") or len(chosen),
            "instructions": test.get("instructions") or "",
            "status": state,
        },
        "questions": [public_question(row, round(marks_each, 2)) for row in chosen],
    }


@router.post("/submit")
async def submit(body: SubmitRequest):
    """Grade on the server, then write the attempt for mentor + student views."""
    sid = body.studentId.strip().upper()
    
    await _validate_existing_student_login(sid, body.password)
    db = get_db()
    test = await db[MENTOR_TESTS].find_one({"testId": body.testId, "published": True})
    if not test:
        raise HTTPException(status_code=404, detail="Test nahi mila ya abhi publish nahi hua")

    kind = test.get("kind") or "mcq-test"
    now_ms = _now_ms()
    account = await _account(db, sid)
    attempt_id = f"mentor-test:{body.testId}:{sid}"
    # /submit has no deadline of its own (the paper is the gate), so an attempt can
    # legitimately land after the window. When it is covered by granted makeup days,
    # record that: the mentor's analysis must tell "late with credit" from "on time".
    makeup_minutes = await access_lib.makeup_minutes(db, sid, test, account)
    makeup_attempt = bool(makeup_minutes) and window_state(test, now_ms) == "closed"

    if kind == "paper-test":
        # Self-evaluation: student ke bataye marks hi final maane jaate hain.
        result = paper_submission(test, body.selfMarks, body.remarks, body.answerUrl)
        if result.get("error"):
            raise HTTPException(status_code=422, detail=result["error"])
        history = {
            "id": attempt_id,
            "testId": body.testId,
            "studentId": sid,
            "studentName": account.get("studentName") or sid,
            "batch": account.get("batch") or "",
            "kind": "paper-test",
            "title": test.get("title"),
            "subject": test.get("subject") or "",
            "at": _now_iso(),
            "at_ms": now_ms,
            "score": result["score"],
            "total": result["total"],
            "scorePct": result["scorePct"],
            "selfMarks": True,
            "remarks": result["remarks"],
            "answerUrl": result.get("answerUrl", ""),
            "makeup": makeup_attempt,
        }
        await db[ANALYTICS_TEST_HISTORY].update_one(
            {"studentId": sid, "id": attempt_id}, {"$set": history}, upsert=True
        )
        return {
            "ok": True,
            "kind": "paper-test",
            "testId": body.testId,
            "title": test.get("title"),
            "score": result["score"],
            "total": result["total"],
            "scorePct": result["scorePct"],
            "selfMarks": True,
            "remarks": result["remarks"],
            "answerUrl": result.get("answerUrl", ""),
            "message": "Marks mentor ko bhej diye gaye",
        }

    rows = await _candidates(db, test)
    if not rows:
        raise HTTPException(status_code=409, detail="Is test ke liye published questions nahi hain")
    want = int(test.get("question_count") or 0) or min(10, len(rows))
    want = max(1, min(want, MAX_QUESTIONS, len(rows)))
    chosen = pick_questions(rows, want, f"{body.testId}:{sid}")

    if not body.answers:
        raise HTTPException(status_code=422, detail="Kam se kam ek question ka jawab chuno")
    result = grade(chosen, body.answers, test.get("total_marks"))

    history = {
        "id": attempt_id,
        "testId": body.testId,
        "studentId": sid,
        "studentName": account.get("studentName") or sid,
        "batch": account.get("batch") or "",
        "kind": "mcq-test",
        "title": test.get("title"),
        "subject": test.get("subject") or "",
        "at": _now_iso(),
        "at_ms": now_ms,
        "score": result["score"],
        "total": result["total"],
        "scorePct": result["scorePct"],
        "selfMarks": False,
        "makeup": makeup_attempt,
    }
    await db[ANALYTICS_TEST_HISTORY].update_one(
        {"studentId": sid, "id": attempt_id}, {"$set": history}, upsert=True
    )

    attempt_doc = {
        "studentId": sid,
        "attemptId": attempt_id,
        "kind": "mentor-test",
        "group": account.get("group") or "",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "completedAt": now_ms,
        "durationSeconds": body.durationSeconds,
        "questionIds": [str(r.get("id")) for r in chosen],
        "answers": body.answers,
        "review": result["review"],
        "score": result["score"],
        "total": result["total"],
        "config": {"testId": body.testId, "title": test.get("title"), "subject": test.get("subject") or ""},
    }
    await db[STUDENT_MCQ_ATTEMPTS].update_one(
        {"studentId": sid, "attemptId": attempt_id}, {"$set": attempt_doc}, upsert=True
    )

    return {
        "ok": True,
        "testId": body.testId,
        "title": test.get("title"),
        "score": result["score"],
        "total": result["total"],
        "scorePct": result["scorePct"],
        "correctCount": result["correctCount"],
        "questionCount": len(chosen),
        "review": result["review"],
    }
