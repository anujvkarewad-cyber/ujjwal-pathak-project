"""POST /api/targets/complete — a tick belongs to the day it was made on.

The day-wise screen lets a student open one plan day at a time and catch up on a
day that is not the calendar's today. The endpoint used to stamp every tick with
`today`, so a tick made on Day 7 was stored under Day 20's date and the day the
student was looking at never filled up (found 22-Nov-2026).

These tests pin the contract:
  * no `date`  -> today (the old single-day behaviour, unchanged)
  * `date`     -> that day
  * `done:false` -> the row is removed, so Undo actually undoes
  * junk date  -> falls back to today instead of writing somewhere arbitrary
"""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from auth import hash_password

SID = "COMPLETE_DATE_1"
PASSWORD = "complete-date-synthetic-password"
HEADERS = {"X-Student-Id": SID, "X-Session-Password": PASSWORD}
DONE = "daily_target_done"


@pytest.fixture
def client():
    from server import app
    return TestClient(app)


@pytest.fixture
def seeded():
    from db import STUDENT_ACCOUNTS, get_db

    async def setup():
        db = get_db()
        await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": SID},
            {"$set": {"studentId": SID, "passwordHash": hash_password(PASSWORD),
                      "batch": "LOCAL BATCH", "group": "Group 1",
                      "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )
        await db[DONE].delete_many({"studentId": SID})

    asyncio.run(setup())
    return SID


def _rows(student_id):
    from db import get_db

    async def read():
        return await get_db()[DONE].find(
            {"studentId": student_id}, {"_id": 0, "date": 1, "taskId": 1}
        ).to_list(100)

    return asyncio.run(read())


def test_tick_without_a_date_lands_on_today(client, seeded):
    res = client.post("/api/targets/complete", headers=HEADERS,
                      json={"studentId": seeded, "taskId": "d20-a"})
    assert res.status_code == 200 and res.json()["ok"] is True
    assert _rows(seeded) == [{"date": date.today().isoformat(), "taskId": "d20-a"}]


def test_tick_lands_on_the_day_the_student_has_open(client, seeded):
    # Day 1 of the batch calendar, opened weeks after it passed.
    plan_date = (date.today() - timedelta(days=20)).isoformat()
    res = client.post("/api/targets/complete", headers=HEADERS,
                      json={"studentId": seeded, "taskId": "d1-a", "date": plan_date})
    assert res.status_code == 200
    assert _rows(seeded) == [{"date": plan_date, "taskId": "d1-a"}]


def test_untick_removes_the_row(client, seeded):
    plan_date = (date.today() - timedelta(days=20)).isoformat()
    body = {"studentId": seeded, "taskId": "d1-a", "date": plan_date}
    client.post("/api/targets/complete", headers=HEADERS, json=body)
    assert len(_rows(seeded)) == 1

    body["done"] = False
    res = client.post("/api/targets/complete", headers=HEADERS, json=body)
    assert res.status_code == 200
    assert _rows(seeded) == []


def test_two_days_stay_separate(client, seeded):
    old = (date.today() - timedelta(days=20)).isoformat()
    newer = (date.today() - timedelta(days=5)).isoformat()
    for task, when in (("d1-a", old), ("d1-b", old), ("d3-a", newer)):
        client.post("/api/targets/complete", headers=HEADERS,
                    json={"studentId": seeded, "taskId": task, "date": when})
    got = sorted((r["date"], r["taskId"]) for r in _rows(seeded))
    assert got == sorted([(old, "d1-a"), (old, "d1-b"), (newer, "d3-a")])


@pytest.mark.parametrize("junk", ["", "not-a-date", "2020-01-01", "2099-12-31"])
def test_unusable_date_falls_back_to_today(client, seeded, junk):
    client.post("/api/targets/complete", headers=HEADERS,
                json={"studentId": seeded, "taskId": "x1", "date": junk})
    assert _rows(seeded) == [{"date": date.today().isoformat(), "taskId": "x1"}]


def test_tick_needs_the_owning_session(client, seeded):
    assert client.post("/api/targets/complete",
                       json={"studentId": seeded, "taskId": "d1-a"}).status_code == 401
