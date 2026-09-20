"""File snapshots must never run against a real MongoDB, and must never
clone a collection that already has documents."""
from persist import should_persist, uses_real_mongo


def test_uses_real_mongo_detects_atlas(monkeypatch):
    monkeypatch.setattr("persist.settings.mongo_url", "mongodb+srv://user:pass@cluster.mongodb.net")
    assert uses_real_mongo() is True
    assert should_persist() is False


def test_memory_url_is_not_real_mongo(monkeypatch):
    monkeypatch.setattr("persist.settings.mongo_url", "memory://")
    assert uses_real_mongo() is False


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["store"] in {"memory", "mongo"}
    assert body["questions"] == 0
    assert body["published"] == 0
    assert "studentAttempts" in body
