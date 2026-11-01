"""Actual application route regression; synthetic memory DB, no live student data."""
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PATH = '/api/smart-targets/student/dashboard'

@pytest.fixture
def route_client():
    from server import app
    # No lifespan/startup jobs: only the actual registered request handlers.
    return TestClient(app)

def test_personal_dashboard_post_is_registered_in_actual_application(route_client):
    operation = route_client.get('/openapi.json').json()['paths'][PATH]
    assert 'post' in operation and 'get' not in operation
    # Missing credentials must hit validation, not a GET-only fallback405.
    assert route_client.post(PATH, json={}).status_code == 422
    assert route_client.get(PATH).status_code in (404, 405)

def test_legacy_get_only_fallback_explains405_without_authorizing_get():
    app = FastAPI()
    @app.get('/{path:path}')
    def old_fallback(path: str):
        return {'legacy': True}
    response = TestClient(app).post(PATH, json={})
    assert response.status_code == 405
    assert response.headers['allow'] == 'GET'

def test_real_dashboard_post_authenticates_owner_and_preserves_saved_data(route_client, monkeypatch):
    from auth import hash_password
    from db import get_db, STUDENT_ACCOUNTS
    from routers import smart_targets as targets
    from routers.revision_schedule import PLAN
    password = 'local-synthetic-password'
    async def setup():
        for sid in ('LOCAL_A', 'LOCAL_B'):
            await get_db()[STUDENT_ACCOUNTS].insert_one({
                'studentId': sid, 'passwordHash': hash_password(password),
                'group': 'Group 1', 'batch': 'LOCAL', 'attempt': 'Jan 2027',
            })
            await get_db()[PLAN].insert_one({'studentId': sid, 'concept': sid+' chapter',
                'subject': 'Taxation', 'dueOn': '2099-01-01'})
    async def sheet():
        return [['Student ID','Student Name','Batch','Group','Attempt'],
                ['LOCAL_A','Synthetic A','LOCAL','Group 1','Jan 2027'],
                ['LOCAL_B','Synthetic B','LOCAL','Group 1','Jan 2027']]
    monkeypatch.setattr(targets, '_sheet_students_rows', sheet)
    asyncio.run(setup())
    body={'studentId':'LOCAL_A','password':password}
    response=route_client.post(PATH+'?studentId=LOCAL_B',json=body)
    assert response.status_code==200, response.text
    data=response.json();assert data['studentId']=='LOCAL_A'
    assert [c['concept']for c in data['revisions']['chapters']]==['LOCAL_A chapter']
    assert route_client.post(PATH,json={**body,'password':'wrong'}).status_code==401
    assert route_client.post(PATH,json={**body,'ownerId':'LOCAL_B'}).status_code==422
    async def unchanged():
        assert await get_db()[PLAN].count_documents({})==2
        assert await get_db()[targets.PROGRESS].count_documents({})==0
    asyncio.run(unchanged())
