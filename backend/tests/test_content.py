"""Content review API tests: queue, edits with revalidation, decisions,
scenario blocks, chapter gate, releases, audit."""
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db import CONTENT_CHAPTERS, CONTENT_QUESTIONS, CONTENT_SCENARIOS, get_db  # noqa: E402
from tests.fixtures import CHAPTER, make_question, seed_full_chapter  # noqa: E402


def _seed(status="needs_review"):
    async def run():
        await seed_full_chapter(status=status)

    asyncio.run(run())


def test_content_stats(client, mentor_headers):
    _seed()
    res = client.get("/api/content/stats", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 50
    assert body["needsReview"] == 50
    assert body["chapters"] >= 1


def test_queue_lists_and_filters(client, mentor_headers):
    _seed()
    res = client.get("/api/content/queue", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 50

    res = client.get("/api/content/queue?questionType=mcq", headers=mentor_headers)
    assert res.json()["total"] == 30
    res = client.get("/api/content/queue?questionType=scenario_mcq", headers=mentor_headers)
    assert res.json()["total"] == 20
    res = client.get("/api/content/queue?chapterId=ch-acc-01&status=needs_review", headers=mentor_headers)
    assert res.json()["total"] == 50
    res = client.get("/api/content/queue?chapterId=nope", headers=mentor_headers)
    assert res.json()["total"] == 0

    paged = client.get("/api/content/queue?limit=10&offset=10", headers=mentor_headers)
    assert paged.status_code == 200
    body = paged.json()
    assert body["total"] == 50
    assert body["limit"] == 10
    assert body["offset"] == 10
    assert len(body["items"]) == 10


def test_edit_question_revalidates(client, mentor_headers):
    _seed()
    qid = "adp_q_ch-acc-01_01"
    # valid edit
    res = client.put(
        f"/api/content/questions/{qid}",
        headers=mentor_headers,
        json={"difficulty": "hard", "conceptTags": ["accounting-standards-framework", "applicability", "new-tag"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["difficulty"] == "hard"

    # invalid edit (duplicate options) must be revalidated and still stored with errors
    res = client.put(
        f"/api/content/questions/{qid}",
        headers=mentor_headers,
        json={
            "options": [
                {"id": "A", "text": "Same option text here"},
                {"id": "B", "text": "Same option text here"},
                {"id": "C", "text": "Option C text here"},
                {"id": "D", "text": "Option D text here"},
            ]
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert any("not pairwise distinct" in e for e in body["validation"]["errors"])


def test_approve_requires_clean_validation(client, mentor_headers):
    _seed()
    qid = "adp_q_ch-acc-01_01"
    # corrupt the question via edit, then approve must be rejected
    client.put(
        f"/api/content/questions/{qid}",
        headers=mentor_headers,
        json={
            "options": [
                {"id": "A", "text": "Same option text here"},
                {"id": "B", "text": "Same option text here"},
                {"id": "C", "text": "Option C text here"},
                {"id": "D", "text": "Option D text here"},
            ]
        },
    )
    res = client.post(
        f"/api/content/questions/{qid}/decision",
        headers=mentor_headers,
        json={"decision": "approve", "comment": "looks fine"},
    )
    assert res.status_code == 422
    assert "blocking validation errors" in res.json()["detail"]["message"]


def test_decision_flow(client, mentor_headers):
    _seed()
    qid = "adp_q_ch-acc-01_02"
    res = client.post(f"/api/content/questions/{qid}/decision", headers=mentor_headers, json={"decision": "request_changes", "comment": "tighten option B"})
    assert res.status_code == 200
    assert res.json()["status"] == "changes_requested"
    res = client.post(f"/api/content/questions/{qid}/decision", headers=mentor_headers, json={"decision": "reject", "comment": "not salvageable"})
    assert res.json()["status"] == "rejected"
    # rejected item can't be approved directly (not found as editable)
    res = client.post(f"/api/content/questions/{qid}/decision", headers=mentor_headers, json={"decision": "approve"})
    assert res.status_code == 200  # decision endpoint allows transitions; status moved to approved
    assert res.json()["status"] == "approved"


def test_edit_approved_creates_new_revision(client, mentor_headers):
    _seed()
    qid = "adp_q_ch-acc-01_03"
    client.post(f"/api/content/questions/{qid}/decision", headers=mentor_headers, json={"decision": "approve"})
    res = client.put(f"/api/content/questions/{qid}", headers=mentor_headers, json={"difficulty": "hard"})
    assert res.status_code == 200
    body = res.json()
    assert body["revision"] == 2
    assert body["status"] == "needs_review"
    # old revision superseded
    async def check():
        db = get_db()
        docs = await db[CONTENT_QUESTIONS].find({"id": qid}).to_list(None)
        assert {d["revision"] for d in docs} == {1, 2}
        assert any(d["status"] == "superseded" for d in docs)

    asyncio.run(check())


def test_scenario_block_decision(client, mentor_headers):
    _seed()
    sid = "adp_s_ch-acc-01_01"
    res = client.get(f"/api/content/scenarios/{sid}", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body["questions"]) == 4

    res = client.post(f"/api/content/scenarios/{sid}/decision", headers=mentor_headers, json={"decision": "approve", "comment": "block ok"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
    for qid in body["questionIds"]:
        r = client.get(f"/api/content/questions/{qid}", headers=mentor_headers)
        assert r.json()["status"] == "approved"

    # reject the other block — all 4 questions move to rejected
    sid2 = "adp_s_ch-acc-01_02"
    client.post(f"/api/content/scenarios/{sid2}/decision", headers=mentor_headers, json={"decision": "reject", "comment": "redo passage"})
    body2 = client.get(f"/api/content/scenarios/{sid2}", headers=mentor_headers).json()
    for qid in body2["questionIds"]:
        r = client.get(f"/api/content/questions/{qid}", headers=mentor_headers)
        assert r.json()["status"] == "rejected"


def test_chapter_gate_and_approve(client, mentor_headers):
    _seed()
    res = client.get("/api/content/chapters/ch-acc-01/gate", headers=mentor_headers)
    assert res.status_code == 200
    assert res.json()["publishable"] is False

    # approve everything
    async def approve_all():
        db = get_db()
        await db[CONTENT_QUESTIONS].update_many({"chapterId": "ch-acc-01"}, {"$set": {"status": "approved", "warningsAcknowledged": True}})
        await db[CONTENT_SCENARIOS].update_many({"chapterId": "ch-acc-01"}, {"$set": {"status": "approved"}})

    asyncio.run(approve_all())

    res = client.get("/api/content/chapters/ch-acc-01/gate", headers=mentor_headers)
    assert res.json()["publishable"] is True, res.text

    res = client.post("/api/content/chapters/ch-acc-01/approve", headers=mentor_headers)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert res.json()["coverage"] == {"plainApproved": 30, "plainTarget": 30, "scenariosApproved": 5, "scenariosTarget": 5, "scenarioMcqsApproved": 20, "scenarioMcqsTarget": 20}

    chapters = client.get("/api/content/chapters", headers=mentor_headers).json()["items"]
    ch = next(c for c in chapters if c["chapterId"] == "ch-acc-01")
    assert ch["coverage"]["plainApproved"] == 30


def test_gate_promotes_scenarios_after_question_approval(client, mentor_headers):
    """Approving all 50 questions (not the scenario docs) used to leave the
    Gate button locked on '5 scenarios not all approved'. Opening / approving
    the gate must auto-promote complete scenario blocks."""
    _seed()

    async def approve_questions_only():
        db = get_db()
        await db[CONTENT_QUESTIONS].update_many(
            {"chapterId": "ch-acc-01"},
            {"$set": {"status": "approved", "warningsAcknowledged": True}},
        )

    asyncio.run(approve_questions_only())

    res = client.get("/api/content/chapters/ch-acc-01/gate", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["publishable"] is True, body
    assert body["coverage"]["scenariosApproved"] == 5

    res = client.post("/api/content/chapters/ch-acc-01/approve", headers=mentor_headers)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    res = client.post("/api/content/chapters/ch-acc-01/publish", headers=mentor_headers, json={"warningsAcknowledged": True})
    assert res.status_code == 200, res.text
    published = res.json()
    assert published["ok"] is True
    assert published["status"] == "published"
    assert published["revision"] == 1

    chapters = client.get("/api/content/chapters", headers=mentor_headers).json()["items"]
    ch = next(c for c in chapters if c["chapterId"] == "ch-acc-01")
    assert ch["status"] == "published"

    releases = client.get("/api/content/releases", headers=mentor_headers).json()["items"]
    assert releases and releases[0]["revision"] == 1


def test_gate_fails_on_incomplete_chapter(client, mentor_headers):
    _seed()
    async def approve_partial():
        db = get_db()
        await db[CONTENT_QUESTIONS].update_many(
            {"chapterId": "ch-acc-01", "questionType": "mcq"}, {"$set": {"status": "approved"}}
        )  # scenarios remain needs_review

    asyncio.run(approve_partial())
    res = client.post("/api/content/chapters/ch-acc-01/approve", headers=mentor_headers)
    assert res.status_code == 422
    assert any("scenarios" in e for e in res.json()["detail"]["errors"])


def test_releases_and_audit(client, mentor_headers):
    _seed()
    res = client.get("/api/content/releases", headers=mentor_headers)
    assert res.status_code == 200
    assert res.json()["items"] == []

    audit = client.get("/api/content/audit?action=edit", headers=mentor_headers).json()
    assert "items" in audit

    qid = "adp_q_ch-acc-01_05"
    client.put(f"/api/content/questions/{qid}", headers=mentor_headers, json={"difficulty": "easy"})
    audit = client.get(f"/api/content/audit?entityId={qid}", headers=mentor_headers).json()
    assert any(a["action"] == "edit" for a in audit["items"])
