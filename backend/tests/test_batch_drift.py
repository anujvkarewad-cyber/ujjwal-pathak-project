"""Sheet Batch ⇄ Mongo batch drift check and one-click sync.

Why this exists: a student's own profile shows what validateLogin returns, which
is the Students sheet, while test/notes/target/push audience is taken from Mongo.
A hand edit in the sheet therefore never reaches the app and silently keeps the
student in the wrong batch. The rule under test:

  * drift = active student whose sheet Batch differs from the Mongo batch,
  * master accounts (ALL) and soft-removed students are never drift,
  * a sheet row with no Mongo account is reported, never "fixed" here,
  * apply copies the SHEET value (re-read, never the client's copy) and writes
    one audit row per student, touching nothing else on the account.
"""
import asyncio

import pytest

from db import STUDENT_ACCOUNTS, STUDENT_ADMIN_AUDIT, get_db
from routers.student_auth import batch_drift_rows

HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch"]


def _sheet(*rows):
    return [HEADER] + [list(row) for row in rows]


def _seed(student_id, batch, **extra):
    doc = {
        "studentId": student_id,
        "studentName": f"Student {student_id}",
        "batch": batch,
        "passwordHash": "x",
        "updatedAt": "2026-10-15T00:00:00+00:00",
    }
    doc.update(extra)
    asyncio.run(get_db()[STUDENT_ACCOUNTS].insert_one(doc))


# ── the pure rule ───────────────────────────────────────────────────────────
def test_only_active_students_with_a_real_difference_are_drift():
    accounts = [
        {"studentId": "UMP0132", "studentName": "Khushi", "batch": "Before Result Batch 2"},
        {"studentId": "UMP0040", "studentName": "Palak", "batch": "Before Result Batch 1"},
        {"studentId": "UMP0039", "studentName": "Neer", "batch": "Before Result Batch 1",
         "removedAt": "2026-10-14T06:59:22+00:00"},
    ]
    sheet = _sheet(
        ("UMP0132", "Khushi", "k@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 1"),
        ("UMP0040", "Palak", "p@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 1"),
        ("UMP0039", "Neer", "n@e.com", "IP", "Group 1", "Jan 2027", "After Result Batch 1"),
        ("UMP0000", "Ujjwal (Master)", "u@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 2"),
        ("UMP9999", "Admin (Master)", "a@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 2"),
    )
    out = batch_drift_rows(sheet, accounts)
    assert [row["studentId"] for row in out["drift"]] == ["UMP0132"]
    assert out["drift"][0]["sheetBatch"] == "Before Result Batch 1"
    assert out["drift"][0]["mongoBatch"] == "Before Result Batch 2"
    # removed students and the master accounts are not reported as anything
    assert out["needsImport"] == []
    assert out["skipped"]["removedStudents"] == 1


def test_column_order_and_blank_cells_are_tolerated():
    rows = [
        ["Batch", "Student ID", "Student Name"],
        ["After Result Batch 2", "UMP0100", "Mahadev"],
        ["", "UMP0101", "Gurasis"],          # no batch typed yet -> not a drift
        ["After Result Batch 1", "not-an-id", "Junk"],
    ]
    accounts = [
        {"studentId": "UMP0100", "studentName": "Mahadev", "batch": "Before Result Batch 1"},
        {"studentId": "UMP0101", "studentName": "Gurasis", "batch": "Before Result Batch 1"},
    ]
    out = batch_drift_rows(rows, accounts)
    assert [row["studentId"] for row in out["drift"]] == ["UMP0100"]


def test_sheet_row_without_an_account_is_reported_for_import():
    out = batch_drift_rows(_sheet(("UMP0068", "New", "n@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 2")), [])
    assert out["drift"] == []
    assert out["needsImport"] == [{"studentId": "UMP0068", "studentName": "New", "sheetBatch": "Before Result Batch 2"}]


def test_missing_header_is_not_reported_as_healthy():
    assert batch_drift_rows([["id", "name"]], [])["skipped"]["noHeader"] is True


