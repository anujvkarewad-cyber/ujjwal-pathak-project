"""Functional test for routers/live_quiz_admin.py, run against the repo's OWN in-memory Mongo
(mongomock-motor, selected by MONGO_URL=memory://) and seeded with the actual shipped pool payload
(the first published rows of group-1-content.ndjson, plus real needs_review rows from group 2).

Nothing here mocks the backend's behaviour: the selection assertions call the same
`_candidates` / `pick_questions` / `public_question` that /api/student-tests/paper calls.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "memory://")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import pytest                                                        # noqa: E402

from db import CONTENT_QUESTIONS, get_db, reset_db                   # noqa: E402
from routers import live_quiz_admin as admin                        # noqa: E402
from routers.student_tests import APPROVED_SET, _candidates, pick_questions, public_question  # noqa: E402

POOL_FILES = [
    BACKEND.parent / "pool" / "import" / "group-1-content.ndjson",
    BACKEND.parent / "pool" / "import" / "group-2-content.ndjson",
]
PUBLISHED = 24          # enough for 10-per-student sampling to actually sample
REVIEW = 6
STUDENTS = ["STU01", "STU02", "STU03"]


def _rows() -> list:
    docs, seen = [], set()
    for f in POOL_FILES:
        if not f.exists():
            pytest.skip(f"{f.name} missing — run pool_to_content_questions.py first")
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            want_pub, want_rev = d["status"] in APPROVED_SET, d["status"] == "needs_review"
            if want_pub and len([x for x in docs if x["status"] in APPROVED_SET]) < PUBLISHED and d["id"] not in seen:
                seen.add(d["id"]); docs.append(d)
            elif want_rev and len([x for x in docs if x["status"] == "needs_review"]) < REVIEW and d["id"] not in seen:
                seen.add(d["id"]); docs.append(d)
    return docs


@pytest.fixture()
def seeded():
    async def load():
        await reset_db()
        docs = _rows()
        await get_db()[CONTENT_QUESTIONS].insert_many([dict(d) for d in docs])
        return docs
    return asyncio.run(load())


def run(coro):
    return asyncio.run(coro)


def test_pool_summary_counts_the_real_rows(seeded):
    out = run(admin.pool_summary(claims={}))
    published = sum(1 for d in seeded if d["status"] in APPROVED_SET)
    review = sum(1 for d in seeded if d["status"] == "needs_review")
    assert out["readable"] == published
    assert out["needsReview"] == review
    assert out["total"] == len(seeded)
    assert out["truncated"] is False
    subject = out["subjects"][0]
    assert subject["readable"] > 0 and subject["chapterCount"] >= 1
    assert sum(c["readable"] for c in subject["chapters"]) <= subject["readable"]
    assert subject["revisions"], "the pool revision must survive into the summary for traceability"


def test_preview_matches_the_papers_the_students_would_get(seeded):
    subject = seeded[0]["subject"]
    out = run(admin.preview(admin.PreviewRequest(testId="t-preview", subject=subject, studentIds=STUDENTS), claims={}))
    assert out["perStudentCount"] == min(10, out["pool"]["afterChapterFilter"]) == 10
    rows = run(_candidates(get_db(), {"subject": subject}))
    for entry in out["papers"]:
        want = pick_questions(rows, 10, f"t-preview:{entry['studentId']}")
        assert [q["id"] for q in entry["questions"]] == [str(r["id"]) for r in want]
    # deterministic: the same test + same student must replay identically (student_tests.py:405 seed)
    again = run(admin.preview(admin.PreviewRequest(testId="t-preview", subject=subject, studentIds=STUDENTS), claims={}))
    assert again == out


def test_unreviewed_rows_never_reach_a_paper(seeded):
    review_ids = {d["id"] for d in seeded if d["status"] == "needs_review"}
    assert review_ids, "fixture must include needs_review rows"
    subject = seeded[0]["subject"]
    out = run(admin.preview(admin.PreviewRequest(testId="t-rev", subject=subject, studentIds=STUDENTS), claims={}))
    shown = {q["id"] for entry in out["papers"] for q in entry["questions"]}
    assert shown & review_ids == set()
    assert out["byQuestion"], "the per-question cross-tab is the whole point of the tab"
    total = sum(e["studentCount"] for e in out["byQuestion"])
    assert total == len(STUDENTS) * out["perStudentCount"]


def test_a_chapter_the_pool_does_not_carry_is_warned_about(seeded):
    subject = seeded[0]["subject"]
    out = run(admin.preview(admin.PreviewRequest(
        testId="t-chap", subject=subject, studentIds=["STU01"], chapters=["Chapter 5 — Nothing Here"]), claims={}))
    assert any("matched nothing" in w for w in out["warnings"]), out["warnings"]
    assert out["pool"]["subjectRows"] == out["pool"]["afterChapterFilter"]  # silent fallback, exactly as the app behaves
    assert out["perStudentCount"] == 10                                          # still a full paper, not an error


def test_a_real_chapter_actually_narrows(seeded):
    subject = seeded[0]["subject"]
    label = seeded[0]["chapterTitle"]
    rows = run(_candidates(get_db(), {"subject": subject, "chapters": [label]}))
    all_rows = run(_candidates(get_db(), {"subject": subject}))
    assert 0 < len(rows) <= len(all_rows)
    out = run(admin.preview(admin.PreviewRequest(
        testId="t-narrow", subject=subject, studentIds=["STU01"], chapters=[label], count=3), claims={}))
    assert not any("matched nothing" in w for w in out["warnings"])
    assert out["perStudentCount"] == min(3, len(rows))
    for e in out["papers"]:
        for q in e["questions"]:
            pub = public_question(next(r for r in all_rows if str(r["id"]) == q["id"]), 1.0)
            assert q["prompt"] == pub["prompt"] and q["options"] == pub["options"]


def test_count_is_clamped_and_an_empty_subject_is_reported(seeded):
    subject = seeded[0]["subject"]
    big = run(admin.preview(admin.PreviewRequest(testId="t-big", subject=subject, studentIds=["STU01"], count=500), claims={}))
    pool = big["pool"]["afterChapterFilter"]
    assert big["perStudentCount"] == min(500, admin.MAX_QUESTIONS, pool) == pool <= admin.MAX_QUESTIONS
    assert big["papers"][0]["count"] == pool
    empty = run(admin.preview(admin.PreviewRequest(testId="t-none", subject="No Such Subject", studentIds=["STU01"]), claims={}))
    assert empty["pool"]["afterChapterFilter"] == 0 and empty["perStudentCount"] == 0
    assert any("409" in w for w in empty["warnings"])
