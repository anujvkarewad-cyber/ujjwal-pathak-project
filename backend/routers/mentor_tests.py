"""Mentor test authoring for the dashboard.

The Tests page could only *read* submissions (``test_history`` sync from the
student app). There was no way to create a test from the dashboard — the mentor
had to keep a separate list outside the app. This router adds the missing write
side:

* ``GET    /api/mentor/tests``              list created tests (newest first)
* ``POST   /api/mentor/tests``              create a test
* ``PATCH  /api/mentor/tests/{testId}``     edit fields
* ``POST   /api/mentor/tests/{testId}/publish``  publish / unpublish
* ``DELETE /api/mentor/tests/{testId}``     delete

Storage: ``mentor_tests`` collection (one document per test). The ``testId``
generated here is the same id the student app already sends inside
``TestHistoryItem.testId`` when a test is submitted, so definitions and
submissions line up in the Tests page as soon as the student-side channel ships.

Nothing here touches student data or the student app; this is mentor-side
authoring plus the ledger the mentor needs to know what he has set.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Literal, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from auth import require_mentor
import push as push_service
from config import settings
from db import MENTOR_TESTS, STUDENT_ACCOUNTS, get_db

router = APIRouter(prefix="/api/mentor", tags=["mentor-tests"])

KINDS = ("mcq-test", "paper-test")
TITLE_MAX = 160
SUBJECT_MAX = 80
TARGET_MAX = 80

# Dashboard file uploads (question paper / answer sheet). The browser sends
# base64 to the backend, which hands it to the mentor's Apps Script — the only
# writer that can create files in his Drive.
UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB, same cap as the app
UPLOAD_MIME_OK = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


# --------------------------------------------------------------------------- #
# payload models
# --------------------------------------------------------------------------- #
class TestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=TITLE_MAX)
    kind: Literal["mcq-test", "paper-test"] = "mcq-test"
    subject: Optional[str] = Field(default=None, max_length=SUBJECT_MAX)
    chapters: list[str] = Field(default_factory=list)
    batch: Optional[str] = Field(default=None, max_length=TARGET_MAX)
    group: Optional[str] = Field(default=None, max_length=TARGET_MAX)
    exclusiveGroup: bool = False
    test_date: Optional[str] = Field(default=None, max_length=10)      # YYYY-MM-DD
    window_start: Optional[str] = Field(default=None, max_length=32)   # ISO
    window_end: Optional[str] = Field(default=None, max_length=32)     # ISO
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=600)
    total_marks: Optional[int] = Field(default=None, ge=1, le=1000)
    question_count: Optional[int] = Field(default=None, ge=1, le=500)
    instructions: Optional[str] = Field(default=None, max_length=2000)
    # Paper-test helpers — sab optional. Student inhi se khud check karke apne
    # marks (self-evaluation) bharta hai.
    paper_url: Optional[str] = Field(default=None, max_length=400)
    answer_sheet_url: Optional[str] = Field(default=None, max_length=400)
    answer_sheet_text: Optional[str] = Field(default=None, max_length=4000)
    marking_scheme: Optional[str] = Field(default=None, max_length=4000)


class TestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=2, max_length=TITLE_MAX)
    kind: Optional[Literal["mcq-test", "paper-test"]] = None
    subject: Optional[str] = Field(default=None, max_length=SUBJECT_MAX)
    chapters: Optional[list[str]] = None
    batch: Optional[str] = Field(default=None, max_length=TARGET_MAX)
    group: Optional[str] = Field(default=None, max_length=TARGET_MAX)
    exclusiveGroup: Optional[bool] = None
    test_date: Optional[str] = Field(default=None, max_length=10)
    window_start: Optional[str] = Field(default=None, max_length=32)
    window_end: Optional[str] = Field(default=None, max_length=32)
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=600)
    total_marks: Optional[int] = Field(default=None, ge=1, le=1000)
    question_count: Optional[int] = Field(default=None, ge=1, le=500)
    instructions: Optional[str] = Field(default=None, max_length=2000)
    paper_url: Optional[str] = Field(default=None, max_length=400)
    answer_sheet_url: Optional[str] = Field(default=None, max_length=400)
    answer_sheet_text: Optional[str] = Field(default=None, max_length=4000)
    marking_scheme: Optional[str] = Field(default=None, max_length=4000)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published: bool = True


class TestUploadBody(BaseModel):
    """One file for a test — question paper ('qp') or answer sheet ('as').

    The Apps Script owns the two Drive folders (TEST_QP_FOLDER_ID /
    TEST_AS_FOLDER_ID) and shares every upload as anyone-with-link/view, which
    is exactly what the student app's in-app viewer needs.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["qp", "as"] = "qp"
    filename: str = Field(min_length=1, max_length=180)
    mimeType: str = Field(default="application/pdf", max_length=100)
    base64: str = Field(min_length=1)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def new_test_id(existing: set[str] | None = None, now_ms: int | None = None) -> str:
    """Short, sortable, human-readable id: MT-<dhm>-<4 rand chars>."""
    now = datetime.fromtimestamp((now_ms or time.time() * 1000) / 1000, tz=timezone.utc)
    stamp = now.strftime("%y%m%d%H%M")
    for _ in range(20):
        candidate = f"MT-{stamp}-{secrets.token_hex(2).upper()}"
        if not existing or candidate not in existing:
            return candidate
    raise RuntimeError("could not allocate a test id")


