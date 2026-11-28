"""Tests for surgical removal of the Nov-2026 Live Quiz / MCQ-book pool."""
import asyncio

import pytest

import db as db_module
from db import CONTENT_QUESTIONS, MIGRATIONS, get_db
from pool_purge import MARKER_KEY, purge_live_quiz_pool


def _run(coro):
    return asyncio.run(coro)


async def _seed_mixed_bank():
    db = get_db()
    # Legitimate existing questions (generated + demo) — must NEVER be touched.
    await db[CONTENT_QUESTIONS].insert_many(
        [
            {
                "id": "adp_q_001",
                "chapterId": "acc-ch01",
                "subject": "Advanced Accounting",
                "group": "Group I",
                "questionType": "direct",
                "status": "published",
                "prompt": "Original generated MCQ",
                "options": [
                    {"id": "A", "text": "Opt A"},
                    {"id": "B", "text": "Opt B"},
                    {"id": "C", "text": "Opt C"},
                    {"id": "D", "text": "Opt D"},
                ],
                "correctOptionId": "B",
                "revision": 1,
                "validation": {"errors": [], "warnings": [], "validatedBy": "content-pipeline"},
            },
            {
                "id": "ch-acc-01-q-001",
                "chapterId": "ch-acc-01",
                "subject": "Accounting",
                "group": "Group I",
                "questionType": "direct",
                "status": "needs_review",
                "prompt": "Demo review queue MCQ",
                "options": [
                    {"id": "A", "text": "1"},
                    {"id": "B", "text": "2"},
                ],
                "correctOptionId": "A",
                "revision": 1,
            },
        ]
    )

    # Nov-2026 Live Quiz / MCQ-book pool questions — MUST be removed.
    await db[CONTENT_QUESTIONS].insert_many(
        [
            {
                "id": "g1-advanced-accou-case-1-1",
                "chapterId": "case-1",
                "subject": "Advanced Accounting",
                "group": "Group 1",
                "questionType": "mcq",
                "status": "published",
                "prompt": "Pool G1 question",
                "options": [
                    {"id": "A", "text": "A"},
                    {"id": "B", "text": "B", "isCorrect": True},
                ],
                "correctOptionId": "B",
                "revision": "mcq-book-g1-518607be",
                "importSource": {
                    "file": "group-1-questions.ndjson",
                    "tool": "pool_to_content_questions.py",
                },
                "validation": {"errors": [], "warnings": [], "validatedBy": "pool-import"},
            },
            {
                "id": "g2-audit-mtp-1-2",
                "chapterId": "mtp-1",
                "subject": "Audit & Assurance",
                "group": "Group 2",
                "questionType": "mcq",
                "status": "needs_review",
                "prompt": "Pool G2 question",
                "options": [
                    {"id": "A", "text": "A", "isCorrect": True},
                    {"id": "B", "text": "B"},
                ],
                "correctOptionId": "A",
                "revision": "mcq-book-g2-438e1fe9",
                "importSource": {
                    "file": "group-2-questions.ndjson",
                    "tool": "pool-import",
                },
                "validation": {"errors": [], "warnings": [], "validatedBy": "pool-import"},
            },
        ]
    )

    # Orphan standalone pool collections in primary DB and sibling `ump` DB.
    await db["mcq_questions"].insert_one({"id": "mcq-1", "group": 1})
    await db["mcq_cases"].insert_one({"caseId": "case-1"})
    await db["mcq_meta"].insert_one({"group": 1, "questions": 1281})

    ump_db = db_module._client["ump"]
    await ump_db["questions"].insert_many(
        [
            {"id": "g1-q1", "revision": "mcq-book-g1-518607be", "poolFingerprint": "abc"},
            {"id": "g2-q1", "revision": "mcq-book-g2-438e1fe9", "poolFingerprint": "def"},
        ]
    )


@pytest.fixture
def mixed_bank():
    _run(_seed_mixed_bank())


