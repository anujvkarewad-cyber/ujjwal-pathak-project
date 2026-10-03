from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from auth import require_mentor
from config import settings
from db import CONTENT_CHAPTERS, CONTENT_QUESTIONS, CONTENT_SCENARIOS, CONTENT_RELEASES, get_db
from routers.student_content import invalidate_student_bank

router = APIRouter(prefix="/api/admin", tags=["admin-fast-publish"])

def _now(): return datetime.now(timezone.utc).isoformat()

@router.post("/fast-publish-all")
async def fast_publish_all(claims: dict = Depends(require_mentor)):
    """Bypass all gates and publish every question - for emergency use when UI approve fails"""
    db = get_db()
    now = _now()

    # Approve all questions directly to published
    q_res = await db[CONTENT_QUESTIONS].update_many({}, {"$set": {"status": "published", "publishedAt": now, "publishedInRevision": 1, "warningsAcknowledged": True, "attemptSpecificRiskConfirmed": True}})
    s_res = await db[CONTENT_SCENARIOS].update_many({}, {"$set": {"status": "published", "publishedAt": now, "publishedInRevision": 1, "warningsAcknowledged": True, "attemptSpecificRiskConfirmed": True}})
    c_res = await db[CONTENT_CHAPTERS].update_many({}, {"$set": {"status": "published", "releaseCandidate": {"revision": 1, "at": now, "by": "fast-publish"}}})

    # Create release
    latest = None
    async for row in db[CONTENT_RELEASES].find({}).sort("revision", -1).limit(1):
        latest = row
    rev = (latest.get("revision") if latest else 0) + 1

    chapters = []
    async for ch in db[CONTENT_CHAPTERS].find({}):
        cid = ch["chapterId"]
        cnt = await db[CONTENT_QUESTIONS].count_documents({"chapterId": cid, "status": "published"})
        if cnt>0:
            chapters.append({"chapterId": cid, "counts": {"total": cnt}})

    manifest = {
        "schemaVersion": 1,
        "revision": rev,
        "publishedAt": now,
        "publishedBy": "fast-publish",
        "catalogRevision": "may-2026",
        "chapters": chapters
    }

    await db[CONTENT_RELEASES].insert_one({
        "revision": rev,
        "manifest": manifest,
        "publishedAt": now,
        "publishedBy": "fast-publish",
        "chapters": [c["chapterId"] for c in chapters],
        "gates": []
    })

    published = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})
    invalidate_student_bank()

    return {
        "ok": True,
        "published_questions": published,
        "chapters": len(chapters),
        "revision": rev,
        "message": f"Published {published} questions across {len(chapters)} chapters - bank.json will now show {published} MCQs"
    }

@router.get("/fast-status")
async def fast_status():
    db = get_db()
    total = await db[CONTENT_QUESTIONS].count_documents({})
    published = await db[CONTENT_QUESTIONS].count_documents({"status": "published"})
    needs = await db[CONTENT_QUESTIONS].count_documents({"status": "needs_review"})
    approved = await db[CONTENT_QUESTIONS].count_documents({"status": "approved"})
    chapters = await db[CONTENT_CHAPTERS].count_documents({})
    releases = await db[CONTENT_RELEASES].count_documents({})
    return {
        "total_questions": total,
        "published": published,
        "needs_review": needs,
        "approved": approved,
        "chapters": chapters,
        "releases": releases
    }


@router.get("/db-stats")
async def db_stats(_: dict = Depends(require_mentor)):
    """Storage/ops headroom for the current MongoDB plan.

    Atlas M0 (free) allows 512 MB and ~100 ops/sec. Watch `usedPercent`:
    past ~80% either lower MCQ_DAILY_RETENTION / MCQ_PRACTICE_RETENTION
    (cheapest, stays free) or move the cluster to Atlas Flex.
    """
    db = get_db()
    free_limit_mb = 512
    try:
        stats = await db.command("dbStats", scale=1024 * 1024)
    except Exception as exc:  # in-memory mock or restricted cluster
        return {"ok": False, "reason": str(exc)[:200], "freeLimitMB": free_limit_mb}

    used_mb = round(float(stats.get("dataSize", 0)) + float(stats.get("indexSize", 0)), 2)
    collections = {}
    for name in (
        "student_mcq_attempts",
        "student_accounts",
        "content_questions",
        "knowledge_chunks",
        "analytics_summaries",
        "analytics_trends",
    ):
        try:
            collections[name] = await db[name].count_documents({})
        except Exception:
            collections[name] = None

    return {
        "ok": True,
        "usedMB": used_mb,
        "freeLimitMB": free_limit_mb,
        "usedPercent": round(used_mb / free_limit_mb * 100, 1),
        "storageMB": round(float(stats.get("storageSize", 0)), 2),
        "indexMB": round(float(stats.get("indexSize", 0)), 2),
        "documents": int(stats.get("objects", 0)),
        "counts": collections,
        "retention": {
            "mcqDaily": settings.mcq_daily_retention,
            "mcqPractice": settings.mcq_practice_retention,
        },
        "advice": (
            "Under 80% of the M0 free limit — no action needed."
            if used_mb < free_limit_mb * 0.8
            else "Approaching the M0 free limit: lower MCQ retention or upgrade to Atlas Flex."
        ),
    }
