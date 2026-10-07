"""Mentor leaderboard endpoint + student projection (ranking wiring).

The endpoint replaces the legacy Apps Script `leaderboard.list` call, which
returned every student with zero stats and no rank field at all.
"""
from datetime import date, timedelta

import pytest

TODAY = date.today()
RECENT = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def no_live_sheet(monkeypatch):
    """Keep these tests hermetic.

    The roster comes from the real Students Sheet in production, which is exactly
    what we want there. In tests it would pull live student data over the network
    and make assertions depend on production rows, so force the documented Mongo
    fallback instead.
    """
    from routers import student_dashboard as sd

    def unavailable():
        raise RuntimeError("students sheet disabled in tests")

    monkeypatch.setattr(sd, "_fetch_tracker_roster_sync", unavailable)


def _import(client, mentor_headers):
    """Two batches with clearly different effort, plus an inactive student."""
    imported = client.post(
        "/api/student-dashboard/import",
        headers=mentor_headers,
        json={
            "announcements": [],
            "notes": [],
            "leaderboard": [],
            "students": [
                {
                    "studentId": "UMP0101",
                    "stats": {"weeklyHours": 0, "streak": 5},
                    "studyLog": [{"date": RECENT, "topic": "FM", "hours": 10}],
                    "reports": [], "mentorNotes": [], "feedback": [],
                },
                {
                    "studentId": "UMP0102",
                    "stats": {"weeklyHours": 0, "streak": 2},
                    "studyLog": [{"date": RECENT, "topic": "FM", "hours": 4}],
                    "reports": [], "mentorNotes": [], "feedback": [],
                },
                {
                    "studentId": "UMP0103",
                    "stats": {"weeklyHours": 0, "streak": 0},
                    "studyLog": [], "reports": [], "mentorNotes": [], "feedback": [],
                },
            ],
        },
    )
    assert imported.status_code == 200, imported.text


def _seed_accounts(client, mentor_headers):
    """Give the three students real account rows so cohort/batch filters apply."""
    from db import STUDENT_ACCOUNTS, get_db

    async def seed():
        db = get_db()
        rows = [
            {"studentId": "UMP0101", "studentName": "Aarav One", "attempt": "Jan 2027",
             "batch": "Before Result Batch 1", "group": "Group 1",
             "joinedOn": (TODAY - timedelta(days=30)).isoformat()},
            {"studentId": "UMP0102", "studentName": "Bela Two", "attempt": "Jan 2027",
             "batch": "Before Result Batch 1", "group": "Group 2",
             "joinedOn": (TODAY - timedelta(days=30)).isoformat()},
            {"studentId": "UMP0103", "studentName": "Chet Three", "attempt": "Jan 2027",
             "batch": "Before Result Batch 2", "group": "Group 1",
             "joinedOn": (TODAY - timedelta(days=30)).isoformat()},
        ]
        for row in rows:
            await db[STUDENT_ACCOUNTS].update_one({"studentId": row["studentId"]},
                                                  {"$set": row}, upsert=True)

    import asyncio
    asyncio.run(seed())


