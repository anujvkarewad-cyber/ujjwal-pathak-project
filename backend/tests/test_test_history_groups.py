"""Per-test grouping on the mentor's submissions screen, using the sheet's bucket rule.

What these tests are really protecting is the sentence a mentor reads off the screen:
"these students did not submit this test". For this program that is decided by the
Students tab's Group cell, which is a BUCKET - "Group 1", "Group 2" or "Both" - and a
test published to one bucket is owed by exactly that bucket of that batch.

The owner spelled this out on 17-Oct-2026 after the first sheet-backed version still
listed wrong people: it treated "Both" as "Group 1 + Group 2", so a Group 2 test in
Before Result Batch 2 also showed the both-group students and printed them as
"Group 1 + Group 2", which looked like Group 1 students had been dragged in. Under the
rule below: a Group 2 test shows Group 2 rows, a Both Groups test shows Both rows, and
the label is always the sheet's own word.
"""
import asyncio

import pytest

from db import get_db, reset_db
from routers import student_auth, test_history

# Header order is not fixed in the real sheet, so the reader resolves columns by name.
SHEET_HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch",
                "Passwords", "Password Changed"]


def _rows(mapping):
    """mapping: sid -> (name, group text as the sheet writes it, batch)."""
    return [SHEET_HEADER] + [[sid, name, f"{sid.lower()}@x.com", "Inter", grp, "Jan 2027", batch, "", ""]
                             for sid, (name, grp, batch) in mapping.items()]


# The live shape: three buckets inside two batches, plus one student with no group and
# one student in another batch. The app's own group column is EMPTY for all of them,
# which is the production condition this feature has to survive.
PEOPLE = {
    "UMP0201": ("G2 Aniya", "Group 2", "Before Result Batch 2"),
    "UMP0202": ("G2 Bohra", "Group 2", "Before Result Batch 2"),
    "UMP0203": ("G1 Chetan", "Group 1", "Before Result Batch 2"),
    "UMP0204": ("Both Deepa", "Both", "Before Result Batch 2"),
    "UMP0205": ("Both Elvish", "both groups", "Before Result Batch 2"),
    "UMP0206": ("No group Farha", "", "Before Result Batch 2"),
    "UMP0207": ("G2 in BRB1", "Group 2", "Before Result Batch 1"),
    "UMP0208": ("Both in Super30", "Both", "Super 30"),
}


@pytest.fixture()
def db(monkeypatch):
    asyncio.run(reset_db())
    handle = get_db()
    state = {"rows": _rows(PEOPLE), "fail": False}

    async def fake_rows():
        if state["fail"]:
            raise RuntimeError("Students sheet is unreachable right now.")
        return state["rows"]

    monkeypatch.setattr(student_auth, "_sheet_students_rows", fake_rows)
    test_history._scope_cache.update(at=None, rows={}, ok=False)

    def set_sheet(mapping):
        state["rows"] = _rows(mapping)
        test_history._scope_cache.update(at=None, rows={}, ok=False)

    def no_sheet():
        state["fail"] = True
        test_history._scope_cache.update(at=None, rows={}, ok=False)

    handle.sheet = set_sheet
    handle.no_sheet = no_sheet
    handle.seed = lambda **kw: asyncio.run(_seed(**kw))
    return handle


async def _seed(accounts=(), tests=(), entries=()):
    db = get_db()
    if accounts:
        await db["student_accounts"].insert_many(list(accounts))
    if tests:
        await db["mentor_tests"].insert_many(list(tests))
    if entries:
        await db["analytics_test_history"].insert_many(list(entries))


def _acc(sid, name, batch, group="", **kw):
    return {"studentId": sid, "studentName": name, "batch": batch, "group": group,
            "removedAt": None, "accessEnabled": True, **kw}


def _test(tid, title, date, batch, group, published=True):
    return {"_id": tid, "testId": tid, "title": title, "kind": "paper-test", "subject": "Audit",
            "test_date": date, "batch": batch, "group": group, "published": published}


def _entry(sid, name, tid, title, date, pct, at="2026-10-10T10:00:00Z"):
    return {"studentId": sid, "studentName": name, "testId": tid, "title": title,
            "kind": "paper-test", "subject": "Audit", "test_date": date, "batch": "",
            "selfMarks": False, "score": pct, "total": 100, "scorePct": pct, "at": at}


