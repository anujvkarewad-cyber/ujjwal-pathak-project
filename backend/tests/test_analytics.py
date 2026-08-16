"""Analytics API tests over consented summaries (docs §8)."""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db import ANALYTICS_CONSENTS, ANALYTICS_SUMMARIES, ANALYTICS_TRENDS, get_db  # noqa: E402


async def _seed():
    db = get_db()
    # idempotent seeding (tests share one in-memory store)
    for sid in ("S-2001", "S-2002", "S-2003"):
        await db[ANALYTICS_CONSENTS].delete_many({"studentId": sid})
        await db[ANALYTICS_SUMMARIES].delete_many({"studentId": sid})
        await db[ANALYTICS_TRENDS].delete_many({"studentId": sid})
    students = [
        ("S-2001", True, "Strong", 0),
        ("S-2002", True, "Weak", 20),
        ("S-2003", False, "Medium", 3),  # sharing off — must be excluded
    ]
    for sid, sharing, band, inactive_days in students:
        await db[ANALYTICS_CONSENTS].insert_one({"studentId": sid, "sharing": sharing})
        if not sharing:
            continue
        await db[ANALYTICS_SUMMARIES].insert_one({
            "studentId": sid,
            "chapterId": "ch-acc-01",
            "subject": "Accounting",
            "group": "Group 1",
            "masteryBand": band,
            "attemptCount": 10,
            "accuracyRange": "0-49" if band == "Weak" else "70-84",
            "lastActivityDate": (date.today() - timedelta(days=inactive_days)).isoformat(),
            "weakConceptTags": ["tag-a"] if band == "Weak" else [],
        })
    # improving trend for S-2001, declining for S-2002
    base = date.today() - timedelta(weeks=3)
    for w, band in enumerate(["Weak", "Medium", "Strong"]):
        await db[ANALYTICS_TRENDS].insert_one({
            "studentId": "S-2001", "chapterId": "ch-acc-01", "weekStart": (base + timedelta(weeks=w)).isoformat(),
            "masteryBand": band, "attemptCount": 10, "accuracyRange": "70-84",
        })
    for w, band in enumerate(["Mastered", "Medium", "Weak"]):
        await db[ANALYTICS_TRENDS].insert_one({
            "studentId": "S-2002", "chapterId": "ch-acc-01", "weekStart": (base + timedelta(weeks=w)).isoformat(),
            "masteryBand": band, "attemptCount": 10, "accuracyRange": "0-49",
        })


def _run_seed():
    asyncio.run(_seed())


def test_overview_excludes_sharing_off(client, mentor_headers):
    _run_seed()
    res = client.get("/api/analytics/overview", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["consentOnStudents"] == 2  # S-2003 excluded
    assert body["bandDistribution"]["Weak"] == 1
    assert body["bandDistribution"]["Strong"] == 1


def test_student_analysis(client, mentor_headers):
    _run_seed()
    res = client.get("/api/analytics/students/S-2002", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sharing"] is True
    assert body["weakChapters"][0]["chapterId"] == "ch-acc-01"
    assert "tag-a" in body["weakConcepts"]
    assert body["decliningChapters"] == ["ch-acc-01"]

    res = client.get("/api/analytics/students/S-2003", headers=mentor_headers)
    assert res.json()["sharing"] is False
    assert res.json()["summaries"] == []


def test_heatmap(client, mentor_headers):
    _run_seed()
    res = client.get("/api/analytics/heatmap", headers=mentor_headers)
    assert res.status_code == 200
    body = res.json()
    cells = {c["studentId"]: c for c in body["cells"]}
    assert "S-2003" not in cells  # sharing off
    assert cells["S-2001"]["masteryBand"] == "Strong"
    assert cells["S-2001"]["inactive"] is False
    assert cells["S-2002"]["masteryBand"] == "Weak"
    assert cells["S-2002"]["inactive"] is True  # 20 days inactive
    assert body["chapters"] == ["ch-acc-01"]

    band_filter = client.get("/api/analytics/heatmap?band=Weak", headers=mentor_headers).json()
    assert [c["studentId"] for c in band_filter["cells"]] == ["S-2002"]


def test_weak_chapters_and_groups(client, mentor_headers):
    _run_seed()
    weak = client.get("/api/analytics/weak-chapters", headers=mentor_headers).json()
    assert weak["items"][0]["chapterId"] == "ch-acc-01"
    assert weak["items"][0]["weakStudents"] == 1

    groups = client.get("/api/analytics/groups", headers=mentor_headers).json()
    assert groups["items"][0]["group"] == "Group 1"
    assert groups["items"][0]["bandCounts"]["Weak"] == 1


def test_at_risk_and_improvement(client, mentor_headers):
    _run_seed()
    at_risk = client.get("/api/analytics/at-risk", headers=mentor_headers).json()
    assert [i["studentId"] for i in at_risk["items"]] == ["S-2002"]

    improvement = client.get("/api/analytics/improvement", headers=mentor_headers).json()
    by_student = {i["studentId"]: i for i in improvement["items"]}
    assert by_student["S-2001"]["improvingChapters"] == ["ch-acc-01"]
    assert by_student["S-2002"]["decliningChapters"] == ["ch-acc-01"]


def test_followups(client, mentor_headers):
    _run_seed()
    created = client.post(
        "/api/analytics/followups",
        headers=mentor_headers,
        json={"studentId": "S-2002", "title": "Intervention for weak chapter", "priority": "high", "rule": "declining_trend"},
    )
    assert created.status_code == 200, created.text
    followup_id = created.json()["followupId"]

    listing = client.get("/api/analytics/followups?studentId=S-2002", headers=mentor_headers).json()
    assert listing["items"][0]["status"] == "open"

    updated = client.post(
        f"/api/analytics/followups/{followup_id}",
        headers=mentor_headers,
        json={"status": "completed", "note": "Mentor called the student"},
    )
    assert updated.status_code == 200
    listing = client.get("/api/analytics/followups?studentId=S-2002", headers=mentor_headers).json()
    assert listing["items"][0]["status"] == "completed"
    assert listing["items"][0]["notes"][0]["note"] == "Mentor called the student"

    overview = client.get("/api/analytics/overview", headers=mentor_headers).json()
    assert overview["openFollowups"] == 0


def test_inactive_listing(client, mentor_headers):
    _run_seed()
    res = client.get("/api/analytics/inactive", headers=mentor_headers)
    items = res.json()["items"]
    assert any(i["studentId"] == "S-2002" for i in items)
    assert not any(i["studentId"] == "S-2001" for i in items)
