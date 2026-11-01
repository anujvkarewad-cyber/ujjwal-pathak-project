"""Existing receipt owner gate must not broaden when workbook routes are mounted."""
import json
import pytest
from server import app
from test_workbook_practice import feature_env, account, student_headers, PASSWORD


def test_no_duplicate_method_paths_and_no_workbook_receipt_routes():
    from routers import workbook_practice as p
    paths=[(method,r.path) for r in app.routes for method in getattr(r,'methods',()) if r.path.startswith('/api/practice/')]
    assert len(paths)==len(set(paths))
    assert all('/receipt/' not in r.path for r in p.router.routes)
    assert {r.path for r in p.router.routes}=={'/api/practice/workbooks/session','/api/practice/workbooks','/api/practice/workbooks/{book_id}/pdf','/api/practice/grade','/api/practice/mentor/workbooks','/api/practice/mentor/workbooks/{book_id}/publish','/api/practice/mentor/workbooks/{book_id}/unpublish','/api/practice/handwriting/read'}


def test_workbook_login_cannot_bypass_existing_receipt_owner_allowlist(client,student_headers,monkeypatch):
    monkeypatch.setenv('RECEIPT_TRANSCRIPTION_ENABLED','1')
    monkeypatch.setenv('RECEIPT_TRANSCRIPTION_TEST_STUDENTS','UMP0000')
    has_receipt=any(r.path=='/api/practice/receipt/transcribe' for r in app.routes)
    legacy=client.post('/api/practice/session',json={'studentId':'UMP9001','password':PASSWORD})
    assert legacy.status_code==(403 if has_receipt else 405)
    denied=client.post('/api/practice/receipt/transcribe',headers=student_headers,content=b'not-real-audio')
    assert denied.status_code==(403 if has_receipt else 405)
    assert legacy.headers['content-type'].startswith('application/json')
    assert denied.headers['content-type'].startswith('application/json')
    assert client.get('/api/practice/workbooks',headers=student_headers).status_code==200


def test_receipt_flag_cannot_enable_workbooks(client,monkeypatch):
    monkeypatch.delenv('PRACTICE_TOOLS_ENABLED',raising=False)
    monkeypatch.setenv('RECEIPT_TRANSCRIPTION_ENABLED','1')
    r=client.post('/api/practice/workbooks/session',json={'studentId':'UMP9001','password':'synthetic-only'})
    assert r.status_code==503
    assert r.headers['Cache-Control']=='no-store'
    assert r.headers['X-Content-Type-Options']=='nosniff'
