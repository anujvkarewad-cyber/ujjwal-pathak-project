"""Central configuration for the mentor backend.

Loads .env (gitignored). Production behavior is unchanged when MONGO_URL and
DB_NAME are set as before; `MONGO_URL=memory://` (or missing MONGO_URL in a
dev/test environment) selects the in-memory mock store.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    mongo_url: str = os.environ.get("MONGO_URL") or "memory://"
    db_name: str = os.environ.get("DB_NAME") or "ujjwal_pathak"

    jwt_secret: str = os.environ.get("JWT_SECRET") or "dev-secret-do-not-use-in-prod"
    mentor_email: str = os.environ.get("MENTOR_EMAIL") or "mentor@ujjwalpathak.in"
    mentor_password_hash: str = os.environ.get("MENTOR_PASSWORD_HASH") or ""
    # Multiple mentor logins: "email1:password1,email2:password2" (dev/demo).
    # Production deployments should prefer MENTOR_PASSWORD_HASH.
    mentor_accounts: str = os.environ.get("MENTOR_ACCOUNTS") or ""
    jwt_expires_minutes: int = _int("JWT_EXPIRES_MINUTES", 720)
    dev_auth_bypass: bool = _int("DEV_AUTH_BYPASS", 0) == 1

    cors_origins: str = os.environ.get("CORS_ORIGINS", "*")

    content_dir: Path = Path(os.environ.get("CONTENT_DIR", str(ROOT_DIR.parent / "content-pipeline" / "dist")))
    public_content_base_url: str = os.environ.get(
        "PUBLIC_CONTENT_BASE_URL", "http://localhost:8000/api/content/student"
    )

    sync_secret: str = os.environ.get("SYNC_SECRET", "")
    sync_max_summaries: int = _int("SYNC_MAX_SUMMARIES", 94)
    sync_rate_limit_seconds: int = _int("SYNC_RATE_LIMIT_SECONDS", 300)

    # Student login lives in Mongo (`student_accounts`). Apps Script remains
    # the fallback until a student has been imported.
    student_auth_url: str = os.environ.get(
        "STUDENT_AUTH_URL",
        "https://student-dashboard-frontend-iota.vercel.app/api/proxy",
    )
    # Optional header for the one-shot Students-sheet → Mongo import.
    student_import_key: str = os.environ.get("STUDENT_IMPORT_KEY") or ""
    mcq_daily_retention: int = _int("MCQ_DAILY_RETENTION", 180)
    mcq_practice_retention: int = _int("MCQ_PRACTICE_RETENTION", 150)

    # If the store has questions but zero are published (typical after a
    # Mongo restore of the needs_review snapshot), publish them on boot so
    # students keep seeing the bank. Set AUTO_PUBLISH_IF_EMPTY=0 to disable.
    auto_publish_if_empty: bool = _int("AUTO_PUBLISH_IF_EMPTY", 1) == 1


settings = Settings()
