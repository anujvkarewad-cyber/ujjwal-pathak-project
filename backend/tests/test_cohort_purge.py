"""End-of-attempt cohort purge: keeps Atlas M0 (512 MB) free forever.

Contract:
  * only the selected cohort's activity data is deleted,
  * other cohorts and all content are untouched,
  * accounts survive unless explicitly requested,
  * dry run reports without deleting; a real delete needs confirm="DELETE".
"""
import asyncio

import pytest

from cohort_purge import PROTECTED_COLLECTIONS, purge_cohort, resolve_cohort
from db import (
    ANALYTICS_SUMMARIES,
    CONTENT_QUESTIONS,
    STUDENT_ACCOUNTS,
    STUDENT_MCQ_ATTEMPTS,
    get_db,
)


def _run(coro):
    return asyncio.run(coro)


async def _seed():
    db = get_db()
    cohorts = {
        "UMP0101": "Sept 2026",
        "UMP0102": "Sept 2026",
        "UMP0201": "Jan 2027",
    }
    for sid, attempt in cohorts.items():
        await db[STUDENT_ACCOUNTS].insert_one(
            {"studentId": sid, "studentName": sid, "attempt": attempt, "batch": ""}
        )
        for n in range(3):
            await db[STUDENT_MCQ_ATTEMPTS].insert_one(
                {"studentId": sid, "kind": "daily", "attemptId": f"{sid}-{n}", "answers": {}}
            )
        await db[ANALYTICS_SUMMARIES].insert_one({"studentId": sid, "chapterId": "ch1"})
    # Content must survive any purge.
    await db[CONTENT_QUESTIONS].insert_one({"id": "Q1", "status": "published", "revision": 1})


@pytest.fixture
def seeded():
    _run(_seed())


def test_resolve_cohort_matches_attempt_text(seeded):
    assert _run(resolve_cohort(attempt="Sept 2026")) == ["UMP0101", "UMP0102"]
    assert _run(resolve_cohort(attempt="jan 2027")) == ["UMP0201"]
    assert _run(resolve_cohort(attempt="May 2028")) == []


def test_dry_run_reports_but_deletes_nothing(seeded):
    out = _run(purge_cohort(attempt="Sept 2026", dry_run=True))
    assert out["dryRun"] is True
    assert out["students"] == 2
    assert out["deleted"][STUDENT_MCQ_ATTEMPTS] == 6
    assert out["totalDocuments"] == 8  # 6 attempts + 2 summaries

    db = get_db()
    assert _run(db[STUDENT_MCQ_ATTEMPTS].count_documents({})) == 9


def test_purge_removes_only_that_cohort(seeded):
    out = _run(purge_cohort(attempt="Sept 2026", dry_run=False))
    assert out["dryRun"] is False
    assert out["deleted"][STUDENT_MCQ_ATTEMPTS] == 6

    db = get_db()
    remaining = _run(db[STUDENT_MCQ_ATTEMPTS].distinct("studentId"))
    assert remaining == ["UMP0201"]
    assert _run(db[ANALYTICS_SUMMARIES].count_documents({})) == 1


def test_accounts_and_content_survive_by_default(seeded):
    _run(purge_cohort(attempt="Sept 2026", dry_run=False))
    db = get_db()
    assert _run(db[STUDENT_ACCOUNTS].count_documents({})) == 3
    assert _run(db[CONTENT_QUESTIONS].count_documents({})) == 1
    assert "content_questions" in PROTECTED_COLLECTIONS


def test_accounts_removed_only_when_requested(seeded):
    out = _run(purge_cohort(attempt="Sept 2026", dry_run=False, delete_accounts=True))
    assert out["accountsDeleted"] == 2
    db = get_db()
    assert _run(db[STUDENT_ACCOUNTS].distinct("studentId")) == ["UMP0201"]
    assert _run(db[CONTENT_QUESTIONS].count_documents({})) == 1


def test_explicit_student_ids(seeded):
    out = _run(purge_cohort(student_ids=["UMP0101"], dry_run=False))
    assert out["students"] == 1
    db = get_db()
    assert sorted(_run(db[STUDENT_MCQ_ATTEMPTS].distinct("studentId"))) == ["UMP0102", "UMP0201"]


def test_unknown_cohort_is_a_no_op(seeded):
    out = _run(purge_cohort(attempt="May 2030", dry_run=False))
    assert out["ok"] is False
    assert out["reason"] == "no_students_matched"
    db = get_db()
    assert _run(db[STUDENT_MCQ_ATTEMPTS].count_documents({})) == 9


# ── HTTP endpoint ─────────────────────────────────────────────────────────

def test_endpoint_requires_mentor_auth(client, seeded):
    res = client.post("/api/admin/purge-cohort", json={"attempt": "Sept 2026"})
    assert res.status_code in (401, 403)


def test_endpoint_refuses_real_delete_without_confirmation(client, mentor_headers, seeded):
    res = client.post(
        "/api/admin/purge-cohort",
        json={"attempt": "Sept 2026", "dryRun": False},
        headers=mentor_headers,
    )
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert res.json()["reason"] == "confirmation_required"
    db = get_db()
    assert _run(db[STUDENT_MCQ_ATTEMPTS].count_documents({})) == 9


def test_endpoint_deletes_with_confirmation(client, mentor_headers, seeded):
    res = client.post(
        "/api/admin/purge-cohort",
        json={"attempt": "Sept 2026", "dryRun": False, "confirm": "DELETE"},
        headers=mentor_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["students"] == 2
    db = get_db()
    assert _run(db[STUDENT_MCQ_ATTEMPTS].distinct("studentId")) == ["UMP0201"]
