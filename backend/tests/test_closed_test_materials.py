"""Closed mentor-test windows, audience filtering, and Materials paper pairs."""
import asyncio
from datetime import datetime, timedelta, timezone

from db import ANALYTICS_TEST_HISTORY, MENTOR_TESTS, STUDENT_ACCESS_EVENTS, get_db

STUDENT_ID = "UMP0674"
PASSWORD = "closed-window-fixture"
BATCH = "Before Result Batch 1"
GROUP = "Group 1"
CHAPTER = "Ch 13 — Amalgamation of Companies"


def _run(coro):
    return asyncio.run(coro)


def _iso(stamp):
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _test(test_id, title, now, *, start_delta=-2, end_delta=-1, batch=BATCH, group=GROUP, **fields):
    return {
        "testId": test_id,
        "title": title,
        "kind": "paper-test",
        "subject": "Accounts",
        "chapters": [CHAPTER],
        "batch": batch,
        "group": group,
        "published": True,
        "window_start": _iso(now + timedelta(hours=start_delta)),
        "window_end": _iso(now + timedelta(hours=end_delta)),
        "createdAt": int(now.timestamp() * 1000),
        **fields,
    }


def test_closed_tests_stay_listed_but_only_their_paper_pair_enters_materials(client, mentor_headers):
    imported = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={"students": [{
            "studentId": STUDENT_ID,
            "password": PASSWORD,
            "studentName": "Closed Window Fixture",
            "attempt": "Jan 2027",
            "batch": BATCH,
            "group": GROUP,
        }]},
    )
    assert imported.status_code == 200, imported.text
    now = datetime.now(timezone.utc)

    async def seed():
        db = get_db()
        await db[MENTOR_TESTS].insert_many([
            _test(
                "CLOSED-SUBMITTED", "AS 13 submitted", now,
                paper_url="https://drive.google.com/file/d/qp-submitted/view",
                answer_sheet_text="Answer key: debit the asset account.",
            ),
            _test(
                "CLOSED-NOT-SUBMITTED", "AS 13 not submitted", now,
                paper_url="https://drive.google.com/file/d/qp-not-submitted/view",
                answer_sheet_url="https://drive.google.com/file/d/as-not-submitted/view",
            ),
            _test(
                "OPEN-NOT-SUBMITTED", "Open test", now,
                start_delta=-1, end_delta=1,
                paper_url="https://drive.google.com/file/d/qp-open/view",
                answer_sheet_url="https://drive.google.com/file/d/as-open/view",
            ),
            _test(
                "UPCOMING-NOT-SUBMITTED", "Upcoming test", now,
                start_delta=1, end_delta=2,
                paper_url="https://drive.google.com/file/d/qp-upcoming/view",
                answer_sheet_url="https://drive.google.com/file/d/as-upcoming/view",
            ),
            _test(
                "CLOSED-WRONG-BATCH", "Another batch", now,
                batch="After Result Batch 2",
                paper_url="https://drive.google.com/file/d/qp-other-batch/view",
                answer_sheet_url="https://drive.google.com/file/d/as-other-batch/view",
            ),
            _test(
                "CLOSED-WRONG-GROUP", "Another group", now,
                group="Group 2",
                paper_url="https://drive.google.com/file/d/qp-other-group/view",
                answer_sheet_url="https://drive.google.com/file/d/as-other-group/view",
            ),
        ])
        await db[ANALYTICS_TEST_HISTORY].insert_one({
            "id": f"mentor-test:CLOSED-SUBMITTED:{STUDENT_ID}",
            "studentId": STUDENT_ID,
            "testId": "CLOSED-SUBMITTED",
            "kind": "paper-test",
            "at": _iso(now),
            "at_ms": int(now.timestamp() * 1000),
            "score": 72,
            "total": 100,
        })

    _run(seed())
    student_headers = {"X-Student-Id": STUDENT_ID, "X-Session-Password": PASSWORD}

    listed = client.post(
        "/api/student-tests/list",
        json={"studentId": STUDENT_ID, "password": PASSWORD},
    )
    assert listed.status_code == 200, listed.text
    by_id = {item["testId"]: item for item in listed.json()["tests"]}
    assert by_id["CLOSED-SUBMITTED"]["status"] == "closed"
    assert by_id["CLOSED-SUBMITTED"]["attempted"] is True
    assert by_id["CLOSED-NOT-SUBMITTED"]["status"] == "closed"
    assert by_id["CLOSED-NOT-SUBMITTED"]["attempted"] is False
    assert by_id["OPEN-NOT-SUBMITTED"]["status"] == "open"
    assert by_id["UPCOMING-NOT-SUBMITTED"]["status"] == "upcoming"
    assert "CLOSED-WRONG-BATCH" not in by_id
    assert "CLOSED-WRONG-GROUP" not in by_id

    materials = client.post(
        "/api/student-dashboard/get",
        headers=student_headers,
        json={"action": "notes.listForStudent", "payload": {"studentId": STUDENT_ID}},
    )
    assert materials.status_code == 200, materials.text
    assert materials.json()["found"] is True
    rows = materials.json()["result"]
    assert {row["testId"] for row in rows} == {"CLOSED-SUBMITTED", "CLOSED-NOT-SUBMITTED"}
    for test_id in ("CLOSED-SUBMITTED", "CLOSED-NOT-SUBMITTED"):
        pair = [row for row in rows if row["testId"] == test_id]
        assert {row["materialType"] for row in pair} == {"question-paper", "answer-paper"}
        assert {row["chapter"] for row in pair} == {CHAPTER}
        assert {row["category"] for row in pair} == {"Mentor Tests"}
    answer_key = next(row for row in rows if row["testId"] == "CLOSED-SUBMITTED" and row["materialType"] == "answer-paper")
    assert answer_key["textContent"] == "Answer key: debit the asset account."


