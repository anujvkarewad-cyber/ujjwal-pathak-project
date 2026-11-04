"""Ranks must update by themselves — no new APK, no cron, no button.

The installed app reads a stored snapshot through /api/proxy and has no way to
ask for a refresh, so the snapshot has to look after its own freshness. These
tests pin that behaviour.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

TODAY = date.today()
RECENT = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def no_live_sheet(monkeypatch):
    """Hermetic: never reach the real Students Sheet from tests."""
    from routers import student_dashboard as sd

    def unavailable():
        raise RuntimeError("students sheet disabled in tests")

    monkeypatch.setattr(sd, "_fetch_tracker_roster_sync", unavailable)


def _seed(client, mentor_headers, hours_by_student):
    """hours_by_student: {id: hours} or {id: {"hours": n, "batch": "..."}}."""
    students = []
    spec = {}
    for sid, value in hours_by_student.items():
        if isinstance(value, dict):
            spec[sid] = (value.get("hours", 0), value.get("batch", "Batch A"))
        else:
            spec[sid] = (value, "Batch A")
        hours = spec[sid][0]
        log = [{"date": RECENT, "topic": "FM", "hours": hours}] if hours else []
        students.append({"studentId": sid, "stats": {"streak": 0}, "studyLog": log,
                         "reports": [], "mentorNotes": [], "feedback": []})
    res = client.post("/api/student-dashboard/import", headers=mentor_headers,
                      json={"announcements": [], "notes": [], "leaderboard": [], "students": students})
    assert res.status_code == 200, res.text

    from db import STUDENT_ACCOUNTS, get_db

    import asyncio

    async def accounts():
        db = get_db()
        for sid, (_, batch) in spec.items():
            await db[STUDENT_ACCOUNTS].update_one(
                {"studentId": sid},
                {"$set": {"studentId": sid, "studentName": f"Student {sid}",
                          "attempt": "Jan 2027", "batch": batch, "group": "Group 1", "password":"synthetic-leaderboard",
                          "joinedOn": (TODAY - timedelta(days=30)).isoformat()}},
                upsert=True)

    asyncio.run(accounts())


def _age_snapshot(seconds):
    """Pretend the stored snapshot was generated `seconds` ago."""
    from db import DASHBOARD_SHARED, get_db

    import asyncio

    async def backdate():
        generated = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        await get_db()[DASHBOARD_SHARED].update_one(
            {"_id": "shared"}, {"$set": {"leaderboardMeta.generatedAt": generated}})

    asyncio.run(backdate())


def _snapshot_generated_at():
    from db import DASHBOARD_SHARED, get_db

    import asyncio

    async def read():
        shared = await get_db()[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        return (shared.get("leaderboardMeta") or {}).get("generatedAt")

    return asyncio.run(read())


def _student_leaderboard(client, student_id=None):
    # Explicit internal snapshot tests: the public student audience route stays closed.
    import asyncio
    from db import get_db
    from routers import student_dashboard as sd
    sid=student_id or "UMP0301"
    assert client.post('/api/student-dashboard/get',json={"action":"getLeaderboard"}).status_code==401
    blocked=client.post('/api/student-dashboard/get',headers={"X-Student-Id":sid,"X-Session-Password":"synthetic-leaderboard"},json={"action":"getLeaderboard"})
    assert blocked.status_code==200  # student reads answer 200 + safe projection
    async def internal():
        db=get_db();shared=await sd._leaderboard_snapshot(db)
        return {"result":await sd._leaderboard_for_student(db,shared.get('leaderboard')or[],student_id)}
    return asyncio.run(internal())


def test_internal_snapshot_rebuilds_when_stale(client, mentor_headers):
    """The core requirement: opening the app is enough to refresh ranks."""
    _seed(client, mentor_headers, {"UMP0301": 5, "UMP0302": 2})
    _age_snapshot(10 * 60)                      # 10 minutes stale

    stale_at = _snapshot_generated_at()
    _student_leaderboard(client, "UMP0301")     # a student just opens the app
    assert _snapshot_generated_at() != stale_at, "read did not refresh the snapshot"


def test_internal_fresh_snapshot_is_not_rebuilt(client, mentor_headers):
    """Freshness must not turn every app open into a rebuild."""
    _seed(client, mentor_headers, {"UMP0301": 5})
    _age_snapshot(10 * 60)
    _student_leaderboard(client, "UMP0301")     # builds a populated snapshot
    assert _snapshot_generated_at()

    _age_snapshot(5)                            # well inside the max age
    fresh_at = _snapshot_generated_at()
    _student_leaderboard(client, "UMP0301")
    assert _snapshot_generated_at() == fresh_at, "a fresh snapshot was rebuilt unnecessarily"


def test_ranks_follow_new_submissions_without_any_manual_step(client, mentor_headers):
    """A submission elsewhere must change this student's rank on their next open."""
    _seed(client, mentor_headers, {"UMP0301": 10, "UMP0302": 1})
    _age_snapshot(10 * 60)
    first = _student_leaderboard(client, "UMP0302")["result"]
    before = next(r for r in first if r["studentId"] == "UMP0302")["rank"]

    # UMP0302 studies hard; nobody touches the dashboard or clicks anything.
    client.post("/api/student-dashboard/write", headers={"X-Student-Id":"UMP0302","X-Session-Password":"synthetic-leaderboard"},
                json={"action": "addStudyLog",
                      "payload": {"studentId": "UMP0302", "date": RECENT,
                                  "hours": 60, "subjects": "FM"}})

    _age_snapshot(10 * 60)
    second = _student_leaderboard(client, "UMP0302")["result"]
    after = next(r for r in second if r["studentId"] == "UMP0302")["rank"]
    assert after < before, f"rank did not improve: {before} -> {after}"


