"""Mentor Password-reset tab: app + Students sheet must end up agreeing.

The bug class this feature exists for is a password that works in one place only: the
app accepted a value the sheet did not, or the sheet was mailed to a student while the
app refused it. So these tests care less about the form fields than about three
invariants:

  1. after a reset, `authenticate_student` accepts the new value;
  2. the sheet write is attempted for that same value, and a failure is reported, not
     swallowed;
  3. a student who was failing leaves the queue once it is fixed, and the password
     itself is never stored in the audit trail.
"""
import asyncio

import pytest

import login_failures
import password_sheet_sync
from auth import hash_password
from db import get_db, reset_db
from login_failures import COLLECTION as FAILS
from routers import password_reset, student_auth

class _Harness:
    """A db handle plus the sheet writes captured so far, for assertions.

    The motor database object is not ours to decorate, so item access is forwarded and
    the test reads `.writes` off the wrapper.
    """

    def __init__(self, db, writes):
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "writes", writes)

    def __getitem__(self, key):
        return self._db[key]

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_db"), name)


SHEET_HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch",
                "Passwords", "Password Changed"]
PEOPLE = {
    # sid: name, group, batch, sheet password cell, "Password Changed" flag
    "UMP0101": ("Aaditya", "Group 1", "Before Result Batch 1", "Maru@4182", ""),
    "UMP0102": ("Aditi", "Group 2", "Before Result Batch 2", "Oldpass@9", "Yes"),   # stale cell
    "UMP0103": ("Anushka", "Both", "Before Result Batch 1", "", ""),                # blank cell
}


def _sheet_rows():
    return [SHEET_HEADER] + [
        [sid, name, f"{sid.lower()}@x.com", "Inter", grp, "1", batch, pwd, flag]
        for sid, (name, grp, batch, pwd, flag) in PEOPLE.items()
    ]


@pytest.fixture()
def db(monkeypatch):
    asyncio.run(reset_db())
    handle = get_db()

    async def fake_rows():
        return _sheet_rows()

    monkeypatch.setattr(student_auth, "_sheet_students_rows", fake_rows)
    password_reset._sheet_cache.update(at=None, rows=[], ok=False)
    writes: list[tuple] = []

    async def ok_write(student_id, plaintext, *, flag_changed=True):
        writes.append((str(student_id).upper(), plaintext, flag_changed))
        return True

    monkeypatch.setattr(password_sheet_sync, "write_password", ok_write)
    return _Harness(handle, writes)


def _acc(sid, name, batch, group, **kw):
    # attempt must be the open one, or the login is refused by the attempt-access rule
    # before the password is ever checked - and these tests are about the password.
    doc = {"studentId": sid, "studentName": name, "batch": batch, "group": group, "attempt": "Jan 2027",
           "passwordHash": hash_password("Initial@1"), "passwordChanged": False,
           "removedAt": None, "accessEnabled": True}
    doc.update(kw)
    return doc


def _seed_db(db, **kw):
    async def go():
        await db["student_accounts"].insert_many([
            _acc("UMP0101", "Aaditya", "Before Result Batch 1", "", **kw),
            _acc("UMP0102", "Aditi", "Before Result Batch 2", ""),
            _acc("UMP0103", "Anushka", "Before Result Batch 1", ""),
        ])
    asyncio.run(go())


def _call(coro):
    return asyncio.run(coro)


# The mock store is motor-shaped, so every read/write has to be awaited.
def _insert(db, coll, doc):
    _call(db[coll].insert_one(doc))


def _update(db, coll, flt, upd):
    _call(db[coll].update_one(flt, upd))


def _find(db, coll, flt):
    return _call(db[coll].find_one(flt))


def _queue(db, days=7):
    return _call(password_reset.password_reset_queue(days=days, refresh=True, claims={"sub": "mentor"}))


# ── the failed-login ledger ─────────────────────────────────────────────── #
def test_wrong_password_leaves_a_record_and_right_one_clears_it(db):
    _insert(db, "student_accounts", _acc("UMP0101", "Aaditya", "Before Result Batch 1", ""))

    bad = _call(student_auth.authenticate_student("UMP0101", "nope"))
    assert bad["code"] == "wrong_password"
    # the login call itself is what records it - no separate write anywhere
    doc = _find(db, FAILS, {"_id": "UMP0101"})
    assert doc["openFails"] == 1 and doc["fails"] == 1
    assert doc["lastFailCode"] == "wrong_password"
    assert "nope" not in str(doc) and "Initial@1" not in str(doc)

    good = _call(student_auth.authenticate_student("UMP0101", "Initial@1"))
    assert good.get("success") is True, good
    doc = _find(db, FAILS, {"_id": "UMP0101"})
    assert doc["openFails"] == 0 and doc["lastOkAt"]


