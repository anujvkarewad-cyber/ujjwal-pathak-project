"""Bulk approve + publish endpoints: chapter / subject / whole bank.

The per-question flow stays untouched; these tests cover the mentor one-click
bulk path used for large banks (~4,700 MCQs):
- publishes every eligible question + scenario + chapter in scope
- skips (does not publish) questions with blocking validation errors
- creates a single shared release revision
- shows up in the student bank immediately
- requires mentor auth
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db import CONTENT_QUESTIONS, CONTENT_SCENARIOS, get_db  # noqa: E402
from tests.fixtures import seed_full_chapter  # noqa: E402


def _seed(status="needs_review"):
    async def run():
        await seed_full_chapter(status=status)

    asyncio.run(run())


def _count(filter_):
    async def run():
        db = get_db()
        return {
            "questions": await db[CONTENT_QUESTIONS].count_documents(filter_),
            "scenarios": await db[CONTENT_SCENARIOS].count_documents(filter_),
        }

    return asyncio.run(run())


def test_bulk_publish_chapter(client, mentor_headers):
    _seed()
    res = client.post("/api/content/chapters/ch-acc-01/bulk-approve-publish", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["publishedQuestions"] == 50
    assert body["chapters"] == 1
    assert body["skippedWithErrors"] == 0
    assert body["revision"] >= 1

    published = _count({"status": "published"})
    assert published["questions"] == 50
    assert published["scenarios"] == 5

    # Student bank serves everything immediately.
    bank = client.get("/api/content/student/bank.json")
    assert bank.status_code == 200
    assert bank.json()["count"] == 50

    # Dashboard stats reflect the change.
    stats = client.get("/api/content/stats", headers=mentor_headers).json()
    assert stats["needsReview"] == 0
    assert stats["approved"] == 50

    # A release revision record exists.
    releases = client.get("/api/content/releases", headers=mentor_headers).json()["items"]
    assert releases and releases[0]["revision"] == body["revision"]


def test_bulk_publish_chapter_not_found(client, mentor_headers):
    res = client.post("/api/content/chapters/nope/bulk-approve-publish", headers=mentor_headers)
    assert res.status_code == 404


def test_bulk_publish_subject(client, mentor_headers):
    _seed()
    res = client.post("/api/content/subjects/Accounting/bulk-approve-publish", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["publishedQuestions"] == 50
    assert body["scope"] == "subject:Accounting"

    res = client.post("/api/content/subjects/Unknown%20Subject/bulk-approve-publish", headers=mentor_headers)
    assert res.status_code == 404


def test_bulk_publish_all_skips_invalid_questions(client, mentor_headers):
    _seed()

    async def corrupt_one():
        db = get_db()
        await db[CONTENT_QUESTIONS].update_one(
            {"id": "adp_q_ch-acc-01_01"},
            {"$set": {"correctOptionId": "Z", "explanation": "x"}},
        )

    asyncio.run(corrupt_one())

    res = client.post("/api/content/bulk-approve-publish-all", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["publishedQuestions"] == 49
    assert body["skippedWithErrors"] == 1
    assert body["skippedSample"][0]["id"] == "adp_q_ch-acc-01_01"
    assert "errors" in body["skippedSample"][0]

    # The broken question stays in review — never reaches students.
    invalid = asyncio.run(get_db()[CONTENT_QUESTIONS].find_one({"id": "adp_q_ch-acc-01_01"}))
    assert invalid["status"] == "needs_review"
    bank = client.get("/api/content/student/bank.json").json()
    assert bank["count"] == 49
    assert all(q["id"] != "adp_q_ch-acc-01_01" for q in bank["questions"])


def test_bulk_publish_is_idempotent_for_published(client, mentor_headers):
    _seed()
    first = client.post("/api/content/chapters/ch-acc-01/bulk-approve-publish", headers=mentor_headers).json()
    second = client.post("/api/content/chapters/ch-acc-01/bulk-approve-publish", headers=mentor_headers).json()
    assert second["publishedQuestions"] == 0
    assert second["alreadyPublished"] == 50
    assert second["revision"] > first["revision"]
    bank = client.get("/api/content/student/bank.json").json()
    assert bank["count"] == 50


def test_bulk_publish_requires_auth(client):
    _seed()
    res = client.post("/api/content/bulk-approve-publish-all")
    assert res.status_code in (401, 403)
    res = client.post("/api/content/chapters/ch-acc-01/bulk-approve-publish")
    assert res.status_code in (401, 403)
    res = client.post("/api/content/subjects/Accounting/bulk-approve-publish")
    assert res.status_code in (401, 403)