def test_stats_also_refresh_so_the_home_tile_is_never_stale(client, mentor_headers):
    """The rank on the student's home screen comes from getStats."""
    _seed(client, mentor_headers, {"UMP0301": 10, "UMP0302": 1})
    _age_snapshot(10 * 60)

    stats = client.post("/api/student-dashboard/get", headers={"X-Student-Id":"UMP0302","X-Session-Password":"synthetic-leaderboard"},
                        json={"action": "getStats", "payload": {"studentId": "UMP0302"}}).json()["result"]
    assert stats["rank"] >= 1
    assert stats["rank"] != 0, "students must never be shown rank 0"


def test_flat_list_has_no_duplicate_ranks_across_batches(client, mentor_headers):
    """The student app shows ONE cross-batch table with a rank column.

    With per-batch ranks that table would print the same number twice, so the
    student-facing rank must be unique across the whole cohort.
    """
    _seed(client, mentor_headers, {
        "UMP0301": {"hours": 40, "batch": "Batch A"},
        "UMP0302": {"hours": 30, "batch": "Batch A"},
        "UMP0303": {"hours": 20, "batch": "Batch B"},   # best of Batch B
        "UMP0304": {"hours": 10, "batch": "Batch B"},
    })
    _age_snapshot(10 * 60)

    rows = _student_leaderboard(client)["result"]
    assert len(rows) == 4, rows
    ranks = [r["rank"] for r in rows]
    assert ranks == sorted(ranks), "flat list should be in rank order"
    assert len(set(ranks)) == len(ranks), f"duplicate ranks in a flat list: {ranks}"
    assert ranks == [1, 2, 3, 4], f"ranks should be contiguous and unique: {ranks}"

    # The batch rank is still carried for the mentor dashboard's per-batch view,
    # and it legitimately repeats across batches.
    by_id = {r["studentId"]: r for r in rows}
    assert by_id["UMP0303"]["rankInBatch"] == 1     # best of Batch B
    assert by_id["UMP0303"]["rank"] == 3            # third in the cohort
    assert by_id["UMP0301"]["rank"] == by_id["UMP0301"]["rankInBatch"] == 1

    for row in rows:
        assert "email" not in row and "phone" not in row


def test_student_tile_matches_their_row_in_the_list(client, mentor_headers):
    """The rank on the student's home tile must equal the number beside their
    name in the list, or they see two different numbers on one screen."""
    _seed(client, mentor_headers, {
        "UMP0301": {"hours": 40, "batch": "Batch A"},
        "UMP0302": {"hours": 30, "batch": "Batch A"},
        "UMP0303": {"hours": 20, "batch": "Batch B"},
    })
    _age_snapshot(10 * 60)

    identified = _student_leaderboard(client, "UMP0303")["result"]
    anonymous = _student_leaderboard(client)["result"]

    # Same list, same numbers, whichever way the client asks. A student must never
    # see one rank in the table and another number on their tile.
    assert [r["studentId"] for r in identified] == [r["studentId"] for r in anonymous]
    for a, b in zip(identified, anonymous):
        assert a["rank"] == b["rank"], f"{a['studentId']}: {a['rank']} vs {b['rank']}"

    mine = next(r for r in identified if r["studentId"] == "UMP0303")
    stats = client.post("/api/student-dashboard/get", headers={"X-Student-Id":"UMP0303","X-Session-Password":"synthetic-leaderboard"},
                        json={"action": "getStats", "payload": {"studentId": "UMP0303"}}).json()["result"]
    assert stats["rank"] == mine["rank"], (
        f"tile says #{stats['rank']} but the list row says #{mine['rank']}")

    # The mentor-facing per-batch rank is still recorded, just not shown to students.
    assert mine["rankInBatch"] == 1
    assert stats["rankInBatch"] == 1
    assert mine["rank"] == 3          # third across the cohort of three


def test_serial_internal_reads_rebuild_once(client, mentor_headers):
    """The claim must stop every reader rebuilding at once."""
    _seed(client, mentor_headers, {"UMP0301": 5})
    _age_snapshot(10 * 60)

    from routers import student_dashboard as sd
    from db import get_db

    import asyncio

    calls = {"n": 0}
    real = sd._rebuild_leaderboard

    async def counting(db):
        calls["n"] += 1
        return await real(db)

    sd._rebuild_leaderboard = counting
    try:
        _student_leaderboard(client, "UMP0301")
        _student_leaderboard(client, "UMP0301")
        _student_leaderboard(client, "UMP0301")
    finally:
        sd._rebuild_leaderboard = real
    assert calls["n"] == 1, f"expected a single rebuild, saw {calls['n']}"


def test_rebuild_skips_writes_when_nothing_changed(client, mentor_headers):
    """A routine refresh must not rewrite every student document."""
    _seed(client, mentor_headers, {"UMP0301": 5, "UMP0302": 2})

    from routers import student_dashboard as sd
    from db import get_db

    import asyncio

    updates = {"n": 0}

    async def run():
        db = get_db()
        real = db[DASHBOARD_STUDENTS_FOR_TEST].update_one

        async def counting(*args, **kwargs):
            updates["n"] += 1
            return await real(*args, **kwargs)

        db[DASHBOARD_STUDENTS_FOR_TEST].update_one = counting
        try:
            await sd._rebuild_leaderboard(db)   # second pass, nothing changed
        finally:
            db[DASHBOARD_STUDENTS_FOR_TEST].update_one = real

    from db import DASHBOARD_STUDENTS as DASHBOARD_STUDENTS_FOR_TEST
    asyncio.run(run())
    assert updates["n"] == 0, f"expected no writes on an unchanged rebuild, saw {updates['n']}"