# ── the two mentor routes ───────────────────────────────────────────────────
SHEET = _sheet(
    ("UMP0132", "Khushi", "k@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 1"),
    ("UMP0040", "Palak", "p@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 1"),
    ("UMP0068", "New", "n@e.com", "IP", "Group 1", "Jan 2027", "Before Result Batch 2"),
)


@pytest.fixture
def patched_sheet(monkeypatch):
    import routers.student_auth as mod

    async def fake():
        return SHEET

    monkeypatch.setattr(mod, "_sheet_batch_rows", fake)
    return mod


def _doc(student_id):
    return asyncio.run(get_db()[STUDENT_ACCOUNTS].find_one({"studentId": student_id}))


def test_drift_report_lists_the_difference(client, mentor_headers, patched_sheet):
    _seed("UMP0132", "Before Result Batch 2")
    _seed("UMP0040", "Before Result Batch 1")
    res = client.get("/api/student-auth/students/batch-drift?refresh=1", headers=mentor_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["driftCount"] == 1 and body["needsImportCount"] == 1
    assert body["drift"][0]["studentId"] == "UMP0132"
    assert body["needsImport"][0]["studentId"] == "UMP0068"


def test_apply_writes_the_sheet_value_and_audits_it(client, mentor_headers, patched_sheet):
    _seed("UMP0132", "Before Result Batch 2", group="Group 1", caLevel="CA Intermediate")
    before = _doc("UMP0132")

    res = client.post(
        "/api/student-auth/students/batch-drift/apply",
        json={"studentIds": ["UMP0132"]},
        headers=mentor_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["synced"] == 1 and body["remaining"] == 0 and body["ok"] is True
    assert body["rows"][0] == {"studentId": "UMP0132", "from": "Before Result Batch 2",
                              "to": "Before Result Batch 1"}

    after = _doc("UMP0132")
    assert after["batch"] == "Before Result Batch 1"
    assert after["group"] == before["group"] and after["caLevel"] == before["caLevel"]
    assert after["passwordHash"] == before["passwordHash"]  # never touched
    assert after["batchUpdatedBy"] == "mentor@test.local"

    audit = asyncio.run(get_db()[STUDENT_ADMIN_AUDIT].find({"studentId": "UMP0132"}).to_list(10))
    rows = [row for row in audit if row["action"] == "student_batch_drift_sync"]
    assert len(rows) == 1
    assert rows[0]["previousBatch"] == "Before Result Batch 2"
    assert rows[0]["batch"] == "Before Result Batch 1"

    # and after the sync there is nothing left to sync
    again = client.post(
        "/api/student-auth/students/batch-drift/apply",
        json={"studentIds": ["*"]},
        headers=mentor_headers,
    )
    assert again.json()["synced"] == 0


def test_apply_refuses_ids_that_are_not_drifting(client, mentor_headers, patched_sheet):
    _seed("UMP0132", "Before Result Batch 1")      # already matches the sheet
    _seed("UMP0040", "Before Result Batch 1")
    res = client.post(
        "/api/student-auth/students/batch-drift/apply",
        json={"studentIds": ["UMP0132", "UMP0040"]},
        headers=mentor_headers,
    )
    assert res.json() == {"ok": True, "synced": 0, "rows": [], "remaining": 0,
                          "message": "Nothing to sync - those students already match."}


def test_drift_routes_need_a_mentor(client, patched_sheet):
    assert client.get("/api/student-auth/students/batch-drift").status_code in (401, 403)
    assert client.post("/api/student-auth/students/batch-drift/apply", json={"studentIds": ["*"]}).status_code in (401, 403)


def test_drift_sync_cannot_bypass_a_pending_workspace_transfer(client, mentor_headers, patched_sheet):
    import asyncio
    from db import get_db
    from routers.mentor_workspace import LOCKS
    _seed('UMP0132', 'Before Result Batch 2')
    asyncio.run(get_db()[LOCKS].insert_one({'_id':'UMP0132', 'planId':'pending-transfer'}))
    response = client.post('/api/student-auth/students/batch-drift/apply', headers=mentor_headers, json={'studentIds':['UMP0132']})
    assert response.status_code == 200
    assert response.json()['synced'] == 0 and response.json()['ok'] is False
    assert _doc('UMP0132')['batch'] == 'Before Result Batch 2'
