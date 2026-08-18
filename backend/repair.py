"""One-shot production repair: remove cloned MCQs and republish an empty bank."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings
from db import (
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_RELEASES,
    CONTENT_SCENARIOS,
    get_db,
)

logger = logging.getLogger(__name__)

STATUS_RANK = {
    "published": 80,
    "release_candidate": 70,
    "approved": 60,
    "changes_requested": 50,
    "needs_review": 40,
    "auto_validated": 30,
    "generated": 20,
    "rejected": 10,
    "superseded": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rank(doc: dict) -> tuple:
    status = doc.get("status") or ""
    revision = int(doc.get("revision") or 0)
    return (STATUS_RANK.get(status, -1), revision)


async def _dedupe(collection: str, key_field: str) -> int:
    db = get_db()
    winners: dict = {}
    losers: list = []
    async for doc in db[collection].find({}):
        key = doc.get(key_field)
        if not key:
            continue
        oid = doc.get("_id")
        current = winners.get(key)
        if current is None:
            winners[key] = doc
            continue
        if _rank(doc) > _rank(current):
            losers.append(current.get("_id"))
            winners[key] = doc
        else:
            losers.append(oid)
    losers = [oid for oid in losers if oid is not None]
    if not losers:
        return 0
    result = await db[collection].delete_many({"_id": {"$in": losers}})
    deleted = int(getattr(result, "deleted_count", 0) or 0)
    logger.info("[repair] %s: removed %s duplicate(s)", collection, deleted)
    return deleted


async def repair_store() -> dict:
    deleted_questions = await _dedupe(CONTENT_QUESTIONS, "id")
    deleted_scenarios = await _dedupe(CONTENT_SCENARIOS, "scenarioId")
    deleted_chapters = await _dedupe(CONTENT_CHAPTERS, "chapterId")
    report = {
        "deletedQuestions": deleted_questions,
        "deletedScenarios": deleted_scenarios,
        "deletedChapters": deleted_chapters,
    }
    if any(report.values()):
        logger.warning("[repair] deduped store: %s", report)
    else:
        logger.info("[repair] store already unique")
    return report


async def publish_if_empty() -> dict:
    if not settings.auto_publish_if_empty:
        return {"ok": True, "skipped": True, "reason": "AUTO_PUBLISH_IF_EMPTY=0"}

    db = get_db()
    total = await db[CONTENT_QUESTIONS].count_documents({})
    published = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})
    if total == 0:
        return {"ok": True, "skipped": True, "reason": "no_questions"}
    if published > 0:
        return {"ok": True, "skipped": True, "reason": "already_published", "published": published}

    now = _now()
    latest = None
    async for row in db[CONTENT_RELEASES].find({}).sort("revision", -1).limit(1):
        latest = row
    revision = int((latest or {}).get("revision") or 0) + 1

    q_res = await db[CONTENT_QUESTIONS].update_many(
        {"status": {"$ne": "superseded"}},
        {
            "$set": {
                "status": "published",
                "publishedAt": now,
                "publishedInRevision": revision,
                "warningsAcknowledged": True,
                "attemptSpecificRiskConfirmed": True,
            }
        },
    )
    await db[CONTENT_SCENARIOS].update_many(
        {"status": {"$ne": "superseded"}},
        {"$set": {"status": "published", "publishedAt": now, "publishedInRevision": revision}},
    )
    await db[CONTENT_CHAPTERS].update_many(
        {},
        {"$set": {"status": "published", "releaseCandidate": {"revision": revision, "at": now, "by": "auto-publish"}}},
    )
    chapter_ids: list[str] = []
    async for ch in db[CONTENT_CHAPTERS].find({}, {"chapterId": 1}):
        if ch.get("chapterId"):
            chapter_ids.append(ch["chapterId"])

    await db[CONTENT_RELEASES].insert_one(
        {
            "revision": revision,
            "manifest": {
                "schemaVersion": 1,
                "revision": revision,
                "publishedAt": now,
                "publishedBy": "auto-publish",
                "catalogRevision": "may-2026",
                "scope": "auto-publish-if-empty",
            },
            "publishedAt": now,
            "publishedBy": "auto-publish",
            "chapters": chapter_ids,
            "gates": [],
            "bulk": True,
        }
    )

    live = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})
    try:
        from routers.student_content import invalidate_student_bank
        invalidate_student_bank()
    except Exception:
        pass

    logger.warning(
        "[repair] auto-published %s questions (was 0 published, %s in store, revision %s)",
        live,
        total,
        revision,
    )
    return {
        "ok": True,
        "skipped": False,
        "published": live,
        "modified": int(getattr(q_res, "modified_count", 0) or 0),
        "revision": revision,
        "chapters": len(chapter_ids),
    }
