"""JWT auth for mentor-only APIs (AI Content + Analytics).

Credentials come from env (MENTOR_EMAIL / MENTOR_PASSWORD_HASH). If no
credentials are configured, login is disabled (fail closed). DEV_AUTH_BYPASS=1
is for local development only and is documented in backend/.env.example.

Generate a hash:  python -m backend.auth hash 'password'
"""
import hashlib
import hmac
import sys
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext

from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

AUTH_SCHEME = "Bearer"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_token(email: str, role: str = "mentor") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def login_credentials_configured() -> bool:
    return bool(settings.mentor_email and settings.mentor_password_hash)


async def require_mentor(request: Request) -> dict:
    """Dependency: verifies the Bearer token and returns its claims.
    DEV_AUTH_BYPASS=1 skips verification (local development only)."""
    if settings.dev_auth_bypass:
        return {"sub": "dev-mentor", "role": "mentor"}
    auth = request.headers.get("Authorization", "")
    if not auth.startswith(f"{AUTH_SCHEME} "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth[len(AUTH_SCHEME):].strip()
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if claims.get("role") != "mentor":
        raise HTTPException(status_code=403, detail="Mentor role required")
    return claims


def sync_token(student_id: str) -> str:
    """HMAC-SHA256 device token used by the student app for /api/progress-sync."""
    if not settings.sync_secret:
        return ""
    return hmac.new(settings.sync_secret.encode(), student_id.encode(), hashlib.sha256).hexdigest()


def verify_sync_token(student_id: str, token: str) -> bool:
    if not settings.sync_secret:
        return True  # no secret configured → dev mode (documented)
    return hmac.compare_digest(sync_token(student_id), token or "")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(hash_password(sys.argv[2]))
    else:
        print("usage: python -m backend.auth hash 'password'")
