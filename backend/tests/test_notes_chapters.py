"""Notes: series folder (Super 75 / teacher) + chapter-wise notes ("Ch 2 · …").

Owner ka FINAL structure (14 Oct 2026):
  * app me folder = ``category`` = SERIES ("Super 75" ya teacher ka naam)
  * us folder ke andar notes chapter-wise naam ke saath + chapter number se sorted
    ("Ch 2 · Chapter 2 Audit Test QP", phir "Ch 10 · …", phir "Ch 11 · …")
  * ``chapter`` field me ICAI chapter label, ``baseTitle`` me saaf title
"""
import asyncio
import pytest

from routers.notes_inbox import _norm_chapter, _sort_notes, _title_for
from routers.student_dashboard import _notes_for_student

BATCH = "Before Result Batch 1"


def seed_notes(rows):
    from db import DASHBOARD_SHARED, get_db

    async def _seed():
        await get_db()[DASHBOARD_SHARED].update_one(
            {"_id": "shared"}, {"$set": {"notes": rows}}, upsert=True
        )

    asyncio.run(_seed())


def read_notes():
    from db import DASHBOARD_SHARED, get_db

    async def _read():
        shared = await get_db()[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        return shared.get("notes") or []

    return asyncio.run(_read())


# ── helpers ─────────────────────────────────────────────────────────────────


def test_title_prefix_is_added_once_and_moves_with_the_chapter():
    assert _title_for("AS 13 Booster", "Ch 5 — Assets Based Accounting Standards") == "Ch 5 · AS 13 Booster"
    # chapter badla -> purana prefix hat jaata hai, stack nahi hota
    assert _title_for("Ch 5 · AS 13 Booster", "Ch 6 — Liabilities Based Accounting Standards") == "Ch 6 · AS 13 Booster"
    # chapter hata diya -> plain title wapas
    assert _title_for("Ch 5 · AS 13 Booster", "") == "AS 13 Booster"
    assert _title_for("Chapter 12 — Returns", "") == "Returns"
    assert _title_for("Plain Title", "") == "Plain Title"


def test_sort_notes_orders_by_subject_series_folder_then_chapter_number():
    notes = [
        {"id": "C", "subject": "Audit", "category": "Super 75", "chapter": "Ch 11 — Ethics", "title": "Ch 11 · Ethics"},
        {"id": "A", "subject": "Audit", "category": "Super 75", "chapter": "Ch 2 — Audit Strategy", "title": "Ch 2 · Strategy"},
        {"id": "B", "subject": "Audit", "category": "Super 75", "chapter": "Ch 10 — Audit of Banks", "title": "Ch 10 · Banks"},
        {"id": "D", "subject": "Accounts", "category": "Super 75", "chapter": "Ch 1 — Intro", "title": "Ch 1 · Intro"},
        {"id": "E", "subject": "Audit", "category": "CA Rahul", "chapter": "Ch 2 — Audit Strategy", "title": "Ch 2 · Strategy (Rahul)"},
    ]
    ordered = [n["id"] for n in _sort_notes(notes)]
    # Accounts pehle (subject order), phir Audit: CA Rahul folder, phir Super 75 (Ch 2, 10, 11)
    assert ordered == ["D", "E", "A", "B", "C"]


def test_norm_chapter_trims_and_caps():
    assert _norm_chapter("  Ch 2 — Audit Strategy  ") == "Ch 2 — Audit Strategy"
    assert len(_norm_chapter("x" * 200)) == 90


# ── bulk update ─────────────────────────────────────────────────────────────


def test_bulk_update_sets_series_folder_and_chapter_for_many_notes_at_once(client, mentor_headers):
    seed_notes([
        {"id": "NOTE-1", "title": "AS 13 Booster", "subject": "Accounts", "audience": BATCH, "group": "Both Groups"},
        {"id": "NOTE-2", "title": "AS 13 Extra", "subject": "Accounts", "audience": BATCH, "group": "Both Groups"},
        {"id": "NOTE-3", "title": "Untouched", "subject": "Law", "audience": BATCH, "group": "Both Groups"},
    ])

    res = client.post(
        "/api/notes-inbox/notes/bulk-update",
        headers=mentor_headers,
        json={"ids": ["NOTE-1", "NOTE-2"], "series": "Super 75", "chapter": "Ch 5 — Assets Based Accounting Standards"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updatedCount"] == 2
    assert body["missing"] == []

    stored = {n["id"]: n for n in read_notes()}
    # folder = series, note ka naam "Ch 5 · …"
    assert stored["NOTE-1"]["category"] == "Super 75"
    assert stored["NOTE-1"]["series"] == "Super 75"
    assert stored["NOTE-1"]["chapter"] == "Ch 5 — Assets Based Accounting Standards"
    assert stored["NOTE-1"]["title"] == "Ch 5 · AS 13 Booster"
    assert stored["NOTE-2"]["title"] == "Ch 5 · AS 13 Extra"
    # bina bheje note chhua nahi gaya
    assert "chapter" not in stored["NOTE-3"]
    assert stored["NOTE-3"]["title"] == "Untouched"


def test_bulk_update_reports_unknown_ids_and_can_clear_a_chapter(client, mentor_headers):
    seed_notes([
        {"id": "NOTE-1", "title": "Ch 3 · Framework", "baseTitle": "Framework", "subject": "Accounts",
         "category": "Super 75", "chapter": "Ch 3 — Framework", "series": "Super 75",
         "audience": BATCH, "group": "Both Groups"},
    ])
    res = client.post(
        "/api/notes-inbox/notes/bulk-update",
        headers=mentor_headers,
        json={"ids": ["NOTE-1", "NOTE-NOPE"], "chapter": ""},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updatedCount"] == 1
    assert body["missing"] == ["NOTE-NOPE"]
    stored = read_notes()[0]
    assert stored["chapter"] == ""
    assert stored["title"] == "Framework"       # prefix hat gaya
    assert stored["category"] == "Super 75"     # folder (series) waisa hi


# ── single note update ──────────────────────────────────────────────────────


def test_single_note_update_can_change_series_to_a_teachers_name(client, mentor_headers):
    seed_notes([
        {"id": "NOTE-9", "title": "Ch 1 · GST Ch 1 Notes", "baseTitle": "GST Ch 1 Notes", "subject": "GST",
         "series": "Super 75", "category": "Super 75", "chapter": "Ch 1 — GST in India - An Introduction",
         "audience": BATCH, "group": "Both Groups"},
    ])
    res = client.post(
        "/api/notes-inbox/notes/update",
        headers=mentor_headers,
        json={"id": "NOTE-9", "series": "CA Rahul", "chapter": "Ch 2 — Supply under GST"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"]["series"] == "CA Rahul"
    assert body["changed"]["category"] == "CA Rahul"
    stored = read_notes()[0]
    assert stored["series"] == "CA Rahul"
    assert stored["category"] == "CA Rahul"             # folder badla
    assert stored["chapter"] == "Ch 2 — Supply under GST"
    assert stored["title"] == "Ch 2 · GST Ch 1 Notes"   # prefix naye chapter ka


# ── student side ────────────────────────────────────────────────────────────


def test_students_receive_notes_folder_wise_then_chapter_wise(client, mentor_headers):
    seed_notes([
        {"id": "B", "title": "Ch 10 · Banks", "subject": "Audit", "category": "Super 75", "chapter": "Ch 10 — Audit of Banks",
         "audience": BATCH, "group": "Both Groups"},
        {"id": "A", "title": "Ch 2 · Strategy", "subject": "Audit", "category": "Super 75", "chapter": "Ch 2 — Audit Strategy",
         "audience": BATCH, "group": "Both Groups"},
        {"id": "C", "title": "Ch 2 · Nature", "subject": "Audit", "category": "CA Rahul", "chapter": "Ch 2 — Nature",
         "audience": BATCH, "group": "Both Groups"},
    ])
    account = {"batch": BATCH, "group": "Group 1", "attempt": "Jan 2027"}
    visible = _notes_for_student(read_notes(), account)
    # Pehle CA Rahul folder (Ch 2), phir Super 75 folder (Ch 2, phir Ch 10 — number order)
    assert [n["id"] for n in visible] == ["C", "A", "B"]


# ── publish ─────────────────────────────────────────────────────────────────


def test_publish_keeps_the_series_folder_and_chapterwise_title(client, mentor_headers, monkeypatch):
    """Publish -> Mongo note: folder = Super 75, title = "Ch 5 · …" (sheet mirror optional)."""
    from routers import notes_inbox

    monkeypatch.setattr(notes_inbox, "_drive_headers", lambda: {})
    monkeypatch.setattr(notes_inbox, "_drive_get", lambda *a, **k: {"id": "FILE-1", "name": "as13.pdf", "size": "1234"})
    monkeypatch.setattr(notes_inbox.requests, "post", lambda *a, **k: type("R", (), {"status_code": 200, "json": lambda self: {"id": "permission-fixture"}})())
    monkeypatch.setattr(notes_inbox, "_sheet_append_values", lambda coro: coro.close())
    monkeypatch.setattr(notes_inbox.push_service, "spawn", lambda coro: coro.close())

    res = client.post(
        "/api/notes-inbox/publish",
        headers=mentor_headers,
        json={
            "fileId": "FILE-1",
            "batches": [BATCH],
            "group": "Both Groups",
            "subject": "Accounts",
            "title": "AS 13 Practice Booster",
            "series": "Super 75",
            "chapter": "Ch 5 — Assets Based Accounting Standards",
        },
    )
    assert res.status_code == 200, res.text
    stored = read_notes()
    assert len(stored) == 1
    # folder = series ("Super 75"): student app me Super 75 folder ke andar hi dikhega
    assert stored[0]["category"] == "Super 75"
    assert stored[0]["series"] == "Super 75"
    assert stored[0]["chapter"] == "Ch 5 — Assets Based Accounting Standards"
    assert stored[0]["title"] == "Ch 5 · AS 13 Practice Booster"
    assert stored[0]["baseTitle"] == "AS 13 Practice Booster"


def test_bulk_update_requires_a_mentor_token(client):
    res = client.post(
        "/api/notes-inbox/notes/bulk-update",
        json={"ids": ["NOTE-1"], "chapter": "Ch 1 — X"},
    )
    assert res.status_code == 401


# ── migration (idempotent) ──────────────────────────────────────────────────


def test_migration_brings_notes_back_into_the_series_folder(client, mentor_headers):
    """Galti se chapter-folder me gaye notes wapas series folder me + title prefix."""
    seed_notes([
        {"id": "OLD-1", "title": "Chapter 2 Audit Test QP", "baseTitle": "Chapter 2 Audit Test QP",
         "subject": "Audit", "category": "Ch 2 — Audit Strategy, Audit Planning and Audit Programme",
         "chapter": "Ch 2 — Audit Strategy, Audit Planning and Audit Programme", "series": "Super 75",
         "description": "Super 75", "audience": BATCH, "group": "Both Groups"},
        {"id": "OLD-2", "title": "Plain note", "subject": "Law", "category": "",
         "audience": BATCH, "group": "Both Groups"},
    ])
    res = client.post("/api/notes-inbox/notes/migrate-series", headers=mentor_headers, json={"dryRun": False})
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == 1

    stored = {n["id"]: n for n in read_notes()}
    # folder wapas Super 75, title me chapter prefix, description saaf
    assert stored["OLD-1"]["category"] == "Super 75"
    assert stored["OLD-1"]["series"] == "Super 75"
    assert stored["OLD-1"]["chapter"] == "Ch 2 — Audit Strategy, Audit Planning and Audit Programme"
    assert stored["OLD-1"]["title"] == "Ch 2 · Chapter 2 Audit Test QP"
    assert stored["OLD-1"]["description"] == ""
    # jis note par kuch nahi tha wo waisa hi
    assert stored["OLD-2"]["category"] == ""
    assert stored["OLD-2"]["title"] == "Plain note"

    # idempotent: dobara chalao to kuch nahi badalta
    again = client.post("/api/notes-inbox/notes/migrate-series", headers=mentor_headers, json={"dryRun": False})
    assert again.json()["changed"] == 0


@pytest.mark.parametrize("mode", ["http", "empty", "blank", "wrong-type", "contradictory", "success-false", "invalid-json", "transport"])
def test_publish_never_saves_after_unconfirmed_drive_permission(client, mentor_headers, monkeypatch, mode):
    from routers import notes_inbox
    monkeypatch.setattr(notes_inbox, "_drive_headers", lambda: {})
    monkeypatch.setattr(notes_inbox, "_drive_get", lambda *a, **k: {"id": "FILE-1", "name": "synthetic.pdf", "size": "1234"})
    before = read_notes()
    calls = []
    forbidden = lambda *a, **k: pytest.fail("Unconfirmed permission must not publish/mirror/notify")
    monkeypatch.setattr(notes_inbox, "_sheet_append_values", forbidden)
    monkeypatch.setattr(notes_inbox.push_service, "spawn", forbidden)
    def post(*a, **k):
        calls.append(1)
        if mode == "transport": raise RuntimeError("synthetic-sensitive-provider-detail")
        class Response:
            status_code = 403 if mode == "http" else 200
            def json(self):
                if mode == "invalid-json": raise ValueError("synthetic-sensitive-provider-detail")
                return {"http": {"error": "synthetic-sensitive-provider-detail"}, "empty": {}, "blank": {"id": "  "}, "wrong-type": {"id": 123}, "contradictory": {"id": "fixture", "ok": False}, "success-false": {"id": "fixture", "success": False}}[mode]
        return Response()
    monkeypatch.setattr(notes_inbox.requests, "post", post)
    res = client.post("/api/notes-inbox/publish", headers=mentor_headers, json={"fileId": "FILE-1", "batches": [BATCH], "group": "Both Groups", "subject": "Accounts", "title": "Synthetic"})
    assert res.status_code == 502
    assert "synthetic-sensitive-provider-detail" not in res.text
    assert len(calls) == 1
    assert read_notes() == before
