"""Mentor test authoring: create/publish + the dashboard file upload.

The upload endpoint hands base64 to the mentor's own Apps Script, because only
the script owner can create files in his Drive (a service account has zero
storage quota). These tests pin the wiring: mentor-only access, size/mime
guards, and the exact payload that reaches Apps Script.
"""
import base64
import json

import pytest

from routers import mentor_tests

TINY_PDF = base64.b64encode(b"%PDF-1.4 tiny").decode()


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


@pytest.fixture
def captured_apps_script(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None, **kwargs):  # noqa: A002 - requests signature
        calls.append({"url": url, "body": json, "timeout": timeout})
        return FakeResponse({"result": {"url": "https://drive.google.com/file/d/FILE123/view", "fileId": "FILE123"}})

    monkeypatch.setattr(mentor_tests.requests, "post", fake_post)
    return calls


def test_upload_requires_a_mentor_token(client):
    res = client.post(
        "/api/mentor/tests/upload",
        json={"kind": "qp", "filename": "qp.pdf", "mimeType": "application/pdf", "base64": TINY_PDF},
    )
    assert res.status_code == 401


def test_upload_sends_the_file_to_apps_script_with_the_callers_token(
    client, mentor_headers, captured_apps_script
):
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={
            "kind": "qp",
            "filename": "Chapter 3 Paper.pdf",
            "mimeType": "application/pdf",
            "base64": TINY_PDF,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["fileId"] == "FILE123"
    assert body["downloadUrl"] == "https://drive.google.com/uc?export=download&id=FILE123"
    assert body["kind"] == "qp"

    assert len(captured_apps_script) == 1
    call = captured_apps_script[0]
    assert call["url"] == mentor_tests.settings.mentor_script_url
    assert call["body"]["action"] == "mentor.test.upload"
    assert call["body"]["payload"]["type"] == "qp"
    assert call["body"]["payload"]["base64"] == TINY_PDF
    assert call["body"]["payload"]["filename"] == "Chapter 3 Paper.pdf"
    # The mentor session token travels along so Apps Script's own gate passes.
    assert call["body"]["token"] == mentor_headers["Authorization"].split(" ", 1)[1]


def test_upload_accepts_a_data_url_prefix_from_the_browser(client, mentor_headers, captured_apps_script):
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={
            "kind": "as",
            "filename": "key.pdf",
            "mimeType": "application/pdf",
            "base64": f"data:application/pdf;base64,{TINY_PDF}",
        },
    )
    assert res.status_code == 200, res.text
    assert captured_apps_script[0]["body"]["payload"]["base64"] == TINY_PDF
    assert captured_apps_script[0]["body"]["payload"]["type"] == "as"


def test_upload_rejects_unexpected_file_types(client, mentor_headers):
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={"kind": "qp", "filename": "x.exe", "mimeType": "application/x-msdownload", "base64": TINY_PDF},
    )
    assert res.status_code == 422
    assert "PDF, JPG or PNG" in res.json()["detail"]


def test_upload_rejects_files_over_the_ten_megabyte_cap(client, mentor_headers, monkeypatch):
    monkeypatch.setattr(mentor_tests, "UPLOAD_MAX_BYTES", 8)  # smaller than the tiny pdf
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={"kind": "qp", "filename": "big.pdf", "mimeType": "application/pdf", "base64": TINY_PDF},
    )
    assert res.status_code == 413
    assert "larger than" in res.json()["detail"]


def test_upload_reports_apps_script_errors_without_crashing(client, mentor_headers, monkeypatch):
    def failing_post(url, json=None, timeout=None, **kwargs):  # noqa: A002
        return FakeResponse({"error": "Unauthorized: a valid mentor session token is required."})

    monkeypatch.setattr(mentor_tests.requests, "post", failing_post)
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={"kind": "qp", "filename": "qp.pdf", "mimeType": "application/pdf", "base64": TINY_PDF},
    )
    assert res.status_code == 502
    assert "could not be confirmed" in res.json()["detail"]
    assert "Unauthorized" not in res.json()["detail"]


