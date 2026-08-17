"""Database access (Motor). MONGO_URL=memory:// uses the in-memory mock so the
backend and its tests run without a MongoDB server; any other value behaves
exactly as before (real MongoDB via the official async driver)."""
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
            logger.warning("[db] using in-memory mock store (MONGO_URL=memory://) — dev/test only")
            try:
                from mongomock_motor import AsyncMongoMockClient

                _client = AsyncMongoMockClient()
            except ImportError:  # pragma: no cover
                raise RuntimeError(
                    "MONGO_URL=memory:// requires `mongomock-motor` (pip install mongomock-motor)"
                )
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
    """Test helper: wipe the database. For the in-memory mock this replaces
    the client entirely; for real MongoDB it drops the database."""
    global _client, _db
    db = get_db()
    if settings.mongo_url == "memory://":
        try:
            from mongomock_motor import AsyncMongoMockClient

            _client = AsyncMongoMockClient()
            _db = _client[settings.db_name]
        except ImportError:  # pragma: no cover
            raise RuntimeError("MONGO_URL=memory:// requires `mongomock-motor`")
    else:
        await _client.drop_database(settings.db_name)
        _db = _client[settings.db_name]


async def ensure_indexes():
    db = get_db()
    await db[CONTENT_QUESTIONS].create_index([("chapterId", 1), ("status", 1)])
    await db[CONTENT_QUESTIONS].create_index("id")
    await db[CONTENT_QUESTIONS].create_index("status")
    await db[CONTENT_SCENARIOS].create_index([("chapterId", 1), ("status", 1)])
    await db[CONTENT_SCENARIOS].create_index("scenarioId")
    await db[CONTENT_CHAPTERS].create_index("chapterId")
    await db[CONTENT_RELEASES].create_index("revision")
    await db[CONTENT_AUDIT].create_index("at")
    await db[ANALYTICS_SUMMARIES].create_index([("studentId", 1), ("chapterId", 1)])
    await db[ANALYTICS_CONSENTS].create_index("studentId")
    await db[ANALYTICS_TRENDS].create_index([("studentId", 1), ("chapterId", 1)])
    await db[STUDENT_MCQ_ATTEMPTS].create_index(
        [("studentId", 1), ("kind", 1), ("attemptId", 1)], unique=True
    )
    await db[STUDENT_MCQ_ATTEMPTS].create_index([("studentId", 1), ("completedAt", -1)])
