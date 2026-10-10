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

import re
import secrets
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import require_mentor
from db import MENTOR_TESTS, get_db

router = APIRouter(prefix="/api/mentor", tags=["mentor-tests"])

KINDS = ("mcq-test", "paper-test")
TITLE_MAX = 160
SUBJECT_MAX = 80
TARGET_MAX = 80


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
    err = validate_window(payload) or validate_paper_fields(payload)
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
    err = validate_window({**doc, **patch}) or validate_paper_fields({**doc, **patch})
    if err:
        raise HTTPException(status_code=422, detail=err)
    updated = apply_patch(doc, patch, now_ms=_now_ms())
    await db[MENTOR_TESTS].update_one({"testId": test_id}, {"$set": updated})
    updated.pop("_id", None)
    return {"ok": True, "test": updated}


@router.post("/tests/{test_id}/publish")
async def publish_test(test_id: str, body: PublishBody, claims: dict = Depends(require_mentor)):
    db = get_db()
    doc = await db[MENTOR_TESTS].find_one({"testId": test_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Test nahi mila")
    now = _now_ms()
    await db[MENTOR_TESTS].update_one(
        {"testId": test_id}, {"$set": {"published": body.published, "updatedAt": now}}
    )
    return {"ok": True, "testId": test_id, "published": body.published, "updatedAt": now}


@router.delete("/tests/{test_id}")
async def delete_test(test_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    res = await db[MENTOR_TESTS].delete_one({"testId": test_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Test nahi mila")
    return {"ok": True, "testId": test_id}
