"""Database access (Motor)."""
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

logger = logging.getLogger(__name__)
_client = None
_db = None

CONTENT_QUESTIONS = "content_questions"
CONTENT_SCENARIOS = "content_scenarios"
CONTENT_CHAPTERS = "content_chapters"
CONTENT_RELEASES = "content_releases"
CONTENT_AUDIT = "content_audit"
ANALYTICS_CONSENTS = "analytics_consents"
ANALYTICS_SUMMARIES = "analytics_summaries"
ANALYTICS_TRENDS = "analytics_trends"
ANALYTICS_FOLLOWUPS = "analytics_followups"
ANALYTICS_AUDIT_SYNC = "analytics_audit_sync"
STUDENT_MCQ_ATTEMPTS = "student_mcq_attempts"


def get_db():
    global _client, _db
    if _db is None:
        if settings.mongo_url == "memory://":
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(settings.mongo_url)
        _db = _client[settings.db_name]
    return _db


async def close_db():
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


async def reset_db():
    global _client, _db
    get_db()
    if settings.mongo_url == "memory://":
        from mongomock_motor import AsyncMongoMockClient
        _client = AsyncMongoMockClient()
        _db = _client[settings.db_name]
    else:
        await _client.drop_database(settings.db_name)
        _db = _client[settings.db_name]


async def ensure_indexes():
    db = get_db()
    await db[CONTENT_QUESTIONS].create_index("id")
    await db[CONTENT_QUESTIONS].create_index("status")
    await db[CONTENT_SCENARIOS].create_index("scenarioId")
    await db[CONTENT_CHAPTERS].create_index("chapterId")
    await db[CONTENT_RELEASES].create_index("revision")
    await db[STUDENT_MCQ_ATTEMPTS].create_index(
        [("studentId", 1), ("kind", 1), ("attemptId", 1)], unique=True
    )


async def ensure_unique_indexes():
    db = get_db()
    try:
        await db[CONTENT_QUESTIONS].create_index(
            [("id", 1), ("revision", 1)], unique=True, name="id_revision_unique"
        )
        await db[CONTENT_SCENARIOS].create_index(
            "scenarioId", unique=True, name="scenarioId_unique"
        )
        await db[CONTENT_CHAPTERS].create_index(
            "chapterId", unique=True, name="chapterId_unique"
        )
    except Exception as exc:
        logger.warning("[db] unique index skip: %s", exc)


# END OF FILE
