"""One-click AI reminder backfill (owner ask, 15-Oct-2026).

After the Groq key/model outage a week of already-published targets showed
"AI reminder required" with one button per target. The fix is a single
maintenance call that fills the missing reminders, and it must:

  * touch only targets inside the date window (a passed date is not worth an AI call);
  * never re-generate a reminder that is already Groq-sourced;
  * report per-row failures instead of 503-ing the whole batch, so the button
    is honest about what it managed to fix.
"""
import asyncio
from datetime import timedelta

import pytest

from db import STUDENT_ACCOUNTS, get_db
from routers import daily_targets as dt

SID = "BFTESTR1"
SUBJECT = "Backfill subject"


def _run(coro):
    return asyncio.run(coro)


def _publish(client, mentor_headers, start, end=None):
    body = {
        "startDate": start.isoformat(), "attempt": "Jan 2027", "group": "1",
        "batch": "BFTESTB1", "subject": SUBJECT,
        "tasks": [{"label": "Revise Auditor's Duties", "detail": "Ch 1"}],
    }
    if end:
        body["endDate"] = end.isoformat()
    res = client.post("/api/targets", headers=mentor_headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()["target"]["id"]


@pytest.fixture()
def board(monkeypatch):
    calls = []

    async def fake_reminder(subject, tasks):
        calls.append(subject)
        return "Use the timer for the mentor target, then answer the receipt questions.", "groq"

    monkeypatch.setattr(dt, "_groq_reminder", fake_reminder)

    async def seed():
        await get_db()[STUDENT_ACCOUNTS].insert_one({
            "studentId": SID, "studentName": "Backfill Test", "group": "1",
            "attempt": "Jan 2027", "batch": "BFTESTB1",
        })
    _run(seed())
    yield calls

    async def cleanup():
        db = get_db()
        await db[dt.TARGETS].delete_many({"subject": SUBJECT})
        await db[STUDENT_ACCOUNTS].delete_many({"studentId": SID})
    _run(cleanup())


def _rows():
    async def load():
        return await get_db()[dt.TARGETS].find({"subject": SUBJECT}, {"_id": 0}).to_list(50)
    return _run(load())


def _wipe_reminders():
    """Simulate the outage state: published rows without an AI reminder."""
    _run(get_db()[dt.TARGETS].update_many({"subject": SUBJECT},
                                          {"$set": {"revisionReminder": "", "reminderSource": "plain"}}))


def test_backfill_fills_the_current_target_only(client, mentor_headers, board):
    today = dt._today()
    current_id = _publish(client, mentor_headers, today)
    past_id = _publish(client, mentor_headers, today - timedelta(days=20))
    _wipe_reminders()
    board.clear()

    res = client.post("/api/targets/reminders/backfill", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["generated"] == 1, body
    assert body["considered"] == 1, "the 20-day-old target is outside the window and must not be touched"
    assert board == [SUBJECT], "exactly one AI call for exactly the pending row"

    rows = {row["id"]: row for row in _rows()}
    assert rows[current_id]["reminderSource"] == "groq"
    assert "timer" in rows[current_id]["revisionReminder"]
    assert rows[past_id]["reminderSource"] == "plain"
    assert not rows[past_id].get("revisionReminder")


def test_backfill_is_idempotent_and_reports_a_dead_ai(client, mentor_headers, board, monkeypatch):
    _publish(client, mentor_headers, dt._today())
    _wipe_reminders()

    first = client.post("/api/targets/reminders/backfill", headers=mentor_headers).json()
    assert first["generated"] == 1
    second = client.post("/api/targets/reminders/backfill", headers=mentor_headers).json()
    assert second["generated"] == 0 and second["considered"] == 0, second

    # now make Groq fail: the batch must answer 200 with the reason, not 503
    from fastapi import HTTPException

    async def broken(subject, tasks):
        raise HTTPException(status_code=503, detail="AI reminder generation failed after two attempts.")

    monkeypatch.setattr(dt, "_groq_reminder", broken)
    _wipe_reminders()
    third = client.post("/api/targets/reminders/backfill", headers=mentor_headers)
    assert third.status_code == 200, third.text
    out = third.json()
    assert out["generated"] == 0 and out["stillMissing"] == 1
    assert "two attempts" in out["failed"][0]["reason"], out

    # the row is untouched - still publishable, still shows its tasks
    row = _rows()[0]
    assert row["reminderSource"] == "plain" and row["tasks"]