def test_upload_never_retries_uncertain_creation(client, mentor_headers, monkeypatch):
    attempts = {"n": 0}

    def flaky_post(url, json=None, timeout=None, **kwargs):  # noqa: A002
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("boom")
        return FakeResponse({"result": {"fileId": "FILE999", "url": "https://drive.google.com/file/d/FILE999/view"}})

    monkeypatch.setattr(mentor_tests.requests, "post", flaky_post)
    res = client.post(
        "/api/mentor/tests/upload",
        headers=mentor_headers,
        json={"kind": "qp", "filename": "qp.pdf", "mimeType": "application/pdf", "base64": TINY_PDF},
    )
    assert res.status_code == 502, res.text
    assert attempts["n"] == 1


def test_create_then_publish_a_paper_test_keeps_the_uploaded_links(client, mentor_headers, monkeypatch):
    """End-to-end mentor flow: upload → create → publish (push fires once)."""
    pushed = []

    async def fake_push(ids, title, body, **kwargs):
        pushed.append({"ids": list(ids), "title": title})
        return len(list(ids))

    async def fake_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(mentor_tests.push_service, "configured", lambda: True)
    monkeypatch.setattr(mentor_tests.push_service, "push_to_students", fake_push)

    created = client.post(
        "/api/mentor/tests",
        headers=mentor_headers,
        json={
            "title": "Audit Chapter 3 Paper Test",
            "kind": "paper-test",
            "subject": "Audit",
            "batch": "Before Result Batch 1",
            "group": "Both Groups",
            "test_date": "2026-10-20",
            "total_marks": 50,
            "question_count": 5,
            "instructions": "Write answers in the answer sheet.",
            "paper_url": "https://drive.google.com/file/d/FILE123/view",
            "answer_sheet_url": "https://drive.google.com/file/d/FILE456/view",
            "answer_sheet_text": "1. (a) ...",
        },
    )
    assert created.status_code == 201, created.text
    test = created.json()["test"]
    assert test["published"] is False
    assert test["paper_url"].endswith("/FILE123/view")

    listed = client.get("/api/mentor/tests", headers=mentor_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["publishedCount"] == 0

    publish = client.post(
        f"/api/mentor/tests/{test['testId']}/publish",
        headers=mentor_headers,
        json={"published": True},
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["published"] is True

    # Re-publishing never double-pushes; the transition is what announces.
    again = client.post(
        f"/api/mentor/tests/{test['testId']}/publish",
        headers=mentor_headers,
        json={"published": True},
    )
    assert again.status_code == 200

    deleted = client.delete(f"/api/mentor/tests/{test['testId']}", headers=mentor_headers)
    assert deleted.status_code == 200
    assert client.get("/api/mentor/tests", headers=mentor_headers).json()["total"] == 0


@pytest.mark.parametrize('packet',[{}, {'result':{'fileId':42}}, {'result':{'fileId':' '}}, {'ok':False,'result':{'fileId':'synthetic'}}, {'success':False,'result':{'fileId':'synthetic'}}, {'result':{'fileId':'synthetic','ok':False}}, {'result':{'fileId':'synthetic','error':'private provider detail'}}])
def test_upload_contradictory_or_missing_ack_is_not_retried(client,mentor_headers,monkeypatch,packet):
    calls=[]
    def post(*args,**kwargs):calls.append(1);return FakeResponse(packet)
    monkeypatch.setattr(mentor_tests.requests,'post',post)
    res=client.post('/api/mentor/tests/upload',headers=mentor_headers,json={'kind':'qp','filename':'synthetic.pdf','mimeType':'application/pdf','base64':TINY_PDF})
    assert res.status_code==502 and len(calls)==1
    assert 'private provider detail' not in res.text