def test_login_still_works_when_the_bookkeeping_explodes(db, monkeypatch):
    """An analytics hiccup must never be the reason a student cannot sign in."""
    _insert(db, "student_accounts", _acc("UMP0101", "Aaditya", "Before Result Batch 1", ""))

    def boom(*a, **k):
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(student_auth.login_failures, "note_attempt", boom)
    res = _call(student_auth.authenticate_student("UMP0101", "Initial@1"))
    assert res.get("success") is True


def test_junk_input_is_not_recorded(db):
    assert student_auth._plausible_login_id("x") == ""
    assert student_auth._plausible_login_id("asdkjhasd") == ""
    assert student_auth._plausible_login_id("ump0101") == "UMP0101"


# ── the queue ───────────────────────────────────────────────────────────── #
def test_queue_lists_failing_students_first_and_uses_sheet_groups(db):
    _seed_db(db)
    _call(login_failures._bump_failure(db, "UMP0103", "wrong_password"))
    res = _queue(db)
    assert res["ok"] and res["sheetOk"] is True
    ids = [r["studentId"] for r in res["rows"]]
    assert ids[0] == "UMP0103", ids                       # the one who cannot get in
    row = res["rows"][0]
    assert row["openFails"] == 1 and row["sheetState"] == "blank"
    assert row["groupText"] == "Both" and row["bucket"] == "Both"   # the sheet's own word, not "Group 1 + Group 2"
    assert row["batch"] == "Before Result Batch 1" and row["scopeFrom"] == "sheet"
    assert {"stale", "blank"} <= set(res["counts"]) and res["counts"]["blank"] >= 1


def test_queue_marks_stale_sheet_cells_as_the_dangerous_ones(db):
    _seed_db(db)
    _update(db, "student_accounts", {"studentId": "UMP0102"}, {"$set": {"passwordHash": hash_password("Changed@7")}})
    res = _queue(db)
    row = next(r for r in res["rows"] if r["studentId"] == "UMP0102")
    assert row["sheetState"] == "stale"          # a dead value a mentor would mail out
    assert row["openFails"] == 0


def test_removed_students_are_not_offered_a_reset(db):
    _seed_db(db)
    _update(db, "student_accounts", {"studentId": "UMP0101"}, {"$set": {"removedAt": "2026-10-01T00:00:00Z"}})
    _insert(db, FAILS, {"_id": "UMP0101", "fails": 4, "openFails": 4, "lastFailAt": "2026-10-17T10:00:00"})
    assert "UMP0101" not in [r["studentId"] for r in _queue(db)["rows"]]


def test_queue_survives_a_dead_sheet(db, monkeypatch):
    async def boom():
        raise RuntimeError("Google is down")

    monkeypatch.setattr(student_auth, "_sheet_students_rows", boom)
    _seed_db(db)
    res = _queue(db)
    assert res["sheetOk"] is False and "could not be read" in res["sheetNote"]


# ── the reset ───────────────────────────────────────────────────────────── #
def test_reset_sets_app_password_and_updates_the_sheet(db):
    _seed_db(db)
    res = _call(password_reset.set_password(
        password_reset.ResetBody(studentId="UMP0101", password="Fresh@2026"), {"sub": "mentor"}))
    assert res["ok"] and res["generated"] is False
    assert res["password"] == "Fresh@2026" and res["sheetWritten"] is True
    acc = _find(db, "student_accounts", {"studentId": "UMP0101"})
    assert acc["passwordChanged"] is True and acc["forcePasswordChange"] is True  # import-safe + asks them to change
    assert "password" not in acc
    # the value that now works in the app is the exact value sent to the sheet
    assert db.writes == [("UMP0101", "Fresh@2026", False)]
    assert _call(student_auth.authenticate_student("UMP0101", "Fresh@2026")).get("success") is True
    assert _call(student_auth.authenticate_student("UMP0101", "Initial@1")).get("success") is not True


def test_blank_password_generates_a_usable_one(db):
    _seed_db(db)
    res = _call(password_reset.set_password(password_reset.ResetBody(studentId="UMP0102"), {"sub": "mentor"}))
    assert res["generated"] is True
    pwd = res["password"]
    assert len(pwd) >= 8 and "@" in pwd
    assert _call(student_auth.authenticate_student("UMP0102", pwd)).get("success") is True


def test_generated_passwords_differ(db):
    values = {password_reset.generate_password() for _ in range(40)}
    assert len(values) >= 38


def test_short_password_is_refused_and_changes_nothing(db):
    _seed_db(db)
    before = _find(db, "student_accounts", {"studentId": "UMP0101"})["passwordHash"]
    with pytest.raises(Exception) as exc:
        _call(password_reset.set_password(
            password_reset.ResetBody(studentId="UMP0101", password="abc"), {"sub": "mentor"}))
    assert exc.value.status_code == 400
    assert _find(db, "student_accounts", {"studentId": "UMP0101"})["passwordHash"] == before
    assert db.writes == []


