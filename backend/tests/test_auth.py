"""Auth tests: mentor login, role enforcement, fail-closed unconfigured creds."""
import os
from unittest import mock


def test_login_success(client, mentor_password):
    res = client.post("/api/auth/login", json={"email": "mentor@test.local", "password": mentor_password})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "mentor"
    assert body["token"]


def test_login_wrong_password(client):
    res = client.post("/api/auth/login", json={"email": "mentor@test.local", "password": "wrong"})
    assert res.status_code == 401


def test_content_api_requires_token(client):
    assert client.get("/api/content/queue").status_code == 401
    assert client.get("/api/analytics/overview").status_code == 401
    assert client.get("/api/content/releases").status_code == 401


def test_analytics_api_requires_mentor_role(client, mentor_headers):
    res = client.get("/api/analytics/overview", headers=mentor_headers)
    assert res.status_code == 200


def test_login_disabled_when_credentials_unconfigured(client):
    import config

    from auth import login_credentials_configured

    original = config.settings.mentor_password_hash
    try:
        config.settings.mentor_password_hash = ""
        assert login_credentials_configured() is False
        # fail closed: unconfigured deployments return 503 from /api/auth/login
        res = client.post("/api/auth/login", json={"email": "mentor@test.local", "password": "whatever"})
        assert res.status_code == 503
    finally:
        config.settings.mentor_password_hash = original
