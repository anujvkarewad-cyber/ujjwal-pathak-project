"""Production repair: dedupe cloned MCQs and auto-publish an empty bank."""
import asyncio

from db import CONTENT_CHAPTERS, CONTENT_QUESTIONS, get_db
from repair import publish_if_empty, repair_store
from tests.fixtures import seed_full_chapter


def _run(fn):
    return asyncio.run(fn())


def test_repair_removes_cloned_questions_keeping_published(client):
    async def seed():
        await seed_full_chapter(status="needs_review")
        db = get_db()
        original = await db[CONTENT_QUESTIONS].find_one({"id": "adp_q_ch-acc-01_01"})
        clone = dict(original)
        clone.pop("_id", None)
        clone["status"] = "published"
        await db[CONTENT_QUESTIONS].insert_one(clone)
        chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": "ch-acc-01"})
        chapter_clone = dict(chapter)
        chapter_clone.pop("_id", None)
        await db[CONTENT_CHAPTERS].insert_one(chapter_clone)

    _run(seed)
    assert _run(lambda: get_db()[CONTENT_QUESTIONS].count_documents({"id": "adp_q_ch-acc-01_01"})) == 2

    report = _run(repair_store)
    assert report["deletedQuestions"] >= 1
    assert report["deletedChapters"] == 1

    async def check():
        db = get_db()
        copies = []
        async for doc in db[CONTENT_QUESTIONS].find({"id": "adp_q_ch-acc-01_01"}):
            copies.append(doc)
        assert len(copies) == 1
        assert copies[0]["status"] == "published"
        assert await db[CONTENT_CHAPTERS].count_documents({"chapterId": "ch-acc-01"}) == 1

    _run(check)


def test_publish_if_empty_publishes_the_bank(client, monkeypatch):
    from repair import settings
    assert settings.mongo_url.startswith("memory://")
    monkeypatch.setattr(settings, "auto_publish_if_empty", True)  # isolated test branch only
    _run(seed_full_chapter)
    result = _run(publish_if_empty)
    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["published"] == 50

    bank = client.get("/api/content/student/bank.json").json()
    assert bank["count"] == 50

    again = _run(publish_if_empty)
    assert again["skipped"] is True
    assert again["reason"] == "already_published"


def test_publish_if_empty_noop_when_store_empty(client, monkeypatch):
    from repair import settings
    assert settings.mongo_url.startswith("memory://")
    monkeypatch.setattr(settings, "auto_publish_if_empty", True)  # isolated test branch only
    result = _run(publish_if_empty)
    assert result["skipped"] is True
    assert result["reason"] == "no_questions"


def test_restore_does_not_clone_existing_docs(client, tmp_path, monkeypatch):
    from persist import restore_store

    snapshot = tmp_path / "store.json"
    snapshot.write_text(
        '{"content_questions":[{"id":"adp_q_dup_1","revision":1,"status":"needs_review","prompt":"x"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENT_STORE", str(snapshot))
    monkeypatch.setattr("persist.store_path", lambda: snapshot)

    async def already_there():
        db = get_db()
        await db[CONTENT_QUESTIONS].insert_one(
            {"id": "adp_q_dup_1", "revision": 1, "status": "published", "prompt": "live"}
        )
        await restore_store()
        copies = []
        async for doc in db[CONTENT_QUESTIONS].find({"id": "adp_q_dup_1"}):
            copies.append(doc)
        assert len(copies) == 1
        assert copies[0]["status"] == "published"

    _run(already_there)


def test_publication_hold_never_publishes(client, monkeypatch):
    from repair import settings
    assert settings.mongo_url.startswith("memory://")
    monkeypatch.setattr(settings,"auto_publish_if_empty",False)
    _run(seed_full_chapter)
    before=_run(lambda: get_db()[CONTENT_QUESTIONS].count_documents({"status":"published"}))
    assert _run(publish_if_empty)["reason"]=="AUTO_PUBLISH_IF_EMPTY=0"
    assert _run(lambda: get_db()[CONTENT_QUESTIONS].count_documents({"status":"published"}))==before
