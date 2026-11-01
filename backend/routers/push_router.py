"""Device-token registration for the student app + push diagnostics.

POST /api/push/device-token requires the authenticated student: installed APKs already call the
`saveDeviceToken` proxy action after login, and the gateway forwards it here.
GET /api/push/status is mentor-only and answers "is push actually wired up?".
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import push as push_service
from routers.dashboard_access import dashboard_student, own_payload
from auth import require_mentor
from db import DEVICE_TOKENS, get_db

router = APIRouter(prefix="/api/push", tags=["push"])


class DeviceTokenBody(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    token: str = Field(min_length=20, max_length=4096)


@router.post("/device-token")
async def register_device_token(body: DeviceTokenBody, principal=Depends(dashboard_student)):
    payload = own_payload(principal, {"studentId":body.studentId})
    ok = await push_service.save_device_token(payload["studentId"], body.token)
    if not ok:
        return {"result": {"success": False, "message": "Invalid token."}}
    return {"result": {"success": True}}


@router.post("/device-token/remove")
async def remove_device_token(body: DeviceTokenBody, principal=Depends(dashboard_student)):
    payload = own_payload(principal, {"studentId": body.studentId})
    await push_service.remove_device_token(payload["studentId"], body.token)
    return {"result": {"success": True}}


@router.get("/status")
async def status(claims: dict = Depends(require_mentor)):
    db = get_db()
    tokens = await db[DEVICE_TOKENS].count_documents({})
    students = len(await db[DEVICE_TOKENS].distinct("studentId"))
    return {
        "ok": True,
        "configured": push_service.configured(),
        "tokens": tokens,
        "studentsWithDevices": students,
    }