def test_materials_respects_the_student_makeup_shift_before_releasing_papers(client, mentor_headers):
    imported = client.post(
        "/api/student-auth/import",
        headers=mentor_headers,
        json={"students": [{
            "studentId": STUDENT_ID,
            "password": PASSWORD,
            "studentName": "Closed Window Fixture",
            "attempt": "Jan 2027",
            "batch": BATCH,
            "group": GROUP,
        }]},
    )
    assert imported.status_code == 200, imported.text
    now = datetime.now(timezone.utc)

    async def seed():
        db = get_db()
        await db[MENTOR_TESTS].insert_one(_test(
            "MAKEUP-MATERIAL-WINDOW", "Makeup-window test", now,
            start_delta=-4, end_delta=-0.1,
            paper_url="https://drive.google.com/file/d/qp-makeup/view",
            answer_sheet_url="https://drive.google.com/file/d/as-makeup/view",
        ))
        await db[STUDENT_ACCESS_EVENTS].insert_many([
            {"studentId": STUDENT_ID, "enabled": False, "at": (now - timedelta(hours=3)).isoformat()},
            {"studentId": STUDENT_ID, "enabled": True, "at": (now - timedelta(hours=2)).isoformat()},
        ])

    _run(seed())
    listed = client.post(
        "/api/student-tests/list",
        json={"studentId": STUDENT_ID, "password": PASSWORD},
    )
    assert listed.status_code == 200, listed.text
    test = next(row for row in listed.json()["tests"] if row["testId"] == "MAKEUP-MATERIAL-WINDOW")
    assert test["makeup"] is True
    assert test["status"] == "open"

    materials = client.post(
        "/api/student-dashboard/get",
        headers={"X-Student-Id": STUDENT_ID, "X-Session-Password": PASSWORD},
        json={"action": "notes.listForStudent", "payload": {"studentId": STUDENT_ID}},
    )
    assert materials.status_code == 200, materials.text
    assert not [row for row in materials.json().get("result", []) if row.get("testId") == "MAKEUP-MATERIAL-WINDOW"]
