"""Backend test fixtures. MONGO_URL=memory:// (in-memory mock) — no MongoDB
server needed. All env is configured BEFORE the app/db modules are imported."""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

MENTOR_TEST_PASSWORD = "test-password-123"

# Compute the password hash BEFORE anything imports backend.config.
from passlib.context import CryptContext  # noqa: E402

os.environ.setdefault("MONGO_URL", "memory://")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")
os.environ.setdefault("MENTOR_EMAIL", "mentor@test.local")
os.environ["MENTOR_PASSWORD_HASH"] = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(MENTOR_TEST_PASSWORD)
os.environ.setdefault("DEV_AUTH_BYPASS", "0")
os.environ.setdefault("SYNC_SECRET", "test-sync-secret")
os.environ.setdefault("CONTENT_DIR", str(BACKEND_DIR / "tests" / "fixture_dist"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database_between_tests():
    """Test isolation: the in-memory store is process-global, so wipe it."""
    import asyncio

    from db import reset_db

    asyncio.run(reset_db())
    yield


@pytest.fixture(scope="session")
def mentor_password():
    return MENTOR_TEST_PASSWORD


@pytest.fixture(scope="session")
def client(mentor_password):
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def mentor_headers(client, mentor_password):
    res = client.post("/api/auth/login", json={"email": "mentor@test.local", "password": mentor_password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}
