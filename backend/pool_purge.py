"""One-shot idempotent removal of the Nov-2026 Live Quiz / MCQ-book pool.

Why
---
On 27 Nov 2026, 2,933 MCQ-book questions (Group 1 = 1,281, Group 2 = 1,652)
were imported into ``content_questions`` via ``pool_to_content_questions.py``
alongside standalone ``questions`` / ``mcq_*`` pool collections. That pushed
the live bank from the approved 4,800 questions (4,700 generated + 100 demo)
to 7,733.

This module surgically removes ONLY the Live Quiz / MCQ-book pool documents
while keeping all 4,800 existing questions, chapters, scenarios, releases,
student accounts, and student attempt history completely untouched:

1. ``content_questions`` in the primary database (``ujjwal_pathak``): deletes
   documents matching ``LIVE_QUIZ_POOL_FILTER`` (``importSource.tool`` in
   ``{"pool_to_content_questions.py", "pool-import"}``, ``revision`` in
   ``{"mcq-book-g1-518607be", "mcq-book-g2-438e1fe9", "icai-may-2026-v1"}``,
   or ``validation.validatedBy == "pool-import"``), repairs any accidental
   unique ``id_1`` index created by ``pool_to_content_questions.py``, and
   invalidates the cached ``/api/content/student/bank.json`` payload.
2. Orphan pool collections (``questions``, ``mcq_questions``, ``mcq_cases``,
   ``mcq_meta``) in both the primary database and sibling ``ump`` database (if
   accessible on the same Mongo client): removes pool rows and drops empty
   orphan collections.

Idempotency
-----------
Writes ``key = "live_quiz_pool_purge_2026_11_v1"`` to ``migrations`` after a
real run so every subsequent boot is a single indexed lookup. Pass
``force=True`` (or set ``POOL_PURGE_FORCE=1``) to re-run deliberately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import db as db_module
from config import settings
from db import CONTENT_AUDIT, CONTENT_QUESTIONS, MIGRATIONS, get_db

logger = logging.getLogger(__name__)

MARKER_KEY = "live_quiz_pool_purge_2026_11_v1"
_FORCE_ENV = "POOL_PURGE_FORCE"

LIVE_QUIZ_POOL_REVISIONS: tuple[str, ...] = (
    "mcq-book-g1-518607be",
    "mcq-book-g2-438e1fe9",
    "icai-may-2026-v1",
)

LIVE_QUIZ_POOL_TOOLS: tuple[str, ...] = (
    "pool_to_content_questions.py",
    "pool-import",
)

LIVE_QUIZ_POOL_FILTER: dict = {
    "$or": [
        {"importSource.tool": {"$in": list(LIVE_QUIZ_POOL_TOOLS)}},
        {"revision": {"$in": list(LIVE_QUIZ_POOL_REVISIONS)}},
        {"validation.validatedBy": "pool-import"},
    ]
}

ORPHAN_QUESTIONS_FILTER: dict = {
    "$or": [
        {"revision": {"$in": list(LIVE_QUIZ_POOL_REVISIONS)}},
        {"poolFingerprint": {"$exists": True}},
        {"importSource.tool": {"$in": list(LIVE_QUIZ_POOL_TOOLS)}},
    ]
}

ORPHAN_MCQ_COLLECTIONS: tuple[str, ...] = (
    "mcq_questions",
    "mcq_cases",
    "mcq_meta",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


async def marker_doc() -> Optional[dict]:
    db = get_db()
    return await db[MIGRATIONS].find_one({"key": MARKER_KEY})


async def _repair_unique_id_index(db) -> bool:
    """Drop an accidental unique single-field `id` index on content_questions.

    `pool_to_content_questions.py --ensure-index` created `id` as unique,
    whereas `db.ensure_unique_indexes()` enforces uniqueness on `(id, revision)`
    so mentor edits can insert a new revision for an existing question id.
    """
    try:
        indexes = await db[CONTENT_QUESTIONS].index_information()
        repaired = False
        for idx_name, info in (indexes or {}).items():
            key_spec = info.get("key") or []
            if list(key_spec) == [("id", 1)] and info.get("unique"):
                await db[CONTENT_QUESTIONS].drop_index(idx_name)
                await db[CONTENT_QUESTIONS].create_index("id")
                logger.info(
                    "[pool-purge] replaced unique %s index on %s with non-unique index",
                    idx_name,
                    CONTENT_QUESTIONS,
                )
                repaired = True
        return repaired
    except Exception as exc:
        logger.debug("[pool-purge] index inspection skipped: %s", exc)
        return False


async def _purge_orphan_collections(target_db, label: str, dry_run: bool) -> dict:
    """Clean standalone `questions` and `mcq_*` pool collections on `target_db`."""
    out: dict = {"collections": {}, "dropped": []}
    try:
        existing_names = set(await target_db.list_collection_names())
    except Exception as exc:
        logger.info("[pool-purge] skipping orphan check on %s: %s", label, exc)
        out["skippedReason"] = str(exc)[:200]
        return out

    if "questions" in existing_names:
        try:
            q_coll = target_db["questions"]
            matched = await q_coll.count_documents(ORPHAN_QUESTIONS_FILTER)
            if not dry_run and matched:
                res = await q_coll.delete_many(ORPHAN_QUESTIONS_FILTER)
                matched = int(getattr(res, "deleted_count", matched) or 0)
            out["collections"]["questions"] = matched
            if not dry_run:
                leftover = await q_coll.count_documents({})
                if leftover == 0:
                    await q_coll.drop()
                    out["dropped"].append("questions")
        except Exception as exc:
            logger.warning("[pool-purge] failed cleaning %s.questions: %s", label, exc)

    for coll_name in ORPHAN_MCQ_COLLECTIONS:
        if coll_name not in existing_names:
            continue
        try:
            coll = target_db[coll_name]
            count = await coll.count_documents({})
            if not dry_run:
                if count:
                    res = await coll.delete_many({})
                    count = int(getattr(res, "deleted_count", count) or 0)
                await coll.drop()
                out["dropped"].append(coll_name)
            out["collections"][coll_name] = count
        except Exception as exc:
            logger.warning("[pool-purge] failed cleaning %s.%s: %s", label, coll_name, exc)

    return out


async def purge_live_quiz_pool(
    *,
    dry_run: bool = False,
    force: bool = False,
    include_sibling_ump: bool = True,
) -> dict:
    """Remove the Live Quiz MCQ-book pool from MongoDB (safe & idempotent)."""
    db = get_db()

    if not dry_run and not force:
        existing_marker = await marker_doc()
        if existing_marker is not None:
            logger.info("[pool-purge] marker %s present — nothing to do", MARKER_KEY)
            return {
                "ok": True,
                "applied": False,
                "skipped": True,
                "dryRun": False,
                "reason": "already_applied",
                "key": MARKER_KEY,
                "appliedAt": existing_marker.get("appliedAt"),
                "deletedContentQuestions": existing_marker.get("deletedContentQuestions", 0),
                "orphanCleanup": existing_marker.get("orphanCleanup", {}),
            }

    matched_cq = await db[CONTENT_QUESTIONS].count_documents(LIVE_QUIZ_POOL_FILTER)
    deleted_cq = matched_cq
    if not dry_run and matched_cq:
        res = await db[CONTENT_QUESTIONS].delete_many(LIVE_QUIZ_POOL_FILTER)
        deleted_cq = int(getattr(res, "deleted_count", matched_cq) or 0)

    index_repaired = False
    if not dry_run:
        index_repaired = await _repair_unique_id_index(db)

    orphan_cleanup: dict[str, dict] = {
        settings.db_name: await _purge_orphan_collections(db, settings.db_name, dry_run=dry_run)
    }

    client = getattr(db_module, "_client", None)
    if include_sibling_ump and client is not None and settings.db_name != "ump":
        orphan_cleanup["ump"] = await _purge_orphan_collections(
            client["ump"], "ump", dry_run=dry_run
        )

    remaining_total = await db[CONTENT_QUESTIONS].count_documents({})
    remaining_published = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})

    orphan_deleted_total = sum(
        sum((info.get("collections") or {}).values())
        for info in orphan_cleanup.values()
        if isinstance(info, dict)
    )

    if dry_run:
        return {
            "ok": True,
            "applied": False,
            "skipped": False,
            "dryRun": True,
            "key": MARKER_KEY,
            "wouldDeleteContentQuestions": deleted_cq,
            "wouldDeleteOrphanDocs": orphan_deleted_total,
            "orphanCleanup": orphan_cleanup,
            "currentQuestions": remaining_total,
            "currentPublished": remaining_published,
        }

    if deleted_cq or force:
        try:
            from routers.student_content import invalidate_student_bank

            invalidate_student_bank()
        except Exception as exc:
            logger.warning("[pool-purge] bank cache invalidation skipped: %s", exc)
        try:
            from persist import dump_store

            await dump_store()
        except Exception as exc:
            logger.warning("[pool-purge] persist dump skipped: %s", exc)

    applied_at = _now()
    if deleted_cq or orphan_deleted_total:
        logger.warning(
            "[pool-purge] deleted %s pool rows from %s (remaining=%s, published=%s) and %s orphan rows",
            deleted_cq,
            CONTENT_QUESTIONS,
            remaining_total,
            remaining_published,
            orphan_deleted_total,
        )
        await db[CONTENT_AUDIT].insert_one(
            {
                "at": applied_at,
                "by": "system:pool_purge",
                "action": "live_quiz_pool_purge",
                "entityType": "pool",
                "entityId": MARKER_KEY,
                "detail": {
                    "deletedContentQuestions": deleted_cq,
                    "orphanDeletedTotal": orphan_deleted_total,
                    "orphanCleanup": orphan_cleanup,
                    "indexRepaired": index_repaired,
                    "remainingQuestions": remaining_total,
                    "remainingPublished": remaining_published,
                },
            }
        )

    marker = {
        "key": MARKER_KEY,
        "appliedAt": applied_at,
        "forced": bool(force),
        "deletedContentQuestions": deleted_cq,
        "orphanDeletedTotal": orphan_deleted_total,
        "orphanCleanup": orphan_cleanup,
        "indexRepaired": index_repaired,
        "remainingQuestions": remaining_total,
        "remainingPublished": remaining_published,
    }
    await db[MIGRATIONS].update_one({"key": MARKER_KEY}, {"$set": marker}, upsert=True)

    return {
        "ok": True,
        "applied": True,
        "skipped": False,
        "dryRun": False,
        "key": MARKER_KEY,
        "appliedAt": applied_at,
        "deletedContentQuestions": deleted_cq,
        "orphanDeletedTotal": orphan_deleted_total,
        "orphanCleanup": orphan_cleanup,
        "indexRepaired": index_repaired,
        "remainingQuestions": remaining_total,
        "remainingPublished": remaining_published,
    }


async def run_pool_purge_on_boot() -> Optional[dict]:
    """Startup hook. Never raises — a failed cleanup must not block boot."""
    try:
        return await purge_live_quiz_pool(
            dry_run=False,
            force=_truthy(os.environ.get(_FORCE_ENV, "")),
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("[pool-purge] startup purge failed")
        return None


async def _main() -> None:  # pragma: no cover - manual operator tool
    logging.basicConfig(level=logging.INFO)
    summary = await purge_live_quiz_pool(
        dry_run=False,
        force=_truthy(os.environ.get(_FORCE_ENV, "")),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover - manual operator tool
    asyncio.run(_main())
