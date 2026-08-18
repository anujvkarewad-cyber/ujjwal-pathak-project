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
            logger.warning("[db] using in-memory mock store (MONGO_URL=memory://) — dev/test only")
            try:
                from mongomock_motor import AsyncMongoMockClient

                _client = AsyncMongoMockClient()
            except ImportError:
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
    global _client, _db
    get_db()
    if settings.mongo_url == "memory://":
        try:
            from mongomock_motor import AsyncMongoMockClient

            _client = AsyncMongoMockClient()
            _db = _client[settings.db_name]
        except ImportError:
            raise RuntimeError("MONGO_URL=memory:// requires `mongomock-motor`")
    else:
        await _client.drop_database(settings.db_name)
        _db = _client[settings.db_name]
    try:
        from routers.student_content import invalidate_student_bank

        invalidate_student_bank()
    except Exception:
        pass


async def ensure_indexes():
    db = get_db()
    await 
