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


def test_existing_token_cannot_survive_removed_configured_principal(client, mentor_headers, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'mentor_email', 'replacement@test.local')
    monkeypatch.setattr(settings, 'mentor_accounts', '')
    assert client.get('/api/content/queue', headers=mentor_headers).status_code == 401


def test_unconfigured_mentor_credentials_also_disable_existing_token(client, mentor_headers, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'mentor_password_hash', '')
    monkeypatch.setattr(settings, 'mentor_accounts', '')
    assert client.get('/api/analytics/overview', headers=mentor_headers).status_code == 401


def test_configured_multi_account_principal_keeps_authority(client, mentor_headers, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'mentor_accounts', 'mentor@test.local:synthetic-not-used')
    monkeypatch.setattr(settings, 'mentor_password_hash', '')
    assert client.get('/api/content/queue', headers=mentor_headers).status_code == 200
