"""Public student content serving: manifest + chunks, path safety, 404s."""
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402

FIXTURE_DIST = BACKEND_DIR / "tests" / "fixture_dist"


def _write_fixture_dist():
    FIXTURE_DIST.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIST / "web" / "chunks").mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIST / "mobile" / "chunks").mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 1,
        "revision": 1,
        "publishedAt": "2026-08-16T00:00:00Z",
        "publishedBy": "test",
        "catalogRevision": "may-2026",
        "chapters": [{
            "chapterId": "ch-acc-01",
            "counts": {"plain": 30, "scenarios": 5, "scenarioMcqs": 20, "total": 50},
            "questionIds": ["adp_q_ch-acc-01_01"],
            "chunkWeb": "chunks/ch-acc-01.r1.abc12345.json",
            "chunkMobile": "chunks/ch-acc-01.r1.abc12345.json",
            "contentHash": "sha256:abc12345",
        }],
    }
    (FIXTURE_DIST / "published-manifest.json").write_text(json.dumps(manifest))
    (FIXTURE_DIST / "web" / "chunks" / "ch-acc-01.r1.abc12345.json").write_text(json.dumps({"chapterId": "ch-acc-01", "hello": "web"}))
    (FIXTURE_DIST / "mobile" / "chunks" / "ch-acc-01.r1.abc12345.json").write_text(json.dumps({"chapterId": "ch-acc-01", "hello": "mobile"}))


def test_manifest_served(client):
    _write_fixture_dist()
    res = client.get("/api/content/student/manifest.json")
    assert res.status_code == 200
    assert res.json()["revision"] == 1
    assert res.headers["cache-control"].startswith("public")


def test_chunks_served_and_immutable(client):
    _write_fixture_dist()
    res = client.get("/api/content/student/chunks/web/chunks/ch-acc-01.r1.abc12345.json")
    assert res.status_code == 200
    assert res.json()["hello"] == "web"
    assert "immutable" in res.headers["cache-control"]

    res = client.get("/api/content/student/chunks/mobile/chunks/ch-acc-01.r1.abc12345.json")
    assert res.status_code == 200
    assert res.json()["hello"] == "mobile"


def test_path_traversal_blocked(client):
    _write_fixture_dist()
    # Traversal attempts must never return content files. Since the SPA
    # catch-all serves the app shell for unknown paths, assert the response is
    # NOT the published manifest (i.e. no data leak), then assert real chunk
    # routes still 404 for bad platforms / missing files.
    res = client.get("/api/content/student/chunks/web/../../published-manifest.json")
    assert res.status_code in (200, 404)
    body = res.text
    assert '"revision"' not in body or 'schemaVersion' not in body  # not the manifest JSON
    assert "adp_q_ch-acc-01_01" not in body  # not the chapter chunk

    res = client.get("/api/content/student/chunks/evil/chunks/x.json")
    assert res.status_code == 404
    res = client.get("/api/content/student/chunks/web/chunks/x.json")
    assert res.status_code == 404
    res = client.get("/api/content/student/chunks/web/chunks/%2e%2e/ch-acc-01.r1.abc12345.json")
    assert res.status_code == 404

    # The REAL manifest remains reachable only through the manifest route.
    manifest = client.get("/api/content/student/manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["revision"] == 1


def test_manifest_404_without_publish(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "content_dir", Path(str(tmp_path)))
    res = client.get("/api/content/student/manifest.json")
    assert res.status_code == 404


def test_bank_json_only_serves_published(client):
    """bank.json exposes published questions only, mapped into student shape."""
    import asyncio

    from db import CONTENT_QUESTIONS, get_db
    from tests.fixtures import seed_full_chapter, seed_sync

    seed_sync(seed_full_chapter)

    # Nothing approved → empty bank and lightweight polling metadata.
    res = client.get("/api/content/student/bank.json")
    assert res.status_code == 200
    assert res.json()["count"] == 0
    meta = client.get("/api/content/student/bank-meta.json")
    assert meta.status_code == 200
    assert meta.json() == {"revision": "published-r0", "count": 0}
    assert "no-store" in meta.headers["cache-control"]

    async def _approve_one_of_each():
        db = get_db()
        plain = await db[CONTENT_QUESTIONS].find_one({"questionType": "mcq"})
        await db[CONTENT_QUESTIONS].update_one({"id": plain["id"]}, {"$set": {"status": "approved"}})
        scenario = await db[CONTENT_QUESTIONS].find_one({"questionType": "scenario_mcq"})
        await db[CONTENT_QUESTIONS].update_one({"id": scenario["id"]}, {"$set": {"status": "release_candidate"}})

    seed_sync(_approve_one_of_each)

    # Approval and release-candidate are review workflow states, not student
    # publication states.
    res = client.get("/api/content/student/bank.json")
    assert res.json()["count"] == 0

    async def _publish_both():
        db = get_db()
        await db[CONTENT_QUESTIONS].update_many(
            {"status": {"$in": ["approved", "release_candidate"]}},
            {"$set": {"status": "published"}},
        )

    seed_sync(_publish_both)

    res = client.get("/api/content/student/bank.json")
    data = res.json()
    assert data["revision"] == "published-r0"
    assert data["count"] == 2
    assert data["count"] == len(data["questions"])
    assert res.headers["x-content-revision"] == "0"
    assert "no-store" in res.headers["cache-control"]
    meta = client.get("/api/content/student/bank-meta.json")
    assert meta.json() == {"revision": "published-r0", "count": 2}
    assert {q["kind"] for q in data["questions"]} == {"normal", "case-study"}

    normal = next(q for q in data["questions"] if q["kind"] == "normal")
    assert normal["subject"] == "Accounting"
    assert normal["difficulty"] in {"Easy", "Medium", "Hard"}  # mapped from easy/moderate/hard
    assert isinstance(normal["answer"], int)  # 0-based correct-option index
    assert len(normal["options"]) == 4

    case = next(q for q in data["questions"] if q["kind"] == "case-study")
    assert case["caseStudy"]["passage"]  # passage joined from the scenario doc