def test_unknown_and_removed_ids_are_refused(db):
    _seed_db(db)
    with pytest.raises(Exception) as exc:
        _call(password_reset.set_password(
            password_reset.ResetBody(studentId="UMP9999", password="Whatever@1"), {"sub": "mentor"}))
    assert exc.value.status_code == 404 and "no app account" in str(exc.value.detail)

    _update(db, "student_accounts", {"studentId": "UMP0103"}, {"$set": {"removedAt": "2026-10-01T00:00:00Z"}})
    with pytest.raises(Exception) as exc:
        _call(password_reset.set_password(
            password_reset.ResetBody(studentId="UMP0103", password="Whatever@1"), {"sub": "mentor"}))
    assert exc.value.status_code == 409


def test_sheet_failure_is_reported_not_hidden(db, monkeypatch):
    _seed_db(db)

    async def dead(student_id, plaintext, *, flag_changed=True):
        raise RuntimeError("Sheets API 503")

    monkeypatch.setattr(password_sheet_sync, "write_password", dead)
    res = _call(password_reset.set_password(
        password_reset.ResetBody(studentId="UMP0101", password="Fresh@2026"), {"sub": "mentor"}))
    assert res["sheetWritten"] is False and res["sheetError"] == "RuntimeError"
    assert "NOT updated" in res["message"]


def test_reset_clears_the_failing_flag_and_leaves_no_password_behind(db):
    _seed_db(db)
    _call(login_failures._bump_failure(db, "UMP0101", "wrong_password"))
    _call(password_reset.set_password(
        password_reset.ResetBody(studentId="UMP0101", password="Fresh@2026"), {"sub": "mentor"}))
    assert _find(db, FAILS, {"_id": "UMP0101"})["openFails"] == 0
    assert "UMP0101" not in [r["studentId"] for r in _queue(db)["rows"]] or next(
        r for r in _queue(db)["rows"] if r["studentId"] == "UMP0101")["openFails"] == 0
    audit = _find(db, "analytics_audit_sync", {"action": "password_reset"})
    dumped = str(audit)
    assert "Fresh@2026" not in dumped                      # never stored, never logged
    assert audit["detail"]["studentId"] == "UMP0101" and audit["detail"]["sheetWritten"] is True


def test_force_change_can_be_declined(db):
    _seed_db(db)
    res = _call(password_reset.set_password(password_reset.ResetBody(
        studentId="UMP0101", password="Fresh@2026", forceChange=False), {"sub": "mentor"}))
    assert res["forceChange"] is False
    assert _find(db, "student_accounts", {"studentId": "UMP0101"})["forcePasswordChange"] is False


# ── the retry path for a dead sheet cell ───────────────────────────────── #
def test_sheet_sync_refuses_a_value_the_account_does_not_accept(db):
    _seed_db(db)
    with pytest.raises(Exception) as exc:
        _call(password_reset.sheet_sync(
            password_reset.SheetSyncBody(studentId="UMP0101", password="Guess@123"), {"sub": "mentor"}))
    assert exc.value.status_code == 400 and "dead value" in str(exc.value.detail)
    assert db.writes == []


def test_sheet_sync_writes_the_live_password(db):
    _seed_db(db)
    res = _call(password_reset.sheet_sync(
        password_reset.SheetSyncBody(studentId="UMP0101", password="Initial@1"), {"sub": "mentor"}))
    assert res["ok"] is True and db.writes == [("UMP0101", "Initial@1", False)]


def test_search_finds_students_the_queue_never_show(db):
    _seed_db(db)
    _insert(db, "student_accounts", _acc("UMP0777", "Zoya Khan", "Super 30", "Group 1"))
    res = _call(password_reset.password_reset_students(q="zoya", claims={"sub": "mentor"}))
    assert [r["studentId"] for r in res["rows"]] == ["UMP0777"]
    assert res["rows"][0]["groupText"] == "Group 1"       # no sheet row -> app value, still labelled
    assert _call(password_reset.password_reset_students(q="a", claims={"sub": "mentor"}))["rows"] == []


def test_history_lists_resets_without_secrets(db):
    _seed_db(db)
    _call(password_reset.set_password(password_reset.ResetBody(studentId="UMP0101"), {"sub": "mentor"}))
    res = _call(password_reset.password_reset_history(limit=10, claims={"sub": "mentor"}))
    assert res["entries"] and res["entries"][0]["action"] == "password_reset"
    assert "password" not in str(res["entries"][0]).lower().replace("password_reset", "")


def test_routes_are_mentor_only(client):
    for path in ("/api/password-reset/queue", "/api/password-reset/history"):
        assert client.get(path).status_code == 401
    assert client.post("/api/password-reset/set", json={"studentId": "UMP0101"}).status_code == 401