def _accounts_from_sheet():
    return [_acc(sid, name, batch) for sid, (name, _grp, batch) in PEOPLE.items()]


def _all(db):
    return asyncio.run(test_history.build_test_groups(db))


def _one(db, tid):
    return next(g for g in _all(db) if g["testId"] == tid)


def _seeded(db, tests, entries=()):
    db.seed(accounts=_accounts_from_sheet(), tests=tests, entries=entries)


def test_bucket_is_the_sheets_own_vocabulary():
    assert test_history._bucket("Group 1") == "Group 1"
    assert test_history._bucket("Group 2") == "Group 2"
    assert test_history._bucket("Both") == "Both"
    assert test_history._bucket("Both Groups") == "Both"       # what the publish form writes
    assert test_history._bucket("group2") == "Group 2"
    assert test_history._bucket("Group 1 + Group 2") == "Both"  # same intent, still one bucket
    assert test_history._bucket("Evening batch") == ""          # never a guess
    assert test_history._bucket("") == ""


def test_group2_test_shows_only_group2_students(db):
    """The complaint this exists for: a BRB2 + Group 2 test must not contain anybody else.

    UMP0204/05 are 'Both' and UMP0203 is 'Group 1' - all three sit in BRB2 and were being
    listed as if they owed this test.
    """
    _seeded(db, [_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")])
    g = _one(db, "TST_G2")
    assert sorted(r["studentId"] for r in g["notSubmitted"]) == ["UMP0201", "UMP0202"]
    assert g["audienceSize"] == 2
    assert g["audienceGroup"] == "Group 2" and g["audienceBucket"] == "Group 2"
    for other in ("UMP0203", "UMP0204", "UMP0205", "UMP0207", "UMP0208"):
        assert other not in [r["studentId"] for r in g["notSubmitted"]]


def test_both_groups_test_shows_only_both_students(db):
    """"Both Groups" is the third bucket in this program, not a union of the other two."""
    _seeded(db, [_test("TST_BOTH", "BRB2 Both Groups", "2026-10-15", "Before Result Batch 2", "Both Groups")])
    g = _one(db, "TST_BOTH")
    assert sorted(r["studentId"] for r in g["notSubmitted"]) == ["UMP0204", "UMP0205"]
    # as the sheet spells each one - no expansion into "Group 1 + Group 2"
    assert g["groupLabels"] == ["Both", "both groups"]


def test_no_row_is_ever_labelled_with_two_groups(db):
    """A 'Both' student reads as 'Both'. The expansion was the misreading."""
    _seeded(db, [_test("TST_BOTH", "BRB2 Both Groups", "2026-10-15", "Before Result Batch 2", "Both Groups")],
            entries=[_entry("UMP0204", "Both Deepa", "TST_BOTH", "BRB2 Both Groups", "2026-10-15", 78)])
    g = _one(db, "TST_BOTH")
    assert g["submitted"][0]["groupText"] == "Both"
    assert g["submitted"][0]["bucket"] == "Both"
    assert not any("+" in (r["groupText"] or "") for r in g["submitted"] + g["notSubmitted"])


def test_batch_is_matched_exactly(db):
    """A Group 2 student of BRB1 does not owe a Group 2 test published to BRB2."""
    _seeded(db, [_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")])
    g = _one(db, "TST_G2")
    assert "UMP0207" not in [r["studentId"] for r in g["notSubmitted"]]  # Group 2, wrong batch
    assert all(r["batch"] == "Before Result Batch 2" for r in g["notSubmitted"])


def test_group_came_from_the_sheet_not_the_app(db):
    """Mongo's group column is empty for every one of these accounts."""
    _seeded(db, [_test("TST_G1", "BRB2 Group 1", "2026-10-15", "Before Result Batch 2", "Group 1")])
    g = _one(db, "TST_G1")
    assert [r["studentId"] for r in g["notSubmitted"]] == ["UMP0203"]
    assert g["notSubmitted"][0]["scopeFrom"] == "sheet"
    assert g["notSubmitted"][0]["groupText"] == "Group 1"


def test_student_without_a_group_is_never_called_missing(db):
    _seeded(db, [_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")])
    g = _one(db, "TST_G2")
    assert "UMP0206" not in [r["studentId"] for r in g["notSubmitted"]]
    assert [r["studentId"] for r in g["unknownScope"]] == ["UMP0206"]


def test_open_group_test_lists_the_whole_batch(db):
    """No group chosen on the test = every bucket of that batch, and nobody is 'unsure'."""
    _seeded(db, [_test("TST_ALL", "BRB2 open", "2026-10-15", "Before Result Batch 2", "")])
    g = _one(db, "TST_ALL")
    assert g["audienceSize"] == 6 and g["unknownScope"] == []
    assert sorted(g["groupLabels"]) == sorted(["Group 1", "Group 2", "Both", "both groups"])


def test_unreadable_group_on_the_test_is_flagged(db):
    """Something the app cannot map to a bucket must be visible, not silently widened."""
    _seeded(db, [_test("TST_WEIRD", "Odd audience", "2026-10-15", "Before Result Batch 2", "Sr. Team")])
    g = _one(db, "TST_WEIRD")
    assert g["audienceGroupUnreadable"] is True
    assert sorted(r["studentId"] for r in g["notSubmitted"]) == sorted(
        ["UMP0201", "UMP0202", "UMP0203", "UMP0204", "UMP0205", "UMP0206"])


def test_locked_out_students_are_reported_separately(db):
    db.seed(
        accounts=[_acc(sid, name, batch, accessEnabled=(sid != "UMP0202"))
                  for sid, (name, _g, batch) in PEOPLE.items()],
        tests=[_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")],
    )
    g = _one(db, "TST_G2")
    assert g["noAccess"] == ["UMP0202"]
    assert [r["studentId"] for r in g["notSubmitted"]] == ["UMP0201"]


def test_removed_students_are_not_asked_for_anything(db):
    db.seed(
        accounts=[_acc(sid, name, batch, removedAt=("2026-10-01T00:00:00Z" if sid == "UMP0202" else None))
                  for sid, (name, _g, batch) in PEOPLE.items()],
        tests=[_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")],
    )
    assert [r["studentId"] for r in _one(db, "TST_G2")["notSubmitted"]] == ["UMP0201"]


def test_falls_back_to_app_records_when_sheet_unreadable(db):
    """A Google outage must not break the screen - but the answer then comes from the app
    and the payload says so, so a wider list is never mistaken for the sheet's word."""
    db.no_sheet()
    db.seed(
        accounts=[_acc("UMP0201", "G2 Aniya", "Before Result Batch 2", "Group 2"),
                  _acc("UMP0202", "G2 Bohra", "Before Result Batch 2", "Group 2"),
                  _acc("UMP0204", "Both Deepa", "Before Result Batch 2", "Both")],
        tests=[_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")],
    )
    g = _one(db, "TST_G2")
    assert sorted(r["studentId"] for r in g["notSubmitted"]) == ["UMP0201", "UMP0202"]  # Both still excluded
    assert g["notSubmitted"][0]["scopeFrom"] == "accounts"
    payload = asyncio.run(test_history.mentor_test_history_groups({"sub": "mentor"}))
    assert payload["scopeSource"] == "accounts" and "unreadable" in payload["scopeNote"]


def test_submitted_row_keeps_the_bucket_for_filtering(db):
    """A student who submitted is still shown with the group the sheet gives them."""
    _seeded(
        db,
        [_test("TST_BOTH", "BRB2 Both Groups", "2026-10-15", "Before Result Batch 2", "Both Groups")],
        entries=[_entry("UMP0205", "Both Elvish", "TST_BOTH", "BRB2 Both Groups", "2026-10-15", 61)],
    )
    g = _one(db, "TST_BOTH")
    assert g["submitted"][0]["studentId"] == "UMP0205" and g["submitted"][0]["groupText"] == "both groups"
    assert [r["studentId"] for r in g["notSubmitted"]] == ["UMP0204"]


def test_retries_count_once_with_best_score(db):
    db.sheet({"UMP0201": ("G2 Aniya", "Group 2", "Before Result Batch 2")})
    db.seed(
        accounts=[_acc("UMP0201", "G2 Aniya", "Before Result Batch 2")],
        tests=[_test("TST_MULTI", "Twice", "2026-10-15", "All", "")],  # open: this test is about retries
        entries=[_entry("UMP0201", "G2 Aniya", "TST_MULTI", "Twice", "2026-10-15", 40, "2026-10-15T10:00:00Z"),
                 _entry("UMP0201", "G2 Aniya", "TST_MULTI", "Twice", "2026-10-15", 88, "2026-10-15T16:00:00Z")],
    )
    g = _one(db, "TST_MULTI")
    assert g["totalStudents"] == 1 and g["submitted"][0]["attempts"] == 2
    assert g["submitted"][0]["scorePct"] == 88


def test_orphan_attempt_claims_no_audience(db):
    db.seed(entries=[_entry("ZZZ9999", "Ghost", "TST_ORPHAN", "Old Test", "2026-09-01", 50, "2026-09-01T10:00:00Z")])
    g = _one(db, "TST_ORPHAN")
    assert g["knownAudience"] is False and g["notSubmitted"] == [] and g["audienceSize"] == 0
    assert g["groupLabels"] == [] and g["totalStudents"] == 1


def test_newest_test_first(db):
    _seeded(db, [_test("TST_OLD", "Older", "2026-10-01", "All", ""), _test("TST_NEW", "Newer", "2026-10-16", "All", "")])
    assert [g["title"] for g in _all(db)] == ["Newer", "Older"]


def test_notify_targets_the_bucket_only(db, monkeypatch):
    """The push button can only ever reach the exact bucket - not the batch."""
    _seeded(db, [_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")])
    calls = []

    async def fake_push(student_ids, title, body, **kw):
        calls.append(list(student_ids))
        return len(calls[-1])

    async def fake_devices():
        return ["UMP0201", "UMP0202", "UMP0203", "UMP0204", "UMP0205", "UMP0206"]

    monkeypatch.setattr(test_history.push_service, "push_to_students", fake_push)
    monkeypatch.setattr(test_history.push_service, "students_with_devices", fake_devices)
    res = asyncio.run(test_history.notify_missing_submissions("TST_G2", {}, {"sub": "mentor"}))
    assert res["ok"] is True
    assert sorted(res["targets"]) == ["UMP0201", "UMP0202"]
    assert "UMP0204" not in res["targets"] and "UMP0203" not in res["targets"]


def test_submitter_outside_the_bucket_is_split_out_not_mixed_in(db):
    """Their marks are kept, but they are not part of this test's roster.

    A 'Both' student who somehow submitted the Group 2 test must not turn up in the
    submitted list (that is what made the screen look like the wrong students were
    listed) - they go into their own box, and the audience math stays about the bucket.
    """
    _seeded(
        db,
        [_test("TST_G2", "BRB2 Group 2", "2026-10-15", "Before Result Batch 2", "Group 2")],
        entries=[_entry("UMP0201", "G2 Aniya", "TST_G2", "BRB2 Group 2", "2026-10-15", 70),
                 _entry("UMP0204", "Both Deepa", "TST_G2", "BRB2 Group 2", "2026-10-15", 55),
                 _entry("UMP0207", "G2 in BRB1", "TST_G2", "BRB2 Group 2", "2026-10-15", 40)],
    )
    g = _one(db, "TST_G2")
    assert [r["studentId"] for r in g["submitted"]] == ["UMP0201"]
    assert sorted(r["studentId"] for r in g["outsideAudience"]) == ["UMP0204", "UMP0207"]
    assert g["outsideAudience"][0]["groupText"] in ("Both", "Group 2")
    assert g["totalStudents"] == 1 and g["audienceSize"] == 2  # Aniya submitted, Bohra did not
    assert [r["studentId"] for r in g["notSubmitted"]] == ["UMP0202"]


def test_outside_box_is_empty_when_audience_is_unknown(db):
    """An attempt with no test on file has no audience to be outside of."""
    db.seed(entries=[_entry("ZZZ9999", "Ghost", "TST_ORPHAN", "Old Test", "2026-09-01", 50, "2026-09-01T10:00:00Z")])
    g = _one(db, "TST_ORPHAN")
    assert g["outsideAudience"] == [] and g["outsideAudienceCount"] == 0
    assert g["totalStudents"] == 1
