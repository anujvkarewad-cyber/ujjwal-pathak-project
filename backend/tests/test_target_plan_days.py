"""GET /api/ai/target-plan-days — the app's day strip (synthetic data only).

The installed Android app has always called this endpoint from the Daily Target
screen. It was never implemented, so every open returned 404 (93 times in 24 h
on 03-04 Nov 2026). These tests pin the contract the app expects.
"""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from auth import hash_password

SID = "LOCAL_PLAN_1"
PASSWORD = "local-synthetic-password"
HEADERS = {"X-Student-Id": SID, "X-Session-Password": PASSWORD}


@pytest.fixture
def client():
    from server import app
    return TestClient(app)


@pytest.fixture
def seeded():
    from db import STUDENT_ACCOUNTS, get_db

    today = date.today()

    async def setup():
        db = get_db()
        await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": SID},
            {"$set": {"studentId": SID, "passwordHash": hash_password(PASSWORD),
                      "batch": "LOCAL BATCH", "group": "Group 1",
                      "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )
        for day in (1, 2, 3):
            await db["daily_targets"].update_one(
                {"_id": f"plan-day-{day}"},
                {"$set": {"_id": f"plan-day-{day}", "id": f"plan-day-{day}", "active": True,
                          "attempt": "Jan 2027", "batch": "LOCAL BATCH", "group": "Group 1",
                          "planId": "tp-local", "planDay": day, "subject": "Accounts",
                          "startDate": (today + timedelta(days=day - 1)).isoformat(),
                          "endDate": (today + timedelta(days=day - 1)).isoformat(),
                          "tasks": [{"id": f"d{day}-a", "label": f"Day {day} A", "detail": "ch1", "kind": "chapter"},
                                    {"id": f"d{day}-b", "label": f"Day {day} B", "detail": "ch2", "kind": "chapter"}]}},
                upsert=True,
            )
        await db["daily_target_done"].update_one(
            {"studentId": SID, "date": today.isoformat(), "taskId": "d1-a"},
            {"$set": {"doneAt": "synthetic"}}, upsert=True,
        )

    asyncio.run(setup())
    return SID


def test_endpoint_is_registered(client):
    assert "get" in client.get("/openapi.json").json()["paths"]["/api/ai/target-plan-days"]


def test_returns_every_published_day_with_ticks(client, seeded):
    res = client.get(f"/api/ai/target-plan-days?studentId={seeded}", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["today"] == date.today().isoformat()
    assert [d["day"] for d in body["days"]] == [1, 2, 3]
    assert body["days"][0]["isToday"] is True
    assert body["days"][1]["isToday"] is False
    done = {t["id"]: t["done"] for t in body["days"][0]["tasks"]}
    assert done == {"d1-a": True, "d1-b": False}
    # past days stay visible once the plan is longer than today
    assert all(d["date"] for d in body["days"])


def test_requires_the_owning_session(client, seeded):
    assert client.get(f"/api/ai/target-plan-days?studentId={seeded}").status_code == 401
    assert client.get("/api/ai/target-plan-days?studentId=UMP9999", headers=HEADERS).status_code == 403


def test_student_without_targets_gets_an_empty_list(client, seeded):
    from db import STUDENT_ACCOUNTS, get_db

    other = "LOCAL_PLAN_2"

    async def setup():
        await get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": other},
            {"$set": {"studentId": other, "passwordHash": hash_password(PASSWORD),
                      "batch": "NO SUCH BATCH", "group": "Group 1",
                      "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )

    asyncio.run(setup())
    res = client.get(f"/api/ai/target-plan-days?studentId={other}",
                     headers={"X-Student-Id": other, "X-Session-Password": PASSWORD})
    assert res.status_code == 200
    assert res.json()["days"] == []


def _publish(group, batch, day, plan_id="tp-aud", subject="Accounts"):
    async def run():
        from db import get_db
        await get_db()["daily_targets"].update_one(
            {"_id": f"{plan_id}-{batch}-{group}-{day}"},
            {"$set": {"_id": f"{plan_id}-{batch}-{group}-{day}", "id": f"{plan_id}-{group}-{day}",
                      "active": True, "attempt": "Jan 2027", "batch": batch, "group": group,
                      "planId": plan_id, "planDay": day, "subject": subject,
                      "startDate": date.today().isoformat(), "endDate": date.today().isoformat(),
                      "tasks": [{"id": f"{plan_id}-{group}-d{day}", "label": "task", "detail": "",
                                 "kind": "chapter"}]}},
            upsert=True,
        )
    asyncio.run(run())


def _student(sid, group, batch):
    async def run():
        from db import STUDENT_ACCOUNTS, get_db
        await get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "passwordHash": hash_password(PASSWORD),
                      "batch": batch, "group": group, "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )
    asyncio.run(run())


def test_a_both_groups_plan_reaches_group1_and_group2_of_that_batch_only(client):
    """One batch plan published as "Both Groups" is that batch's target for G1 and G2.

    After Result Batch 1 had 34 students with a target and 177 without, purely
    because the plan carried the "Both Groups" label.

    The subject is "All" here on purpose: a "Both Groups" plan publishes EVERY
    subject, and a student only ever sees the papers of their own group (the
    rule pinned in test_target_audience_and_days.py - a Group 2 student must
    not be shown Advanced Accounting / Taxation). This test pins the GROUP
    routing; the paper routing is pinned there.
    """
    batch = "ARB1-AUDIENCE"
    _student("AUD-G1", "Group 1", batch)
    _student("AUD-G2", "Group 2", batch)
    _student("AUD-OTHER", "Group 1", "SOME OTHER BATCH")
    _publish("Both", batch, 1, subject="All")

    for sid in ("AUD-G1", "AUD-G2"):
        res = client.get(f"/api/ai/target-plan-days?studentId={sid}",
                         headers={"X-Student-Id": sid, "X-Session-Password": PASSWORD})
        assert res.status_code == 200, sid
        assert len(res.json()["days"]) == 1, sid

    # Never crosses into another batch.
    res = client.get("/api/ai/target-plan-days?studentId=AUD-OTHER",
                     headers={"X-Student-Id": "AUD-OTHER", "X-Session-Password": PASSWORD})
    assert res.json()["days"] == []


def test_a_single_group_plan_does_not_leak_to_the_other_group(client):
    """A plan published for one group never reaches the other group of the batch.

    The subject is a Group 2 paper on purpose, so the only thing that can keep
    the Group 1 student out is the group routing itself.
    """
    batch = "ARB1-LEAK"
    _student("LEAK-G1", "Group 1", batch)
    _student("LEAK-G2", "Group 2", batch)
    _publish("Group 2", batch, 1, plan_id="tp-leak", subject="Cost and Management Accounting")

    g2 = client.get("/api/ai/target-plan-days?studentId=LEAK-G2",
                    headers={"X-Student-Id": "LEAK-G2", "X-Session-Password": PASSWORD})
    g1 = client.get("/api/ai/target-plan-days?studentId=LEAK-G1",
                    headers={"X-Student-Id": "LEAK-G1", "X-Session-Password": PASSWORD})
    assert len(g2.json()["days"]) == 1
    assert g1.json()["days"] == []
