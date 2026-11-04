"""Publishing must survive a Groq outage (owner report, 15-Oct-2026).

Students were left with no target because the mentor's publish 503'd when the
AI reminder could not be generated, and "publish from a photo" failed for two
independent reasons: no GROQ_API_KEY on the service, and a vision model list
Groq had already retired. Behaviour under test:

  * a target publishes with reminderSource="pending" when AI is unavailable —
    the study tasks still reach the student, and the dashboard can retry;
  * the retry endpoint still reports the real cause instead of pretending;
  * the vision lineup defaults to a live Groq image model and is env-tunable;
  * the no-key photo error tells the mentor how to publish anyway.
"""
import asyncio
import importlib
import io

import pytest

from db import STUDENT_ACCOUNTS, get_db
from routers import daily_targets as dt
from routers import target_plans as tp

SID = "AITESTR1"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def ai_off(monkeypatch):
    """No Groq key at all — the exact live state of the deployed service."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _run(get_db()[STUDENT_ACCOUNTS].delete_many({"studentId": SID}))
    _run(get_db()[STUDENT_ACCOUNTS].insert_one({
        "studentId": SID, "studentName": "AI Test", "group": "1",
        "attempt": "Jan 2027", "batch": "BRB1", "password":"synthetic-ai-fixture",
    }))
    yield
    _run(get_db()[dt.TARGETS].delete_many({"studentId": SID}))
    _run(get_db()[dt.TARGETS].delete_many({"batch": "BRB1", "subject": "AI resilience"}))
    _run(get_db()[STUDENT_ACCOUNTS].delete_many({"studentId": SID}))


def _today():
    return dt._today().isoformat()


def test_publish_is_not_blocked_by_a_missing_ai_key(client, mentor_headers, ai_off):
    res = client.post(
        "/api/targets",
        headers=mentor_headers,
        json={
            "startDate": _today(), "attempt": "Jan 2027", "group": "1", "batch": "BRB1",
            "subject": "AI resilience",
            "tasks": [{"label": "Revise Chapter 5", "detail": ""}],
        },
    )
    assert res.status_code == 200, res.text
    target = res.json()["target"]
    assert target["reminderSource"] == "pending", target
    assert target["revisionReminder"] == ""
    assert target["tasks"][0]["label"] == "Revise Chapter 5"

    # and the student still receives the target — that is the whole point
    assert client.get(f"/api/ai/daily-target?studentId={SID}").status_code==401
    got = client.get(f"/api/ai/daily-target?studentId={SID}",headers={"X-Student-Id":SID,"X-Session-Password":"synthetic-ai-fixture"})
    assert got.status_code == 200, got.text
    labels = [task["label"] for task in got.json()["tasks"]]
    assert "Revise Chapter 5" in labels


def test_reminder_retry_endpoint_reports_the_real_cause(client, mentor_headers, ai_off):
    res = client.post(
        "/api/targets",
        headers=mentor_headers,
        json={"startDate": _today(), "subject": "AI resilience",
              "tasks": [{"label": "Revise Chapter 6", "detail": ""}]},
    )
    assert res.status_code == 200, res.text
    target_id = res.json()["target"]["id"]

    retry = client.post(f"/api/targets/{target_id}/reminder", headers=mentor_headers)
    assert retry.status_code == 503
    assert "not configured" in retry.json()["detail"]

    # the published target is untouched by the failed retry
    listed = client.get("/api/targets", headers=mentor_headers).json()["targets"]
    row = next(row for row in listed if row["id"] == target_id)
    assert row["reminderSource"] == "pending"


def test_photo_parse_without_a_key_tells_the_mentor_what_to_do(client, mentor_headers, ai_off):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )
    res = client.post(
        "/api/target-plans/parse-photo",
        headers=mentor_headers,
        files={"file": ("plan.png", io.BytesIO(png), "image/png")},
    )
    assert res.status_code == 503, res.text
    detail = res.json()["detail"]
    # The mentor is told what to do next (type or paste the rows); the message
    # must not name the AI vendor.
    assert "type or paste" in detail.lower()
    assert "photo reading is not set up" in detail.lower()


def test_vision_lineup_is_live_and_tunable(monkeypatch):
    assert tp.VISION_MODELS, "vision lineup must not be empty"
    assert not any("llama-4" in model for model in tp.VISION_MODELS), (
        "Groq retired both Llama 4 vision models (Mar/Jul 2026) — a retired id "
        "in the default lineup means photo parsing fails even with a valid key"
    )
    assert "qwen/qwen3.8-27b" in tp.VISION_MODELS

    monkeypatch.setenv("GROQ_VISION_MODELS", "acme/new-vision , acme/second")
    reloaded = importlib.reload(tp)
    try:
        assert reloaded.VISION_MODELS == ("acme/new-vision", "acme/second")
    finally:
        monkeypatch.delenv("GROQ_VISION_MODELS", raising=False)
        importlib.reload(tp)


def test_reminder_lineup_is_tunable_too(monkeypatch):
    assert dt.REMINDER_MODELS and not any("llama-4" in model for model in dt.REMINDER_MODELS)
    monkeypatch.setenv("GROQ_REMINDER_MODELS", "acme/text-a,acme/text-b")
    reloaded = importlib.reload(dt)
    try:
        assert reloaded.REMINDER_MODELS == ("acme/text-a", "acme/text-b")
    finally:
        monkeypatch.delenv("GROQ_REMINDER_MODELS", raising=False)
        importlib.reload(dt)