def test_dry_run_reports_counts_without_deleting(mixed_bank):
    out = _run(purge_live_quiz_pool(dry_run=True))
    assert out["ok"] is True
    assert out["dryRun"] is True
    assert out["wouldDeleteContentQuestions"] == 2
    assert out["wouldDeleteOrphanDocs"] == 5

    db = get_db()
    assert _run(db[CONTENT_QUESTIONS].count_documents({})) == 4
    assert _run(db_module._client["ump"]["questions"].count_documents({})) == 2


def test_purge_deletes_only_pool_and_preserves_original_bank(mixed_bank):
    out = _run(purge_live_quiz_pool(dry_run=False))
    assert out["ok"] is True
    assert out["applied"] is True
    assert out["deletedContentQuestions"] == 2
    assert out["orphanDeletedTotal"] == 5
    assert out["remainingQuestions"] == 2
    assert out["remainingPublished"] == 1

    db = get_db()
    remaining_ids = sorted(_run(db[CONTENT_QUESTIONS].distinct("id")))
    assert remaining_ids == ["adp_q_001", "ch-acc-01-q-001"]
    assert _run(db["mcq_questions"].count_documents({})) == 0
    assert _run(db_module._client["ump"]["questions"].count_documents({})) == 0
    assert _run(db[MIGRATIONS].find_one({"key": MARKER_KEY})) is not None


def test_purge_is_idempotent_until_forced(mixed_bank):
    first = _run(purge_live_quiz_pool(dry_run=False))
    assert first["applied"] is True

    second = _run(purge_live_quiz_pool(dry_run=False))
    assert second["applied"] is False
    assert second["skipped"] is True
    assert second["reason"] == "already_applied"

    forced = _run(purge_live_quiz_pool(dry_run=False, force=True))
    assert forced["applied"] is True
    assert forced["deletedContentQuestions"] == 0


def test_student_bank_drops_pool_questions_immediately(client, mixed_bank):
    before = client.get("/api/content/student/bank.json").json()
    before_ids = {q["id"] for q in before.get("questions", [])}
    assert "adp_q_001" in before_ids
    assert "g1-advanced-accou-case-1-1" in before_ids

    _run(purge_live_quiz_pool(dry_run=False))

    after = client.get("/api/content/student/bank.json").json()
    after_ids = {q["id"] for q in after.get("questions", [])}
    assert after_ids == {"adp_q_001"}


def test_live_quiz_admin_routes_are_removed(client, mentor_headers):
    spec_paths = client.get("/openapi.json").json().get("paths", {})
    assert "/api/live-quiz-admin/pool" not in spec_paths
    assert "/api/live-quiz-admin/preview" not in spec_paths

    res = client.get("/api/live-quiz-admin/pool", headers=mentor_headers)
    assert res.status_code == 404
    assert res.json().get("code") == "API_ROUTE_NOT_FOUND"

    # Unregistered POST routes hit the GET-only SPA fallback and answer 405/404.
    res_preview = client.post(
        "/api/live-quiz-admin/preview",
        headers=mentor_headers,
        json={"testId": "t1", "subject": "Law", "questionCount": 5},
    )
    assert res_preview.status_code in (404, 405)


def test_admin_purge_endpoint_guards_and_executes(client, mentor_headers, mixed_bank):
    unauth = client.post("/api/admin/purge-live-quiz-pool", json={"dryRun": True})
    assert unauth.status_code in (401, 403)

    dry = client.post(
        "/api/admin/purge-live-quiz-pool",
        headers=mentor_headers,
        json={"dryRun": True},
    )
    assert dry.status_code == 200
    assert dry.json()["wouldDeleteContentQuestions"] == 2

    refused = client.post(
        "/api/admin/purge-live-quiz-pool",
        headers=mentor_headers,
        json={"dryRun": False},
    )
    assert refused.status_code == 200
    assert refused.json()["ok"] is False
    assert refused.json()["reason"] == "confirmation_required"

    confirmed = client.post(
        "/api/admin/purge-live-quiz-pool",
        headers=mentor_headers,
        json={"dryRun": False, "confirm": "DELETE"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["ok"] is True
    assert body["deletedContentQuestions"] == 2
    assert body["remainingQuestions"] == 2
