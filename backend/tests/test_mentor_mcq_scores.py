"""MCQ Scores mentor endpoint (``GET /api/mentor/mcq-scores``).

The page existed in an older deployed build but the endpoint never did, so the
dashboard showed ``Not Found: /api/mentor/mcq-scores``. These tests pin the
aggregate contract: per-student attempts/marks/average/best/lastAttempt plus
cohort stats, honouring the range window, kind filter and search text.
"""
import asyncio
import time

from db import STUDENT_ACCOUNTS, STUDENT_MCQ_ATTEMPTS, get_db

NOW_MS = int(time.time() * 1000)
DAY_MS = 86_400_000


def _run(coro):
    return asyncio.run(coro)


def _account(sid, name, batch="Before Result Batch 1"):
    return {"studentId": sid, "name": name, "batch": batch, "group": "Group I"}


def _attempt(sid, attempt_id, score, total, age_days=1, kind="daily"):
    return {
        "studentId": sid,
        "attemptId": attempt_id,
        "kind": kind,
        "score": score,
        "total": total,
        "completedAt": NOW_MS - age_days * DAY_MS,
        "questionIds": [f"q{i}" for i in range(total)],
        "answers": {},
    }


async def _seed():
    db = get_db()
    await db[STUDENT_ACCOUNTS].insert_many(
        [
            _account("UMP0001", "Tanu Shree"),
            _account("UMP0002", "Ravi Kumar"),
            _account("UMP0003", "Old Attempt"),
        ]
    )
    await db[STUDENT_MCQ_ATTEMPTS].insert_many(
        [
            # UMP0001: two recent daily attempts (2/2 = 100%, 1/2 = 50%)
            _attempt("UMP0001", "d1", 2, 2, age_days=1),
            _attempt("UMP0001", "d2", 1, 2, age_days=2),
            # UMP0002: one mentor-test attempt (3/4 = 75%)
            _attempt("UMP0002", "m1", 3, 4, age_days=3, kind="mentor-test"),
            # UMP0003: an attempt outside the 7-day window (60 days old)
            _attempt("UMP0003", "old1", 4, 4, age_days=60),
        ]
    )


def test_mcq_scores_aggregates_and_filters(client, mentor_headers):
    _run(_seed())

    res = client.get("/api/mentor/mcq-scores?range=7", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    ids = [row["studentId"] for row in body["students"]]
    # 60-day-old attempt must be excluded by the 7-day window
    assert "UMP0003" not in ids
    assert set(ids) == {"UMP0001", "UMP0002"}

    by_id = {row["studentId"]: row for row in body["students"]}
    tanu = by_id["UMP0001"]
    assert tanu["name"] == "Tanu Shree"
    assert tanu["attempts"] == 2
    assert tanu["marks"] == 3            # 2 + 1 correct
    assert tanu["questionsSolved"] == 4  # 2 + 2 faced
    assert tanu["average"] == 75.0       # (100 + 50) / 2
    assert tanu["best"] == 100.0
    assert tanu["lastAttempt"]           # ISO timestamp present

    ravi = by_id["UMP0002"]
    assert ravi["attempts"] == 1
    assert ravi["average"] == 75.0
    assert ravi["best"] == 75.0

    stats = body["stats"]
    assert stats["students"] == 2
    assert stats["attempts"] == 3
    assert stats["questionsSolved"] == 8
    assert stats["cohortAverage"] == 75.0  # (100+50+75)/3 per-attempt


def test_mcq_scores_range_all_includes_old(client, mentor_headers):
    _run(_seed())
    res = client.get("/api/mentor/mcq-scores?range=all", headers=mentor_headers)
    assert res.status_code == 200, res.text
    ids = {row["studentId"] for row in res.json()["students"]}
    assert ids == {"UMP0001", "UMP0002", "UMP0003"}


def test_mcq_scores_kind_filter(client, mentor_headers):
    _run(_seed())
    res = client.get(
        "/api/mentor/mcq-scores?range=all&kind=mentor-test", headers=mentor_headers
    )
    assert res.status_code == 200, res.text
    ids = {row["studentId"] for row in res.json()["students"]}
    assert ids == {"UMP0002"}


def test_mcq_scores_search(client, mentor_headers):
    _run(_seed())
    res = client.get("/api/mentor/mcq-scores?range=all&q=tanu", headers=mentor_headers)
    assert res.status_code == 200, res.text
    ids = {row["studentId"] for row in res.json()["students"]}
    assert ids == {"UMP0001"}

    by_id = client.get(
        "/api/mentor/mcq-scores?range=all&q=UMP0002", headers=mentor_headers
    ).json()
    assert {r["studentId"] for r in by_id["students"]} == {"UMP0002"}


def test_mcq_scores_requires_mentor(client):
    res = client.get("/api/mentor/mcq-scores")
    assert res.status_code == 401


def test_mcq_scores_empty_is_safe(client, mentor_headers):
    res = client.get("/api/mentor/mcq-scores?range=30", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["students"] == []
    assert body["stats"] == {
        "students": 0,
        "attempts": 0,
        "questionsSolved": 0,
        "cohortAverage": None,
    }
