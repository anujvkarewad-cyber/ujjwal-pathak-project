"""Safe end-of-attempt cleanup: delete one cohort's student data.

Why
---
A new batch starts every 3-4 months. Keeping every past batch's MCQ attempts
fills the MongoDB Atlas M0 free tier (512 MB). Purging a finished cohort after
its CA attempt keeps the database small — and free — forever.

Safety rules (deliberate, not configurable):
  * Only data keyed by `studentId` is removed, and only for students that
    belong to the selected cohort.
  * Content is NEVER touched: questions, scenarios, chapters, releases and the
    knowledge base live in their own collections and are out of scope.
  * Student accounts are kept by default, so logins and the Students sheet keep
    working. Pass `delete_accounts=True` to remove them too.
  * `dry_run=True` is the default everywhere: it reports exactly what WOULD be
    deleted without touching anything.
  * Every real purge writes an audit record.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from db import (
    ANALYTICS_AUDIT_SYNC,
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TEST_HISTORY,
    ANALYTICS_TRENDS,
    STUDENT_ACCOUNTS,
    STUDENT_MCQ_ATTEMPTS,
    STUDENT_MESSAGES,
    get_db,
)

logger = logging.getLogger(__name__)

# Collections keyed by studentId that hold per-cohort activity data.
PURGEABLE_COLLECTIONS: tuple[str, ...] = (
    STUDENT_MCQ_ATTEMPTS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TRENDS,
    ANALYTICS_TEST_HISTORY,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_CONSENTS,
    STUDENT_MESSAGES,
)

# Never deleted by this module, whatever the arguments.
PROTECTED_COLLECTIONS: tuple[str, ...] = (
    "content_questions",
    "content_scenarios",
    "content_chapters",
    "content_releases",
    "knowledge_chunks",
    "migrations",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return re.sub(r"[\s._/-]+", " ", str(text or "").strip().lower())


async def resolve_cohort(
    attempt: str = "",
    student_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """Student IDs for a cohort, matched on the account's attempt/batch text."""
    from routers.student_auth import normalize_student_id

    if student_ids:
        return sorted({normalize_student_id(s) for s in student_ids if str(s).strip()})

    needle = _norm(attempt)
    if not needle:
        return []
    db = get_db()
    matched: set[str] = set()
    async for doc in db[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "attempt": 1, "batch": 1}):
        haystack = f"{_norm(doc.get('attempt'))} {_norm(doc.get('batch'))}"
        if needle and needle in haystack:
            sid = normalize_student_id(doc.get("studentId") or "")
            if sid:
                matched.add(sid)
    return sorted(matched)


async def purge_cohort(
    attempt: str = "",
    student_ids: Optional[Iterable[str]] = None,
    dry_run: bool = True,
    delete_accounts: bool = False,
) -> dict:
    """Count (dry run) or delete one cohort's activity data.

    Returns ``{"ok", "dryRun", "students", "studentIds", "deleted": {...},
    "totalDocuments", "accountsDeleted"}``.
    """
    db = get_db()
    ids = await resolve_cohort(attempt=attempt, student_ids=student_ids)
    if not ids:
        return {
            "ok": False,
            "reason": "no_students_matched",
            "dryRun": dry_run,
            "attempt": attempt,
            "students": 0,
            "studentIds": [],
            "deleted": {},
            "totalDocuments": 0,
            "accountsDeleted": 0,
        }

    query = {"studentId": {"$in": ids}}
    deleted: dict[str, int] = {}
    total = 0
    for collection in PURGEABLE_COLLECTIONS:
        count = await db[collection].count_documents(query)
        if not dry_run and count:
            result = await db[collection].delete_many(query)
            count = int(getattr(result, "deleted_count", count) or 0)
        deleted[collection] = count
        total += count

    accounts = 0
    if delete_accounts:
        accounts = await db[STUDENT_ACCOUNTS].count_documents(query)
        if not dry_run and accounts:
            result = await db[STUDENT_ACCOUNTS].delete_many(query)
            accounts = int(getattr(result, "deleted_count", accounts) or 0)

    summary = {
        "ok": True,
        "dryRun": dry_run,
        "attempt": attempt,
        "students": len(ids),
        "studentIds": ids,
        "deleted": deleted,
        "totalDocuments": total,
        "accountsDeleted": accounts,
        "protectedCollections": list(PROTECTED_COLLECTIONS),
    }

    if not dry_run:
        logger.warning(
            "[cohort-purge] purged %s students (%s documents, accounts=%s)",
            len(ids), total, accounts,
        )
        await db[ANALYTICS_AUDIT_SYNC].insert_one(
            {
                "at": _now(),
                "studentId": "*",
                "action": "cohort_purge",
                "detail": {
                    "attempt": attempt,
                    "students": len(ids),
                    "deleted": deleted,
                    "accountsDeleted": accounts,
                },
            }
        )
    return summary
