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
    # Connections per process. Serverless hosts (Cloud Run) run several
    # instances, and Motor's default pool of 100 each would blow past the
    # 500-connection limit of an Atlas M0/M2 cluster. 20 × 10 instances = 200.
    mongo_max_pool_size: int = _int("MONGO_MAX_POOL_SIZE", 20)
    mongo_min_pool_size: int = _int("MONGO_MIN_POOL_SIZE", 0)

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
    # Optional header for the one-shot Students-sheet → Mongo import. The same
    # secret authenticates server-to-server mentor batch changes; it is never
    # sent to the browser.
    student_import_key: str = os.environ.get("STUDENT_IMPORT_KEY") or ""
    student_admin_script_url: str = os.environ.get(
        "STUDENT_ADMIN_SCRIPT_URL",
        "https://script.google.com/macros/s/AKfycbyWjeCaMGwCnG5h2M5gjLsURcnBz8tOxoNzd2sZoLlBB8IA5FygE4WQKB1YEcGwpoPHfg/exec",
    )
    # The mentor's own Google Apps Script ("Mentor Dashboard API"). Test file
    # uploads go through it because only the script's owner (the mentor) can
    # create files in his Drive — a service account has zero storage quota.
    mentor_script_url: str = os.environ.get(
        "MENTOR_SCRIPT_URL",
        "https://script.google.com/macros/s/AKfycbzyfWa8agayMB0XLjkbfhfj2MdIRElAiY2Wnd7-eQKd1zlMl099ky6Cif06TWydzr8D/exec",
    )
    mcq_daily_retention: int = _int("MCQ_DAILY_RETENTION", 180)
    mcq_practice_retention: int = _int("MCQ_PRACTICE_RETENTION", 150)

    # If the store has questions but zero are published (typical after a
    # Mongo restore of the needs_review snapshot), publish them on boot so
    # students keep seeing the bank. Set AUTO_PUBLISH_IF_EMPTY=0 to disable.
    auto_publish_if_empty: bool = _int("AUTO_PUBLISH_IF_EMPTY", 1) == 1


settings = Settings()
