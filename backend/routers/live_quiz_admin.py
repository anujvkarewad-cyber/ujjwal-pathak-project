"""Mentor-side visibility for the live-quiz pool.

Two questions this answers, because nothing else in the backend answers them:

  1. what is actually in the bank, per subject — readable vs needs_review vs other, and which
     chapter labels the pool carries;
  2. WHICH question goes to WHICH student, before any student opens a paper.

(2) matters because the selection is per student: the student paper builder samples with
`seed = f"{testId}:{sid}"`, so two students in one test can get different questions from one pool,
and a mentor reading only the test document cannot see what anyone will get. This router does NOT
re-implement that logic — it imports `_candidates`, `pick_questions` and `public_question` from
`routers/student_tests.py`, the very functions `/api/student-tests/paper` calls (see student_tests.py
:271 `_candidates`, :101 `pick_questions`, :405-408 for the `want` arithmetic that is mirrored here
with the same clamp). If the picker changes, this view changes with it; that is the point.

Read-only: no writes, no status changes, no cache invalidation. The pool summary counts documents, it
does not touch the student-facing gates.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import require_mentor
from db import CONTENT_QUESTIONS, get_db
from routers.student_tests import (
    APPROVED_SET,
    MAX_QUESTIONS,
    _candidates,
    pick_questions,
    public_question,
)

router = APIRouter(prefix="/api/live-quiz-admin", tags=["live-quiz-admin"])

# the pool summary walks a projection rather than an aggregation: the in-memory mock store the
# backend tests run on has no aggregate(), and the bank is a few thousand docs. Keep the cap well
# above the pool size and say so out loud instead of silently under-counting.
SCAN_CAP = 60000
_PROJECTION = {"subject": 1, "status": 1, "chapter": 1, "chapterTitle": 1, "chapterId": 1, "revision": 1, "id": 1}


def _chapter_hits(rows: list, asked: list) -> int:
    """How many of `rows` the paper builder would keep for these chapter names. It mirrors the three
    comparisons at student_tests.py:281-290 on purpose: it only ever feeds a *warning*, never a
    selection, so if that code changes the worst case is a stale warning — the papers themselves come
    from `_candidates` itself."""
    hits = 0
    for q in rows:
        chapter = str(q.get("chapter") or "").strip().lower()
        title = str(q.get("chapterTitle") or "").strip().lower()
        if chapter in asked or title in asked or any(c in chapter for c in asked):
            hits += 1
    return hits


@router.get("/pool")
async def pool_summary(claims: dict = Depends(require_mentor)) -> dict:
    """Per subject: how many questions a test can draw from, how many are still under review, and
    the chapter labels the pool actually carries (which is what decides whether a chapter-filtered
    test narrows anything at all)."""
    db = get_db()
    subjects: dict = {}
    scanned = 0
    async for row in db[CONTENT_QUESTIONS].find({}, _PROJECTION).limit(SCAN_CAP):
        scanned += 1
        subject = str(row.get("subject") or "(no subject)")
        s = subjects.setdefault(subject, {
            "subject": subject, "readable": 0, "needsReview": 0, "other": 0,
            "chapters": {}, "revisions": set(),
        })
        status = str(row.get("status") or "")
        if status in APPROVED_SET:
            s["readable"] += 1
        elif status == "needs_review":
            s["needsReview"] += 1
        else:
            s["other"] += 1
        label = str(row.get("chapter") or row.get("chapterTitle") or "").strip()
        if label:
            ch = s["chapters"].setdefault(label, {"label": label, "readable": 0, "total": 0})
            ch["total"] += 1
            if status in APPROVED_SET:
                ch["readable"] += 1
        if row.get("revision"):
            s["revisions"].add(str(row["revision"]))

    out = []
    for s in subjects.values():
        s["revisions"] = sorted(s["revisions"])
        s["chapters"] = sorted(s["chapters"].values(), key=lambda c: (-c["readable"], c["label"]))
        s["chapterCount"] = len(s["chapters"])
        out.append(s)
    out.sort(key=lambda s: -s["readable"])
    return {
        "subjects": out,
        "total": sum(s["readable"] + s["needsReview"] + s["other"] for s in out),
        "readable": sum(s["readable"] for s in out),
        "needsReview": sum(s["needsReview"] for s in out),
        "scanned": scanned,
        "truncated": scanned >= SCAN_CAP,
        "note": ("readable = status in " + ", ".join(sorted(APPROVED_SET)) +
                 " — the only rows /api/student-tests/paper can select. needsReview rows are invisible to students."),
    }


class PreviewRequest(BaseModel):
    """`testId` + `studentIds` reproduce the real selection seed; `subject`/`chapters`/`count`
    mirror what the test document carries. A real testId may be passed instead of the filters and
    then its stored document is used, so the preview is of the test as students will meet it."""
    testId: str = Field(min_length=1, max_length=200)
    studentIds: List[str] = Field(default_factory=list, max_length=500)
    subject: Optional[str] = None
    chapters: List[str] = Field(default_factory=list, max_length=50)
    count: Optional[int] = Field(default=None, ge=1, le=500)
    useStoredTest: bool = True


@router.post("/preview")
async def preview(body: PreviewRequest, claims: dict = Depends(require_mentor)) -> dict:
    db = get_db()
    test: dict = {}
    source = "request"
    if body.useStoredTest:
        from db import MENTOR_TESTS                      # local import: keeps this importable in unit tests
        stored = await db[MENTOR_TESTS].find_one({"testId": body.testId})
        if stored:
            test = stored
            source = "mentor_tests"
    if body.subject:
        test = {**test, "subject": body.subject}
    if body.chapters:
        test = {**test, "chapters": [str(c) for c in body.chapters]}
    if body.count:
        test = {**test, "question_count": body.count}

    rows = await _candidates(db, test)                    # the real filter, incl. chapter narrowing
    unfiltered = await _candidates(db, {**test, "chapters": []})
    pool_size = len(rows)

    # diagnostics, derived from their own two calls rather than a re-implementation: if asking for
    # chapters leaves the count unchanged while chapters were asked for and the pool is bigger than
    # the request, the narrowing silently fell back to the whole subject (student_tests.py:281-290).
    asked = [str(c).strip().lower() for c in (test.get("chapters") or []) if str(c).strip()]
    hits = _chapter_hits(unfiltered, asked) if asked else None
    silent_fallback = bool(asked) and hits == 0 and pool_size > 0
    warnings = []
    if not rows:
        warnings.append("no question matches this test's subject/status filter — students get 409 'Is test ke liye abhi published questions nahi hain'")
    if silent_fallback:
        warnings.append(f"chapters {asked} matched nothing in the pool, so the paper draws from the whole subject instead (student_tests.py:281-290 falls back when the narrowed set is empty). Map the pool's chapter labels to content_chapters if chapter-wise tests must really be chapter-wise.")
    elif asked and 0 < hits < len(unfiltered):
        warnings.append(f"chapter filter narrowed {len(unfiltered)} rows to {pool_size} ({hits} matched)")

    want = int(test.get("question_count") or 0) or min(10, pool_size)
    want = max(1, min(want, MAX_QUESTIONS, pool_size)) if pool_size else 0

    sids = [str(s).strip().upper() for s in body.studentIds if str(s).strip()] or ["(no student given)"]
    per_student = []
    by_question: dict = {}
    for sid in sids:
        chosen = pick_questions(rows, want, f"{body.testId}:{sid}") if pool_size else []
        questions = [public_question(q, 1.0) for q in chosen]
        per_student.append({"studentId": sid, "count": len(questions), "questions": questions})
        for q in chosen:
            e = by_question.setdefault(str(q.get("id")), {"id": str(q.get("id")), "students": []})
            e["students"].append(sid)
    for e in by_question.values():
        e["studentCount"] = len(e["students"])
        e["pinned"] = e["studentCount"] == len(sids)          # in every paper → effectively fixed

    return {
        "testId": body.testId, "testSource": source,
        "subject": test.get("subject") or "", "chapters": asked,
        "requested": body.count, "perStudentCount": want,
        "pool": {"subjectRows": len(unfiltered), "afterChapterFilter": pool_size},
        "students": len(sids), "distinctQuestions": len(by_question),
        "papers": per_student,
        "byQuestion": sorted(by_question.values(), key=lambda e: (-e["studentCount"], e["id"])),
        "warnings": warnings,
        "note": "selection is per student: seed is f\"{testId}:{studentId}\" (student_tests.py:405). Same test, two students, different papers is normal.",
    }
