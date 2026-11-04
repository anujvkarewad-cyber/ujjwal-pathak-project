"""Personal day-based targets — synthetic data only, in-memory DB.

Covers the contract the owner asked for:
  * student picks a start day once, and it locks
  * the day number is personal, not calendar based
  * only a mentor can change the locked start day
  * MAX_DAYS is 40
  * students without a start day keep the old calendar behaviour
"""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from auth import hash_password

SID = "LOCAL_TP_1"
PASSWORD = "local-synthetic-password"
STUDENT_HEADERS = {"X-Student-Id": SID, "X-Session-Password": PASSWORD}


@pytest.fixture
def client():
    from server import app
    return TestClient(app)


@pytest.fixture
def student():
    from db import STUDENT_ACCOUNTS, get_db

    async def setup():
        await get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": SID},
            {"$set": {"studentId": SID, "passwordHash": hash_password(PASSWORD),
                      "batch": "LOCAL BATCH", "group": "Group 1",
                      "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )

    asyncio.run(setup())
    return SID


@pytest.fixture
def mentor_token():
    from auth import create_token
    return create_token("mentor@test.local", "mentor")


def test_endpoints_are_registered(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/student-targets/start"]
    assert "get" in paths["/api/student-targets/progress"]
    assert "post" in paths["/api/student-targets/complete-day"]
    assert "patch" in paths["/api/student-targets/{student_id}/start-day"]
    assert "get" in paths["/api/student-targets/all-progress"]


def test_student_endpoints_require_auth(client):
    assert client.post("/api/student-targets/start", json={"startDay": 5}).status_code == 401
    assert client.get("/api/student-targets/progress").status_code == 401
    assert client.get("/api/student-targets/all-progress").status_code == 401


def test_start_day_locks_and_cannot_be_changed_by_student(client, student):
    first = client.post("/api/student-targets/start", json={"startDay": 12}, headers=STUDENT_HEADERS)
    assert first.status_code == 200
    body = first.json()
    assert body["created"] is True
    assert body["progress"]["startDay"] == 12
    assert body["progress"]["currentDay"] == 12
    assert body["progress"]["locked"] is True

    # a second call never overwrites the lock
    second = client.post("/api/student-targets/start", json={"startDay": 30}, headers=STUDENT_HEADERS)
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["progress"]["startDay"] == 12


def test_start_day_out_of_range_is_rejected(client, student):
    assert client.post("/api/student-targets/start", json={"startDay": 0},
                       headers=STUDENT_HEADERS).status_code == 422
    assert client.post("/api/student-targets/start", json={"startDay": 41},
                       headers=STUDENT_HEADERS).status_code == 422


def test_day_does_not_advance_with_the_calendar(client, student):
    """The date never moves a student forward — only completing a day does."""
    client.post("/api/student-targets/start", json={"startDay": 5}, headers=STUDENT_HEADERS)
    from db import STUDENT_TARGET_PROGRESS, get_db

    async def backdate():
        await get_db()[STUDENT_TARGET_PROGRESS].update_one(
            {"studentId": SID},
            {"$set": {"startDate": (date.today() - timedelta(days=10)).isoformat()}},
        )

    asyncio.run(backdate())
    body = client.get("/api/student-targets/progress", headers=STUDENT_HEADERS).json()
    assert body["progress"]["currentDay"] == 5          # still Day 5 after 10 days
    assert body["progress"]["completedCount"] == 0


def test_completing_a_day_unlocks_the_next_one(client, student):
    client.post("/api/student-targets/start", json={"startDay": 12}, headers=STUDENT_HEADERS)
    first = client.get("/api/student-targets/progress", headers=STUDENT_HEADERS).json()["progress"]
    assert first["currentDay"] == 12 and first["nextDay"] == 13

    done = client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    assert done.status_code == 200
    assert done.json()["progress"]["currentDay"] == 13
    assert done.json()["progress"]["nextDay"] == 14

    done2 = client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    assert done2.json()["progress"]["currentDay"] == 14


def test_locked_day_cannot_be_completed_early(client, student):
    client.post("/api/student-targets/start", json={"startDay": 7}, headers=STUDENT_HEADERS)
    res = client.post("/api/student-targets/complete-day", json={"day": 8}, headers=STUDENT_HEADERS)
    assert res.status_code == 400
    assert "locked" in res.json()["detail"].lower()
    # nothing moved
    progress = client.get("/api/student-targets/progress", headers=STUDENT_HEADERS).json()["progress"]
    assert progress["currentDay"] == 7
    assert progress["completedDays"] == []


def test_completed_day_cannot_be_repeated(client, student):
    client.post("/api/student-targets/start", json={"startDay": 3}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    again = client.post("/api/student-targets/complete-day", json={"day": 3}, headers=STUDENT_HEADERS)
    assert again.status_code == 400
    assert "already complete" in again.json()["detail"].lower()


def test_day_ladder_marks_complete_open_and_locked(client, student):
    client.post("/api/student-targets/start", json={"startDay": 9}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    body = client.get("/api/student-targets/day-ladder", headers=STUDENT_HEADERS).json()
    assert body["currentDay"] == 10
    states = {row["day"]: row["state"] for row in body["days"]}
    assert states[9] == "complete"
    assert states[10] == "open"
    assert states[11] == "locked"
    assert body["days"][0]["day"] == 1 < body["days"][-1]["day"] == 40
    assert states[8] == "locked" and body["days"][0]["beforeStart"] is True


def test_mentor_change_resets_the_ladder_to_the_new_day(client, student, mentor_token):
    client.post("/api/student-targets/start", json={"startDay": 4}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    res = client.patch(f"/api/student-targets/{SID}/start-day",
                       json={"startDay": 20, "note": "re-joined late"},
                       headers={"Authorization": f"Bearer {mentor_token}"})
    assert res.status_code == 200
    assert res.json()["progress"]["currentDay"] == 20


def test_ladder_stops_at_max_days(client, student):
    client.post("/api/student-targets/start", json={"startDay": 39}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)   # 39 done
    res = client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)  # 40 done
    progress = res.json()["progress"]
    assert progress["currentDay"] == 40
    assert progress["finished"] is True
    assert progress["nextDay"] is None
    assert progress["maxDays"] == 40


def test_complete_day_advances_and_rejects_future_day(client, student):
    client.post("/api/student-targets/start", json={"startDay": 3}, headers=STUDENT_HEADERS)
    ok = client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    assert ok.status_code == 200
    assert ok.json()["day"] == 3
    assert 3 in ok.json()["progress"]["completedDays"]

    future = client.post("/api/student-targets/complete-day", json={"day": 9},
                         headers=STUDENT_HEADERS)
    assert future.status_code == 400


def test_mentor_can_change_locked_start_day(client, student, mentor_token):
    client.post("/api/student-targets/start", json={"startDay": 7}, headers=STUDENT_HEADERS)
    res = client.patch(f"/api/student-targets/{SID}/start-day",
                       json={"startDay": 25, "note": "joined late"},
                       headers={"Authorization": f"Bearer {mentor_token}"})
    assert res.status_code == 200
    assert res.json()["progress"]["startDay"] == 25
    assert res.json()["progress"]["currentDay"] == 25

    # students still cannot change it themselves
    again = client.post("/api/student-targets/start", json={"startDay": 2}, headers=STUDENT_HEADERS)
    assert again.json()["progress"]["startDay"] == 25


def test_mentor_change_requires_mentor_token(client, student):
    assert client.patch(f"/api/student-targets/{SID}/start-day",
                        json={"startDay": 4}).status_code == 401


def test_all_progress_lists_started_and_not_started(client, student, mentor_token):
    client.post("/api/student-targets/start", json={"startDay": 9}, headers=STUDENT_HEADERS)
    from db import STUDENT_ACCOUNTS, get_db

    async def add_other():
        await get_db()[STUDENT_ACCOUNTS].insert_one(
            {"studentId": "LOCAL_TP_2", "name": "Other", "batch": "LOCAL BATCH"}
        )

    asyncio.run(add_other())
    body = client.get("/api/student-targets/all-progress",
                      headers={"Authorization": f"Bearer {mentor_token}"}).json()
    assert body["maxDays"] == 40
    assert body["started"] == 1
    assert body["notStarted"] == 1
    started = next(r for r in body["rows"] if r["studentId"] == SID)
    assert started["currentDay"] == 9
    assert started["started"] is True


def test_student_cannot_read_another_students_progress(client, student):
    res = client.get("/api/student-targets/progress?studentId=LOCAL_OTHER",
                     headers=STUDENT_HEADERS)
    assert res.status_code == 403


def test_daily_target_uses_personal_day_when_plan_day_exists(client, student):
    """The app reads the plan day matching the personal day, not the calendar date."""
    from db import get_db
    from routers.daily_targets import TARGETS

    client.post("/api/student-targets/start", json={"startDay": 9}, headers=STUDENT_HEADERS)

    async def seed():
        db = get_db()
        await db[TARGETS].insert_many([
            {"id": "dt-day9", "startDate": "2000-01-01", "endDate": "2000-01-02",
             "attempt": "All", "group": "All", "batch": "All", "subject": "Taxation",
             "planDay": 9, "active": True, "createdAt": "2000-01-01",
             "tasks": [{"id": "t9", "label": "Day nine chapter", "detail": "", "kind": "chapter"}]},
            {"id": "dt-day10", "startDate": "2000-01-01", "endDate": "2000-01-02",
             "attempt": "All", "group": "All", "batch": "All", "subject": "Taxation",
             "planDay": 10, "active": True, "createdAt": "2000-01-01",
             "tasks": [{"id": "t10", "label": "Day ten chapter", "detail": "", "kind": "chapter"}]},
        ])

    asyncio.run(seed())
    res = client.get(f"/api/ai/daily-target?studentId={SID}", headers=STUDENT_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["personalDay"] == 9
    labels = [t["label"] for t in body["tasks"]]
    assert "Day nine chapter" in labels
    assert "Day ten chapter" not in labels


def test_daily_target_falls_back_when_no_start_day(client, student):
    """A student who has not picked a day is untouched by the personal-day path."""
    from db import get_db
    from routers.daily_targets import TARGETS
    from routers.daily_targets import _today

    async def seed():
        today = _today().isoformat()
        await get_db()[TARGETS].insert_one(
            {"id": "dt-today", "startDate": today, "endDate": today,
             "attempt": "All", "group": "All", "batch": "All", "subject": "Taxation",
             "active": True, "createdAt": today,
             "tasks": [{"id": "t1", "label": "Calendar target", "detail": "", "kind": "chapter"}]}
        )

    asyncio.run(seed())
    res = client.get(f"/api/ai/daily-target?studentId={SID}", headers=STUDENT_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["personalDay"] is None
    assert "Calendar target" in [t["label"] for t in body["tasks"]]


def test_max_days_is_forty_everywhere():
    from routers import student_target_progress, target_plans
    assert student_target_progress.MAX_DAYS == 40
    assert target_plans.MAX_DAYS == 40

def _seed_targets(days):
    """Publish synthetic targets for the given plan days."""
    from db import get_db
    from routers.daily_targets import TARGETS

    async def run():
        for day in days:
            await get_db()[TARGETS].update_one(
                {"id": f"LOCAL-TP-DAY-{day}"},
                {"$set": {
                    "id": f"LOCAL-TP-DAY-{day}", "planDay": day, "active": True,
                    "subject": "Taxation", "batch": "LOCAL BATCH", "group": "Group 1",
                    "tasks": [{"id": f"t{day}", "label": f"Day {day} chapter",
                               "detail": f"Synthetic task for day {day}", "kind": "chapter"}],
                }},
                upsert=True,
            )

    asyncio.run(run())


def test_previous_days_keep_their_targets_and_dates(client, student):
    _seed_targets([10, 11, 12, 13])
    client.post("/api/student-targets/start", json={"startDay": 10}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)  # 10
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)  # 11

    body = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    by_day = {row["day"]: row for row in body["days"]}
    assert body["currentDay"] == 12
    # past days stay readable
    assert by_day[10]["state"] == "complete"
    assert by_day[10]["targets"][0]["label"] == "Day 10 chapter"
    assert by_day[11]["state"] == "complete"
    assert by_day[11]["targets"][0]["detail"].startswith("Taxation.")
    assert by_day[10]["completedOn"]
    # today is open with its own targets
    assert by_day[12]["state"] == "open"
    assert by_day[12]["targets"][0]["label"] == "Day 12 chapter"
    # tomorrow is locked and reveals nothing
    assert by_day[13]["state"] == "locked"
    assert by_day[13]["targets"] == []
    assert by_day[13]["targetCount"] == 0


def test_every_day_carries_a_planned_date(client, student):
    from routers.student_target_progress import _today

    today = _today()          # IST, same clock the endpoint uses
    client.post("/api/student-targets/start", json={"startDay": 5}, headers=STUDENT_HEADERS)
    body = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    by_day = {row["day"]: row for row in body["days"]}
    assert by_day[5]["plannedDate"] == today.isoformat()
    assert by_day[6]["plannedDate"] == (today + timedelta(days=1)).isoformat()
    assert by_day[9]["plannedDate"] == (today + timedelta(days=4)).isoformat()


def test_timeline_can_start_from_an_older_day(client, student):
    client.post("/api/student-targets/start", json={"startDay": 20}, headers=STUDENT_HEADERS)
    # the ladder always starts at Day 1, whatever the student picked
    body = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    assert body["days"][0]["day"] == 1
    by_day = {row["day"]: row for row in body["days"]}
    assert by_day[1]["beforeStart"] is True
    assert by_day[1]["targets"] == []          # nothing existed before the journey began
    assert by_day[19]["beforeStart"] is True
    assert by_day[20]["beforeStart"] is False
    assert by_day[20]["state"] == "open"
    assert body["days"][-1]["day"] == 40


def test_ladder_exposes_dates_for_the_scroll_strip(client, student):
    from routers.student_target_progress import _today

    client.post("/api/student-targets/start", json={"startDay": 8}, headers=STUDENT_HEADERS)
    body = client.get("/api/student-targets/day-ladder", headers=STUDENT_HEADERS).json()
    assert body["days"][7] == {
        "day": 8,
        "plannedDate": _today().isoformat(),
        "beforeStart": False,
        "state": "open",
    }
    assert body["days"][0]["day"] == 1
    assert body["days"][0]["beforeStart"] is True
    assert len(body["days"]) == 40             # the strip always runs Day 1..40
    assert body["days"][0]["day"] == 1
    assert body["days"][0]["beforeStart"] is True
    assert body["days"][7]["day"] == 8 and body["days"][7]["state"] == "open"
    assert body["days"][-1]["day"] == 40


def test_mentor_sees_locked_days_but_the_student_does_not(client, student, mentor_token):
    _seed_targets([9, 10, 11])
    client.post("/api/student-targets/start", json={"startDay": 9}, headers=STUDENT_HEADERS)
    res = client.get(f"/api/student-targets/{SID}/day-timeline",
                     headers={"Authorization": f"Bearer {mentor_token}"})
    assert res.status_code == 200
    by_day = {row["day"]: row for row in res.json()["days"]}
    assert by_day[9]["state"] == "open"
    assert by_day[10]["state"] == "locked"
    assert by_day[10]["targets"][0]["label"] == "Day 10 chapter"     # mentor sees it
    assert by_day[11]["plannedDate"]                                  # dates always present

    student_view = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    assert {row["day"]: row for row in student_view["days"]}[10]["targets"] == []


def test_mentor_timeline_needs_a_started_student(client, student, mentor_token):
    from db import STUDENT_TARGET_PROGRESS, get_db

    asyncio.run(get_db()[STUDENT_TARGET_PROGRESS].delete_many({"studentId": SID}))
    res = client.get(f"/api/student-targets/{SID}/day-timeline",
                     headers={"Authorization": f"Bearer {mentor_token}"})
    assert res.status_code == 404


def test_plan_list_reports_whether_photo_reading_is_available(client, mentor_token, monkeypatch):
    """The page must hide the photo button instead of showing an error banner."""
    headers = {"Authorization": f"Bearer {mentor_token}"}
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert client.get("/api/target-plans", headers=headers).json()["capabilities"] == {"aiPhotoReading": False}

    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key-never-used")
    assert client.get("/api/target-plans", headers=headers).json()["capabilities"] == {"aiPhotoReading": True}


# ── the checklist inside a day ─────────────────────────────────────────────────
def test_ticking_a_task_is_saved_and_survives_a_reload(client, student):
    _seed_targets([21])
    client.post("/api/student-targets/start", json={"startDay": 21}, headers=STUDENT_HEADERS)
    res = client.post("/api/student-targets/toggle-task",
                      json={"day": 21, "taskId": "t21", "done": True}, headers=STUDENT_HEADERS)
    assert res.status_code == 200
    assert res.json()["dayTasks"] == ["t21"]

    timeline = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    day = {row["day"]: row for row in timeline["days"]}[21]
    assert day["targets"][0]["done"] is True
    assert day["doneCount"] == 1

    off = client.post("/api/student-targets/toggle-task",
                      json={"day": 21, "taskId": "t21", "done": False}, headers=STUDENT_HEADERS)
    assert off.json()["dayTasks"] == []
    timeline = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    assert {row["day"]: row for row in timeline["days"]}[21]["targets"][0]["done"] is False


def test_ticking_does_not_advance_the_day(client, student):
    _seed_targets([22])
    client.post("/api/student-targets/start", json={"startDay": 22}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/toggle-task",
                json={"day": 22, "taskId": "t22", "done": True}, headers=STUDENT_HEADERS)
    progress = client.get("/api/student-targets/progress", headers=STUDENT_HEADERS).json()["progress"]
    assert progress["currentDay"] == 22          # only /complete-day moves the ladder
    assert progress["completedDays"] == []


def test_locked_day_cannot_be_ticked(client, student):
    client.post("/api/student-targets/start", json={"startDay": 23}, headers=STUDENT_HEADERS)
    res = client.post("/api/student-targets/toggle-task",
                      json={"day": 24, "taskId": "t24", "done": True}, headers=STUDENT_HEADERS)
    assert res.status_code == 400
    assert "locked" in res.json()["detail"].lower()


def test_day_before_the_start_day_cannot_be_ticked(client, student):
    client.post("/api/student-targets/start", json={"startDay": 25}, headers=STUDENT_HEADERS)
    res = client.post("/api/student-targets/toggle-task",
                      json={"day": 3, "taskId": "x", "done": True}, headers=STUDENT_HEADERS)
    assert res.status_code == 400


def test_completed_days_keep_their_ticks_visible(client, student):
    _seed_targets([26])
    client.post("/api/student-targets/start", json={"startDay": 26}, headers=STUDENT_HEADERS)
    client.post("/api/student-targets/toggle-task", json={"day": 26, "taskId": "t26", "done": True},
                headers=STUDENT_HEADERS)
    client.post("/api/student-targets/complete-day", json={}, headers=STUDENT_HEADERS)
    timeline = client.get("/api/student-targets/day-timeline", headers=STUDENT_HEADERS).json()
    day = {row["day"]: row for row in timeline["days"]}[26]
    assert day["state"] == "complete"
    assert day["targets"][0]["done"] is True