def clean_text(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    return text[:limit]


def clean_chapters(values: Optional[list[str]]) -> list[str]:
    out: list[str] = []
    for item in values or []:
        text = clean_text(item, 120)
        if text and text not in out:
            out.append(text)
    return out[:40]


def validate_paper_fields(payload: dict) -> Optional[str]:
    return None


def validate_exclusive_audience(payload: dict) -> str | None:
    if not payload.get("exclusiveGroup"):
        return None
    from routers.mentor_workspace import group_key
    batch = str(payload.get("batch") or "").strip().lower()
    if batch in ("", "all", "all batches", "allbatches") or group_key(payload.get("group")) == "unknown":
        return "An exclusive-group test needs one concrete batch and one existing group."
    return None


def validate_window(payload: dict) -> Optional[str]:
    """Returns an error string when window_start > window_end (both present)."""
    start = payload.get("window_start")
    end = payload.get("window_end")
    if start and end and str(start) > str(end):
        return "window_start window_end ke baad nahi ho sakta"
    return None


def build_document(payload: dict, *, test_id: str, now_ms: int, created_by: str = "mentor") -> dict:
    """Normalised mentor_tests document. Pure — safe to unit test."""
    doc = {
        "testId": test_id,
        "title": clean_text(payload.get("title"), TITLE_MAX),
        "kind": payload.get("kind") or "mcq-test",
        "subject": clean_text(payload.get("subject"), SUBJECT_MAX),
        "chapters": clean_chapters(payload.get("chapters")),
        "batch": clean_text(payload.get("batch"), TARGET_MAX),
        "group": clean_text(payload.get("group"), TARGET_MAX),
        "exclusiveGroup": bool(payload.get("exclusiveGroup")),
        "test_date": clean_text(payload.get("test_date"), 10),
        "window_start": clean_text(payload.get("window_start"), 32),
        "window_end": clean_text(payload.get("window_end"), 32),
        "duration_minutes": payload.get("duration_minutes"),
        "total_marks": payload.get("total_marks"),
        "question_count": payload.get("question_count"),
        "instructions": clean_text(payload.get("instructions"), 2000),
        "paper_url": clean_text(payload.get("paper_url"), 400),
        "answer_sheet_url": clean_text(payload.get("answer_sheet_url"), 400),
        "answer_sheet_text": clean_text(payload.get("answer_sheet_text"), 4000),
        "marking_scheme": clean_text(payload.get("marking_scheme"), 4000),
        "published": bool(payload.get("published", False)),
        "createdAt": now_ms,
        "updatedAt": now_ms,
        "createdBy": created_by,
    }
    return doc


def apply_patch(doc: dict, patch: dict, *, now_ms: int) -> dict:
    """Merge an update onto an existing document (no-op keys ignored)."""
    updated = dict(doc)
    for key, value in patch.items():
        if value is None and key not in ("published",):
            continue
        limits = {
            "instructions": 2000, "marking_scheme": 4000, "answer_sheet_text": 4000,
            "paper_url": 400, "answer_sheet_url": 400, "title": TITLE_MAX,
        }
        if key in ("title", "subject", "batch", "group", "test_date", "window_start",
                   "window_end", "instructions", "paper_url", "answer_sheet_url",
                   "answer_sheet_text", "marking_scheme"):
            updated[key] = clean_text(value, limits.get(key, TITLE_MAX))
        elif key == "chapters":
            updated[key] = clean_chapters(value)
        else:
            updated[key] = value
    updated["updatedAt"] = now_ms
    return updated


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
def _now_ms() -> int:
    return int(time.time() * 1000)


@router.get("/tests")
async def list_tests(
    published: Optional[bool] = Query(default=None),
    batch: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    """Every test created from the dashboard, newest first."""
    db = get_db()
    query: dict = {}
    if published is not None:
        query["published"] = bool(published)
    if batch:
        query["batch"] = batch

    items: list[dict] = []
    async for doc in db[MENTOR_TESTS].find(query).sort("createdAt", -1).limit(500):
        doc.pop("_id", None)
        items.append(doc)
    return {
        "items": items,
        "total": len(items),
        "publishedCount": sum(1 for i in items if i.get("published")),
    }


@router.post("/tests", status_code=201)
async def create_test(body: TestCreate, claims: dict = Depends(require_mentor)):
    """Create a test. It stays unpublished until the mentor publishes it."""
    db = get_db()
    payload = body.model_dump()
    err = validate_window(payload) or validate_paper_fields(payload) or validate_exclusive_audience(payload)
    if err:
        raise HTTPException(status_code=422, detail=err)

    existing = set()
    async for row in db[MENTOR_TESTS].find({}, {"testId": 1}):
        existing.add(row.get("testId"))
    doc = build_document(payload, test_id=new_test_id(existing), now_ms=_now_ms())
    await db[MENTOR_TESTS].insert_one(dict(doc))
    doc.pop("_id", None)
    return {"ok": True, "test": doc}


@router.patch("/tests/{test_id}")
async def update_test(test_id: str, body: TestPatch, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[MENTOR_TESTS].find_one({"testId": test_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Test nahi mila")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    err = validate_window({**doc, **patch}) or validate_paper_fields({**doc, **patch}) or validate_exclusive_audience({**doc, **patch})
    if err:
        raise HTTPException(status_code=422, detail=err)
    updated = apply_patch(doc, patch, now_ms=_now_ms())
    await db[MENTOR_TESTS].update_one({"testId": test_id}, {"$set": updated})
    updated.pop("_id", None)
    return {"ok": True, "test": updated}


def _upload_to_drive_sync(payload: dict, token: str, attempts: int = 1) -> dict:
    """One creation attempt only: an uncertain response may follow file creation.

    Keep the optional argument for internal compatibility; it never authorizes a
    duplicate creation. No upstream body, credential or exception is returned.
    """
    message = "Upload could not be confirmed. Keep the original file and check before retrying."
    try:
        resp = requests.post(settings.mentor_script_url,
            json={"action":"mentor.test.upload","payload":payload,"token":token}, timeout=180)
        data = resp.json() if resp.content else {}
    except Exception:
        raise HTTPException(status_code=502, detail=message) from None
    if resp.status_code < 200 or resp.status_code >= 300 or not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=message)
    result = data.get("result")
    if (data.get("error") or data.get("success") is False or data.get("ok") is False
        or not isinstance(result, dict) or result.get("error")
        or result.get("success") is False or result.get("ok") is False
        or not isinstance(result.get("fileId"), str) or not result["fileId"].strip()):
        raise HTTPException(status_code=502, detail=message)
    return result



@router.post("/tests/upload")
async def upload_test_file(
    body: TestUploadBody,
    request: Request,
    _mentor=Depends(require_mentor),
):
    """Upload a question paper or answer sheet for a test.

    The file lands in the mentor's Drive (question-paper / answer-sheet folder)
    and comes back as a link that the student app can open. Nothing is stored in
    Mongo here — the create/update call saves the returned URL on the test.
    """
    token = request.headers.get("Authorization", "")
    scheme, _, raw_token = token.partition(" ")
    token = raw_token.strip() if scheme.lower() == "bearer" else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    mime = str(body.mimeType or "").strip().lower() or "application/pdf"
    extension = UPLOAD_MIME_OK.get(mime)
    if not extension:
        raise HTTPException(
            status_code=422,
            detail="Only PDF, JPG or PNG files can be uploaded.",
        )

    raw = body.base64.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        content = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="The file could not be read. Try again.")
    if not content:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if len(content) > UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {UPLOAD_MAX_BYTES // (1024 * 1024)} MB. Compress the PDF and try again.",
        )

    name = re.sub(r"[^\w.\- ()\[\]]+", "_", body.filename.strip())[:180] or f"test-{body.kind}.{extension}"
    if not name.lower().endswith(f".{extension}"):
        name = f"{name}.{extension}"

    result = await asyncio.to_thread(
        _upload_to_drive_sync,
        {
            "type": body.kind,
            "base64": raw,
            "mimeType": mime,
            "filename": name,
        },
        token,
    )
    file_id = str(result.get("fileId"))
    return {
        "ok": True,
        "kind": body.kind,
        "fileId": file_id,
        "viewUrl": result.get("url") or f"https://drive.google.com/file/d/{file_id}/view",
        "downloadUrl": f"https://drive.google.com/uc?export=download&id={file_id}",
        "fileName": name,
        "bytes": len(content),
    }


def _announce_new_test(doc: dict) -> None:
    """Fire-and-forget FCM push to every student in the test's audience.

    Runs off-request (spawn), best-effort: publishing a test must never fail
    because push credentials are missing or a send errored.
    """
    async def run() -> None:
        if not push_service.configured():
            return
        db = get_db()
        ids: list[str] = []
        async for acc in db[STUDENT_ACCOUNTS].find(
            {}, {"studentId": 1, "batch": 1, "group": 1, "accessEnabled": 1}
        ):
            sid = str(acc.get("studentId") or "").strip().upper()
            # Access OFF means they cannot open the test at all - pushing it only
            # upsets them. The restore push covers the missed test instead.
            if acc.get("accessEnabled") is False:
                continue
            if sid and push_service.matches_audience(doc, acc):
                ids.append(sid)
        title = str(doc.get("title") or "New test").strip()
        subject = str(doc.get("subject") or "").strip()
        body_text = f"{subject + ' · ' if subject else ''}Open the Tests tab to attempt it."
        await push_service.push_to_students(
            ids,
            f"📝 New test published: {title}"[:200],
            body_text[:180],
            link="tests",
            tag=f"test-{doc.get('testId')}",
        )

    push_service.spawn(run())


@router.post("/tests/{test_id}/publish")
async def publish_test(test_id: str, body: PublishBody, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[MENTOR_TESTS].find_one({"testId": test_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Test nahi mila")
    was_published = bool(doc.get("published"))
    now = _now_ms()
    await db[MENTOR_TESTS].update_one(
        {"testId": test_id}, {"$set": {"published": body.published, "updatedAt": now}}
    )
    # Only on the unpublished -> published transition, never on re-publish.
    if body.published and not was_published:
        _announce_new_test(doc)
    return {"ok": True, "testId": test_id, "published": body.published, "updatedAt": now}


@router.delete("/tests/{test_id}")
async def delete_test(test_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    res = await db[MENTOR_TESTS].delete_one({"testId": test_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Test nahi mila")
    return {"ok": True, "testId": test_id}
