"""Consent + progress-summary sync tests (privacy contract, docs §9)."""
import asyncio
import hashlib
import hmac
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db import ANALYTICS_CONSENTS, ANALYTICS_SUMMARIES, get_db  # noqa: E402


def _summary(student_id="S-1001", chapter_id="ch-acc-01"):
    return {
        "studentId": student_id,
        "chapterId": chapter_id,
        "masteryBand": "Strong",
        "attemptCount": 42,
        "accuracyRange": "70-84",
        "lastActivityDate": date.today().isoformat(),
        "weakConceptTags": ["tag-a"],
    }


def _token(student_id):
    secret = "test-sync-secret"
    return hmac.new(secret.encode(), student_id.encode(), hashlib.sha256).hexdigest()


def test_sync_requires_consent(client):
    res = client.post(
        "/api/progress-sync",
        json={"studentId": "S-1001", "summaries": [_summary()]},
        headers={"X-Sync-Token": _token("S-1001")},
    )
    assert res.status_code == 403  # no consent record → sharing Off by default
    assert "disabled" in res.json()["detail"]


def test_consent_then_sync(client):
    client.post("/api/consent", json={"studentId": "S-1001", "sharing": True})
    res = client.post(
        "/api/progress-sync",
        json={"studentId": "S-1001", "summaries": [_summary()]},
        headers={"X-Sync-Token": _token("S-1001")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["accepted"]["summaries"] == 1

    async def check():
        db = get_db()
        doc = await db[ANALYTICS_SUMMARIES].find_one({"studentId": "S-1001", "chapterId": "ch-acc-01"})
        assert doc["masteryBand"] == "Strong"
        assert doc["attemptCount"] == 42
        # raw answers can never appear
        assert "answers" not in doc

    asyncio.run(check())


def test_revocation_blocks_sync(client):
    client.post("/api/consent", json={"studentId": "S-1002", "sharing": True})
    client.post("/api/progress-sync", json={"studentId": "S-1002", "summaries": [_summary("S-1002")]}, headers={"X-Sync-Token": _token("S-1002")})
    client.post("/api/consent", json={"studentId": "S-1002", "sharing": False})
    res = client.post(
        "/api/progress-sync",
        json={"studentId": "S-1002", "summaries": [_summary("S-1002")]},
        headers={"X-Sync-Token": _token("S-1002")},
    )
    assert res.status_code == 403


def test_invalid_sync_token_rejected(client):
    client.post("/api/consent", json={"studentId": "S-1003", "sharing": True})
    res = client.post(
        "/api/progress-sync",
        json={"studentId": "S-1003", "summaries": [_summary("S-1003")]},
        headers={"X-Sync-Token": "bad-token"},
    )
    assert res.status_code == 401


def test_raw_answers_rejected_by_schema(client):
    client.post("/api/consent", json={"studentId": "S-1004", "sharing": True})
    payload = {"studentId": "S-1004", "summaries": [_summary("S-1004")]}
    payload["answers"] = [{"questionId": "q1", "selected": "A"}]  # forbidden extra field
    res = client.post("/api/progress-sync", json=payload, headers={"X-Sync-Token": _token("S-1004")})
    assert res.status_code == 422


def test_rate_limit(client):
    client.post("/api/consent", json={"studentId": "S-1005", "sharing": True})
    headers = {"X-Sync-Token": _token("S-1005")}
    first = client.post("/api/progress-sync", json={"studentId": "S-1005", "summaries": [_summary("S-1005")]}, headers=headers)
    second = client.post("/api/progress-sync", json={"studentId": "S-1005", "summaries": [_summary("S-1005")]}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 429