def _leaderboard(client, mentor_headers, **params):
    res = client.get("/api/student-dashboard/leaderboard", headers=mentor_headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_leaderboard_requires_mentor_auth(client):
    assert client.get("/api/student-dashboard/leaderboard").status_code == 401


def test_leaderboard_returns_real_scores_not_zeros(client, mentor_headers):
    """Regression: the legacy payload was 0 for every student on every metric."""
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch")

    entries = [e for seg in payload["segments"] for e in seg["entries"]]
    assert entries, "expected ranked students"
    assert any(e["score"] > 0 for e in entries)
    assert any(e["hours"] > 0 for e in entries)
    assert any(e["rank"] > 0 for e in entries)


def test_ranks_are_unique_within_each_segment(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch")

    for segment in payload["segments"]:
        ranks = [e["rank"] for e in segment["entries"]]
        assert sorted(ranks) == list(range(1, len(ranks) + 1)), segment["key"]


def test_ranking_is_per_batch_not_global(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch")

    by_key = {seg["key"]: seg["entries"] for seg in payload["segments"]}
    assert "Before Result Batch 1" in by_key
    assert "Before Result Batch 2" in by_key
    # Batch 2 holds only the inactive student, who is still #1 inside that batch.
    assert by_key["Before Result Batch 2"][0]["rank"] == 1
    assert by_key["Before Result Batch 2"][0]["studentId"] == "UMP0103"


def test_higher_effort_ranks_first_within_a_batch(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    entries = _leaderboard(client, mentor_headers, period="weekly",
                           segment="batch")["segments"]
    batch1 = next(seg["entries"] for seg in entries if seg["key"] == "Before Result Batch 1")
    assert batch1[0]["studentId"] == "UMP0101"      # 10 hours
    assert batch1[0]["rank"] == 1
    assert batch1[1]["studentId"] == "UMP0102"      # 4 hours


def test_group_segmentation_is_available(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="group")
    keys = {seg["key"] for seg in payload["segments"]}
    assert {"Group 1", "Group 2"} <= keys


def test_periods_are_distinct(client, mentor_headers):
    """Regression: Overall/Weekly/Monthly used to return identical payloads."""
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    windows = {}
    for period in ("overall", "weekly", "monthly"):
        payload = _leaderboard(client, mentor_headers, period=period)
        windows[period] = (payload["from"], payload["to"], payload["period"])
    assert windows["weekly"][:2] != windows["monthly"][:2] or windows["weekly"][:2] != windows["overall"][:2]
    assert windows["weekly"][2] == "weekly"
    assert windows["monthly"][2] == "monthly"


def test_history_floor_is_reported_and_respected(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="overall")
    assert payload["historyFloor"] == "2026-09-28"
    assert payload["from"] == "2026-09-28"


def test_invalid_period_and_segment_are_rejected(client, mentor_headers):
    assert client.get("/api/student-dashboard/leaderboard",
                      headers=mentor_headers, params={"period": "hourly"}).status_code == 400
    assert client.get("/api/student-dashboard/leaderboard",
                      headers=mentor_headers, params={"segment": "colour"}).status_code == 400


def test_batch_filter_narrows_the_result(client, mentor_headers):
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch",
                           batch="Before Result Batch 1")
    keys = [seg["key"] for seg in payload["segments"]]
    assert keys == ["Before Result Batch 1"]


def test_student_projection_hides_contact_details_and_ranks_within_batch(client, mentor_headers):
    """A student sees their own batch, and never anyone's email or phone."""
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)

    from db import STUDENT_ACCOUNTS, get_db

    async def add_contact_fields():
        await get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": "UMP0101"},
            {"$set": {"email": "aarav@example.com", "phone": "9000000000"}},
        )

    import asyncio
    asyncio.run(add_contact_fields())

    # Rebuild so the stored leaderboard reflects the seeded accounts.
    from routers.student_dashboard import _rebuild_leaderboard

    async def rebuild():
        await _rebuild_leaderboard(get_db())

    asyncio.run(rebuild())

    row = client.post("/api/student-dashboard/get",
                      json={"action": "getLeaderboard", "payload": {"studentId": "UMP0102"}}).json()
    assert row["found"] is True
    assert row["result"], "student should see their own batch"
    for entry in row["result"]:
        assert "email" not in entry
        assert "phone" not in entry
    assert all(e["rank"] >= 1 for e in row["result"])
    assert [e["studentId"] for e in row["result"]] == ["UMP0101", "UMP0102"]


def test_student_write_never_calls_google_sheets(client, mentor_headers, monkeypatch):
    """The store-log write path must stay Mongo-only.

    The rebuild runs inside every student submission. If it fetched Google Sheets,
    a slow or failing Sheet would slow down students submitting their logs.
    """
    from routers import student_dashboard as sd

    called = []

    def spy_roster():
        called.append("roster")
        raise RuntimeError("network disabled")

    def spy_form():
        called.append("form")
        raise RuntimeError("network disabled")

    monkeypatch.setattr(sd, "_fetch_tracker_roster_sync", spy_roster)
    monkeypatch.setattr(sd, "_fetch_tracker_submissions_sync", spy_form)

    res = client.post(
        "/api/student-dashboard/write",
        json={"action": "addStudyLog",
              "payload": {"studentId": "UMP0101", "date": TODAY.isoformat(),
                          "hours": 3, "subjects": "FM"}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert called == [], f"write path touched the network: {called}"


def test_stored_rows_keep_the_frozen_client_contract(client, mentor_headers):
    """The shipped APK/web app reads these exact keys.

    Ranking was fixed server-side precisely so installed clients improve without a
    new APK build. If a key is renamed or dropped, that promise breaks silently.
    """
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)

    from db import DASHBOARD_SHARED, get_db
    from routers.student_dashboard import _rebuild_leaderboard

    import asyncio

    async def rebuild_and_read():
        await _rebuild_leaderboard(get_db())
        shared = await get_db()[DASHBOARD_SHARED].find_one({"_id": "shared"})
        return shared.get("leaderboard") or []

    rows = asyncio.run(rebuild_and_read())
    assert rows, "expected stored leaderboard rows"

    required = {"studentId", "studentName", "rank", "weeklyHours", "totalHours", "streak", "status"}
    for row in rows:
        missing = required - set(row)
        assert not missing, f"{row.get('studentId')} missing {missing}"
        assert isinstance(row["rank"], int) and row["rank"] >= 1
        assert row["status"] in ("Active", "Inactive")
        assert isinstance(row["weeklyHours"], (int, float))
        assert isinstance(row["totalHours"], (int, float))

    # getStats must expose real period ranks, never the old literal 0 / duplicate.
    stats = client.post("/api/student-dashboard/get",
                        json={"action": "getStats", "payload": {"studentId": "UMP0101"}}).json()["result"]
    for key in ("rank", "weeklyRank", "monthlyRank"):
        assert key in stats, f"getStats must keep returning {key}"
        assert isinstance(stats[key], int)
    assert stats["rank"] >= 1


def test_refresh_pushes_corrected_ranks_to_stored_rows(client, mentor_headers):
    """A mentor can force the stored (student-facing) ranks to update immediately."""
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)

    res = client.get("/api/student-dashboard/leaderboard", headers=mentor_headers,
                     params={"period": "weekly", "refresh": 1})
    assert res.status_code == 200, res.text

    from db import DASHBOARD_SHARED, get_db

    import asyncio

    async def read():
        return await get_db()[DASHBOARD_SHARED].find_one({"_id": "shared"})

    shared = asyncio.run(read())
    rows = shared.get("leaderboard") or []
    assert rows, "refresh should populate the stored leaderboard"
    assert any(row.get("score", 0) > 0 for row in rows)


def test_segment_reports_whether_mcq_counted(client, mentor_headers):
    """MCQ is 30 of 100 points but only counts when enough attempts have synced."""
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch")

    assert "weights" in payload
    assert payload["weights"]["mcqMode"] in ("auto", "on", "off")
    for segment in payload["segments"]:
        assert "mcqUsed" in segment
        assert 0.0 <= segment["mcqCoverage"] <= 1.0
        for entry in segment["entries"]:
            assert "mcqUsed" in entry
            assert isinstance(entry["components"], list)

    # These fixtures sync no MCQ attempts, so the component must be excluded and
    # a student who maxes hours and attendance must still reach 100.
    assert all(seg["mcqUsed"] is False for seg in payload["segments"])
    for entry in [e for seg in payload["segments"] for e in seg["entries"]]:
        assert entry["breakdown"]["mcqScore"] == 0.0
