"""Mentor leaderboard endpoint + student projection (ranking wiring).

The endpoint replaces the legacy Apps Script `leaderboard.list` call, which
returned every student with zero stats and no rank field at all.
"""
from datetime import date, timedelta

import pytest

from week_window import week_start

TODAY = date.today()
# Every day of the week the board is currently ranking, oldest first. Pinning the seed
# to "yesterday" made these tests pass six days a week and fail on the first day of a
# new week, when yesterday belongs to the week that already closed.
WEEK_DAYS = [
    (week_start(TODAY) + timedelta(days=i)).isoformat()
    for i in range((TODAY - week_start(TODAY)).days + 1)
]
RECENT = WEEK_DAYS[-1]


def log_days(hours: float, topic: str = "FM") -> list:
    """One entry per day of the running week, so the window always has data."""
    return [{"date": d, "topic": topic, "hours": hours} for d in WEEK_DAYS]


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
                    "studyLog": log_days(10),
                    "reports": [], "mentorNotes": [], "feedback": [],
                },
                {
                    "studentId": "UMP0102",
                    "stats": {"weeklyHours": 0, "streak": 2},
                    "studyLog": log_days(4),
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
            row["password"]="synthetic-leaderboard"
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


def test_student_projection_hides_contact_details(client, mentor_headers):
    """Students get the cohort list ranked cohort-wide, and never contact details.

    Rank must mean one thing: the app's table has a rank column and no batch
    column, and older clients send no studentId, so a batch-restricted number
    would show different students different values for the same rank.
    """
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

    denied = client.post('/api/student-dashboard/get',json={"action":"getLeaderboard"})
    assert denied.status_code==401
    # A student read is answered with 200 + the safe projection (FIX 3: a
    # business rule never answers 5xx). The projection must still hide contact
    # details - that is asserted on the public response below.
    blocked = client.post('/api/student-dashboard/get',headers={"X-Student-Id":"UMP0102","X-Session-Password":"synthetic-leaderboard"},json={"action":"getLeaderboard"})
    assert blocked.status_code==200
    assert blocked.json()["found"] is True
    for entry in blocked.json()["result"]:
        assert "email" not in entry and "phone" not in entry
    # Internal projection contract only, not permission to expose a global list.
    from routers.student_dashboard import _leaderboard_for_student
    async def projection():
        from db import DASHBOARD_SHARED
        db=get_db(); shared=await db[DASHBOARD_SHARED].find_one({"_id":"shared"})
        return await _leaderboard_for_student(db,shared['leaderboard'],'UMP0102')
    row={"found":True,"result":asyncio.run(projection())}
    assert row["found"] is True
    assert row["result"], "student should see the ranked list"
    for entry in row["result"]:
        assert "email" not in entry
        assert "phone" not in entry
    ranks = [e["rank"] for e in row["result"]]
    assert ranks == list(range(1, len(ranks) + 1)), f"ranks must be unique and contiguous: {ranks}"
    # Across batches too: UMP0103 sits in a different batch but still appears.
    assert {e["studentId"] for e in row["result"]} == {"UMP0101", "UMP0102", "UMP0103"}


def test_student_write_never_calls_google_sheets(client, mentor_headers, monkeypatch):
    """The store-log write path must stay Mongo-only.

    The rebuild runs inside every student submission. If it fetched Google Sheets,
    a slow or failing Sheet would slow down students submitting their logs.
    """
    from routers import student_dashboard as sd

    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
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
        "/api/student-dashboard/write", headers={"X-Student-Id":"UMP0101","X-Session-Password":"synthetic-leaderboard"},
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
    stats = client.post("/api/student-dashboard/get", headers={"X-Student-Id":"UMP0101","X-Session-Password":"synthetic-leaderboard"},
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


def test_individual_mcq_policy_is_reported_and_counts_below_sixty_percent(client, mentor_headers, monkeypatch):
    """Real endpoint wiring, synthetic Mongo inputs; not a live sync test."""
    import asyncio
    from datetime import datetime
    from db import STUDENT_MCQ_ATTEMPTS, get_db
    from routers import ranking, student_dashboard as sd

    today = datetime.now(sd.IST).date()
    monkeypatch.setattr(ranking, "INDIVIDUAL_MCQ_FROM", week_start(today))
    monkeypatch.setattr(sd, "_fetch_tracker_submissions_sync", lambda: [])
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)

    # Exercise the actual authenticated issuance/sync pipeline, not a client eligibility label.
    from db import CONTENT_QUESTIONS
    monkeypatch.setenv("MCQ_VERIFIED_DAILY_ENABLED", "1")
    async def seed_attempt():
        db = get_db()
        await db[STUDENT_MCQ_ATTEMPTS].insert_one({"studentId":"UMP0101", "attemptId":"legacy-practice", "kind":"practice", "score":20, "total":20})
        for i in range(10):
            await db[CONTENT_QUESTIONS].insert_one({"id":f"official-{i}", "status":"published", "subject":"Advanced Accounting", "chapterId":"synthetic", "prompt":f"Synthetic {i}", "questionType":"scenario_mcq" if i>=7 else "normal", "options":[{"id":"a","text":"A"},{"id":"b","text":"B"}], "correctOptionId":"a"})
    asyncio.run(seed_attempt())
    credentials = {"studentId":"UMP0101", "password":"synthetic-leaderboard"}
    # Router-only issuance does not relax candidate owner-only ASGI routing.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import student_attempts
    primary_app = FastAPI(); primary_app.include_router(student_attempts.router)
    primary_client = TestClient(primary_app)
    issued = primary_client.post("/api/student-attempts/daily-set", json=credentials|{"group":"Group I"})
    assert issued.status_code == 200, issued.text
    assignment = issued.json()
    attempt = {k:assignment[k] for k in ("officialSetId","date","group","bankRevision","questionIds")}
    attempt.update(attemptId="client-official", kind="daily", answers={q:0 for q in assignment["questionIds"]}, startedAt=assignment["issuedAt"], completedAt=int(datetime.now(sd.IST).timestamp()*1000), score=0, total=10, durationSeconds=1)
    synced = primary_client.post("/api/student-attempts/sync", json=credentials|{"attempts":[attempt]})
    assert synced.status_code == 200, synced.text
    assert synced.json()["acknowledgements"][0]["rankingEligible"] is True
    payload = _leaderboard(client, mentor_headers, period="weekly", segment="batch")
    assert payload["weights"]["mcqMode"] == "on"
    assert payload["weights"]["mcqMinCoverage"] is None
    assert payload["weights"]["mcqCoverageInformational"] is True
    board = next(b for b in payload["segments"] if b["key"] == "Before Result Batch 1")
    assert board["mcqCoverage"] == .5
    assert board["mcqUsed"] is True
    assert board["effectiveWeights"] == {"hours":40., "mcq":30., "attendance":30.}
    assert board["mcqPolicy"] == "individual-daily-full10-v2"
    points = {e["studentId"]:e["breakdown"]["mcqScore"] for e in board["entries"]}
    assert points == {"UMP0101":15., "UMP0102":0.}
    assert all(b["mcqUsed"] for b in payload["segments"])

    # The stored projection consumed by BOTH installed web and Android clients
    # must carry the same MCQ components, not a separate old coverage decision.
    _leaderboard(client, mentor_headers, period="weekly", refresh=1)
    projected = client.post('/api/student-dashboard/get',headers={"X-Student-Id":"UMP0101","X-Session-Password":"synthetic-leaderboard"},json={"action":"getLeaderboard"})
    assert projected.status_code==200  # 200 + safe projection, never 5xx
    assert projected.json()["found"] is True
    from db import DASHBOARD_SHARED
    from routers.student_dashboard import _leaderboard_for_student
    async def projection():
        db=get_db();shared=await db[DASHBOARD_SHARED].find_one({"_id":"shared"})
        return await _leaderboard_for_student(db,shared['leaderboard'],'UMP0101')
    student_rows=asyncio.run(projection())
    matching = [e for e in student_rows if e["studentId"] in points]
    assert len(matching) == 2
    for entry in matching:
        assert entry["mcqUsed"] is True
        assert entry["breakdown"]["mcqScore"] == points[entry["studentId"]]


def test_individual_cutover_does_not_rewrite_previous_weekly_top_payloads(client, mentor_headers, monkeypatch):
    from datetime import datetime
    from routers import ranking, student_dashboard as sd

    monkeypatch.setattr(sd, "_fetch_tracker_submissions_sync", lambda: [])
    monkeypatch.setattr(ranking, "INDIVIDUAL_MCQ_FROM", None)
    _import(client, mentor_headers)
    _seed_accounts(client, mentor_headers)
    params = {"weeks":3, "segment":"batch_group"}
    before = client.get("/api/student-dashboard/leaderboard/weekly-tops", headers=mentor_headers, params=params)
    assert before.status_code == 200, before.text
    monkeypatch.setattr(ranking, "INDIVIDUAL_MCQ_FROM", week_start(datetime.now(sd.IST).date()))
    after = client.get("/api/student-dashboard/leaderboard/weekly-tops", headers=mentor_headers, params=params)
    assert after.status_code == 200, after.text
    assert before.json()["weeks"][1:] == after.json()["weeks"][1:]
