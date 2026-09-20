"""Mentor login (JWT). Credentials come from env; if unconfigured, login
fails closed (503) so content/analytics APIs stay inaccessible."""
from fastapi import APIRouter, HTTPException

from auth import create_token, login_credentials_configured, verify_mentor_login
from models import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest):
    if not login_credentials_configured():
        raise HTTPException(status_code=503, detail="Mentor credentials are not configured on this deployment")
    matched = verify_mentor_login(body.email, body.password)
    if not matched:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(matched), "email": matched, "role": "mentor"}
