"""Per-group leaderboards and the weekly Top 3 of each group.

Owner request 18-Oct-2026: "leaderboard me har batch ke 3 alag leaderboard dikhao -
Group 1, Group 2, Both Groups - batch wala jaisa hai waisa rahe. Aur har week ka top 3
in 6 groups se bhi nikle, kyunki chocolates wahi jeet-te hain."

So a batch is split into three boards by the Students sheet's own bucket, `Both` is its
own board and never a union, and a student the sheet cannot place is not ranked inside a
group they are not in - they show up as a board that cannot hand out a prize.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date.today()
from week_window import week_start  # noqa: E402

WEEK_DAYS = [(week_start(TODAY) + timedelta(days=i)).isoformat()
             for i in range((TODAY - week_start(TODAY)).days + 1)]

ROSTER = {
    # sid: (name, batch, group as the sheet writes it, hours per day)
    "UMP0201": ("Aarav One", "Before Result Batch 1", "Group 1", 6),
    "UMP0202": ("Bela Two", "Before Result Batch 1", "Group 2", 5),
    "UMP0203": ("Chet Three", "Before Result Batch 1", "Both Groups", 9),
    "UMP0204": ("Diya Four", "Before Result Batch 1", "Group 1", 2),
    "UMP0205": ("Eshan Five", "Before Result Batch 2", "group 2", 7),      # lower case in the sheet
    "UMP0206": ("Fala Six", "Before Result Batch 1", "", 10),              # no group set at all
}


def _act(sid, hours_per_day):
    from routers.ranking import StudentActivity

    batch, group = None, None
    # same batch/group the seeded accounts carry, for the pure-function tests
    _name, batch, group, _h = ROSTER[sid]
    return StudentActivity(
        student_id=sid, name=_name, batch=batch, group=group, attempt="Jan 2027",
        hours_by_date={date.fromisoformat(d): float(hours_per_day) for d in WEEK_DAYS},
        submitted_dates={date.fromisoformat(d) for d in WEEK_DAYS},
    )


# ----------------------------------------------------------------- the key itself

def test_board_key_is_batch_dot_the_sheet_bucket():
    from routers.ranking import segment_key

    assert segment_key(_act("UMP0201", 6), "batch_group") == "Before Result Batch 1 · Group 1"
    assert segment_key(_act("UMP0202", 5), "batch_group") == "Before Result Batch 1 · Group 2"
    assert segment_key(_act("UMP0205", 7), "batch_group") == "Before Result Batch 2 · Group 2"


def test_both_groups_is_its_own_board_and_never_a_union():
    from routers.ranking import segment_key

    key = segment_key(_act("UMP0203", 9), "batch_group")
    assert key == "Before Result Batch 1 · Both"
    assert "Group 1 +" not in key and "Group 2" not in key   # never "Group 1 + Group 2"


def test_a_student_the_sheet_cannot_place_gets_no_group_board():
    from routers.ranking import segment_key

    assert segment_key(_act("UMP0206", 10), "batch_group") == "Before Result Batch 1 · (no group set)"


def test_single_attribute_modes_still_work():
    from routers.ranking import segment_key

    assert segment_key(_act("UMP0201", 6), "batch") == "Before Result Batch 1"
    assert segment_key(_act("UMP0205", 7), "group") == "group 2"   # untouched: raw group view


# ------------------------------------------------------------------- the ranking

def test_each_group_board_is_ranked_on_its_own():
    from week_window import week_end
    from routers.ranking import rank_segments

    acts = [_act(sid, r[3]) for sid, r in ROSTER.items()]
    boards = rank_segments(acts, week_start(TODAY), min(week_end(TODAY), TODAY), "weekly", "batch_group")
    assert set(boards) == {
        "Before Result Batch 1 · Group 1",
        "Before Result Batch 1 · Group 2",
        "Before Result Batch 1 · Both",
        "Before Result Batch 1 · (no group set)",
        "Before Result Batch 2 · Group 2",
    }
    g1 = boards["Before Result Batch 1 · Group 1"]
    assert [r.student_id for r in g1] == ["UMP0201", "UMP0204"]      # 6 h/day beats 2 h/day
    assert [r.rank for r in g1] == [1, 2]                            # ranks restart per board
    # the 9 h/day "Both" student and the 10 h/day unplaced student must NOT steal G1's top
    assert "UMP0203" not in [r.student_id for r in g1]
    assert "UMP0206" not in [r.student_id for r in g1]


@pytest.fixture(scope="module", autouse=True)
def no_live_sheet(request):
    """Roster from Mongo accounts, never the live Students sheet (same as test_leaderboard)."""
    from routers import student_dashboard as sd

    def unavailable():
        raise RuntimeError("students sheet disabled in tests")

    original = sd._fetch_tracker_roster_sync
    sd._fetch_tracker_roster_sync = unavailable
    yield
    sd._fetch_tracker_roster_sync = original


def _seed():
    from db import DASHBOARD_STUDENTS, STUDENT_ACCOUNTS, get_db

    async def go():
        db = get_db()
        for sid, (name, batch, group, hours) in ROSTER.items():
            await db[STUDENT_ACCOUNTS].update_one({"studentId": sid}, {"$set": {
                "studentId": sid, "studentName": name, "attempt": "Jan 2027",
                "batch": batch, "group": group,
                "joinedOn": (TODAY - timedelta(days=30)).isoformat(),
                "passwordHash": "x",
            }}, upsert=True)
            await db[DASHBOARD_STUDENTS].update_one({"studentId": sid}, {"$set": {
                "studentId": sid,
                "studyLog": [{"date": d, "topic": "SFM", "hours": hours} for d in WEEK_DAYS],
            }}, upsert=True)

    asyncio.run(go())


def _get(client, headers, path, **params):
    res = client.get(path, headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_leaderboard_returns_one_board_per_batch_and_group(client, mentor_headers):
    _seed()
    data = _get(client, mentor_headers, "/api/student-dashboard/leaderboard",
                period="weekly", segment="batch_group")
    by_key = {s["key"]: s for s in data["segments"]}
    assert data["segment"] == "batch_group"
    assert by_key["Before Result Batch 1 · Group 1"]["label"] == "Before Result Batch 1 · Group 1"
    assert [e["studentId"] for e in by_key["Before Result Batch 1 · Group 1"]["entries"]] == \
        ["UMP0201", "UMP0204"]
    assert [e["rank"] for e in by_key["Before Result Batch 1 · Group 1"]["entries"]] == [1, 2]
    assert [e["studentId"] for e in by_key["Before Result Batch 2 · Group 2"]["entries"]] == ["UMP0205"]
    assert by_key["Before Result Batch 1 · Both"]["studentCount"] == 1
    # every board reports the same Sun..Sat window
    assert data["weekStart"] == week_start(TODAY).isoformat()


def test_batch_view_is_left_alone(client, mentor_headers):
    """He asked for the group boards on top of the batch one, not instead of it."""
    _seed()
    data = _get(client, mentor_headers, "/api/student-dashboard/leaderboard",
                period="weekly", segment="batch")
    keys = {s["key"] for s in data["segments"]}
    assert keys == {"Before Result Batch 1", "Before Result Batch 2"}
    assert len(next(s for s in data["segments"] if s["key"] == "Before Result Batch 1")["entries"]) == 5


def test_unknown_segment_is_rejected_with_the_new_message(client, mentor_headers):
    res = client.get("/api/student-dashboard/leaderboard", headers=mentor_headers,
                     params={"period": "weekly", "segment": "colour"})
    assert res.status_code == 400
    assert res.json()["detail"] == "segment must be batch, group or batch_group"


def test_weekly_tops_carry_a_podium_per_group_board(client, mentor_headers):
    _seed()
    data = _get(client, mentor_headers, "/api/student-dashboard/leaderboard/weekly-tops",
                weeks=2, segment="batch_group")
    week = data["weeks"][0]
    boards = {b["key"]: b for b in week["boards"]}
    assert boards["Before Result Batch 1 · Group 1"]["top3"][0]["studentId"] == "UMP0201"
    assert boards["Before Result Batch 1 · Group 1"]["top3"][1]["studentId"] == "UMP0204"
    assert [p["place"] for p in boards["Before Result Batch 2 · Group 2"]["top3"]] == [1]
    # 9 h/day "Both" student is that board's champion, and is not in any single-group board
    assert boards["Before Result Batch 1 · Both"]["top3"][0]["studentId"] == "UMP0203"
    assert all("UMP0203" not in [t["studentId"] for t in boards[k]["top3"]]
               for k in ("Before Result Batch 1 · Group 1", "Before Result Batch 2 · Group 2"))
    # the unplaced student is visible, but that board cannot award a prize
    stray = boards["Before Result Batch 1 · (no group set)"]
    assert stray["podiumEligible"] is False
    assert stray["top3"][0]["studentId"] == "UMP0206"
    assert [b["key"] for b in week["boards"]].index("Before Result Batch 1 · (no group set)") > \
        [b["key"] for b in week["boards"]].index("Before Result Batch 1 · Both")


def test_weekly_tops_batch_view_has_no_boards_key(client, mentor_headers):
    _seed()
    data = _get(client, mentor_headers, "/api/student-dashboard/leaderboard/weekly-tops",
                weeks=1, segment="batch")
    assert "boards" not in data["weeks"][0]
    assert data["weeks"][0]["top3"], "the batch podium must still be there"
