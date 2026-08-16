"""Mentor login (JWT). Credentials come from env; if unconfigured, login
fails closed (503) so content/analytics APIs stay inaccessible."""
from fastapi import APIRouter, HTTPException

from auth import create_token, login_credentials_configured, verify_password
from config import settings
from models import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest):
    if not login_credentials_configured():
        raise HTTPException(status_code=503, detail="Mentor credentials are not configured on this deployment")
    if body.email.strip().lower() != settings.mentor_email.lower() or not verify_password(
        body.password, settings.mentor_password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(settings.mentor_email), "email": settings.mentor_email, "role": "mentor"}
