"""Fail closed on unconfirmed writes; draft retry is one mentor-scoped intent."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from db import get_db
from routers import workbook_practice as p
from test_workbook_practice import feature_env, BOOK, book

@pytest.fixture
def book_store(monkeypatch):
    # The memory DB creates a new async wrapper for each [] access. Inject one
    # stable wrapper so a fault reaches the actual route, not a discarded proxy.
    db=get_db();collection=db[p.BOOKS]
    class InjectedDB:
        def __getitem__(self,name):
            return collection if name==p.BOOKS else db[name]
    monkeypatch.setattr(p,'get_db',lambda:InjectedDB())
    return collection

KEY='synthetic-draft-intent-000001'
PATH='/api/practice/mentor/workbooks'

def create(client,headers,body=None,key=KEY):
    return client.post(PATH,headers=headers,json=body or BOOK,params={'draftKey':key})

def test_same_draft_intent_replays_without_duplicate_or_replacement(client,mentor_headers):
    first=create(client,mentor_headers);second=create(client,mentor_headers)
    assert first.status_code==second.status_code==200
    assert first.json()==second.json()
    assert asyncio.run(get_db()[p.BOOKS].count_documents({}))==1
    changed=copy.deepcopy(BOOK);changed['title']='Different explicit intent'
    mismatch=create(client,mentor_headers,changed)
    assert mismatch.status_code==409
    assert asyncio.run(get_db()[p.BOOKS].count_documents({}))==1
    assert asyncio.run(get_db()[p.BOOKS].find_one({}))['title']==BOOK['title']

def test_published_intent_cannot_be_reused_to_create_another_draft(client,mentor_headers):
    first=create(client,mentor_headers);id=first.json()['id']
    assert client.post(PATH+'/'+id+'/publish',headers=mentor_headers).status_code==200
    assert create(client,mentor_headers).status_code==409
    fresh=create(client,mentor_headers,key='synthetic-draft-intent-000002')
    assert fresh.status_code==200 and fresh.json()['id']!=id
    assert asyncio.run(get_db()[p.BOOKS].count_documents({}))==2

@pytest.mark.parametrize('key',['short','unexpected space in key','x'*81])
def test_invalid_intent_key_writes_nothing(client,mentor_headers,key):
    assert create(client,mentor_headers,key=key).status_code==422
    assert asyncio.run(get_db()[p.BOOKS].count_documents({}))==0

def test_unacknowledged_create_is_not_reported_saved(client,mentor_headers,monkeypatch,book_store):
    collection=book_store
    monkeypatch.setattr(collection,'insert_one',AsyncMock(return_value=SimpleNamespace(acknowledged=False)))
    assert create(client,mentor_headers).status_code==503
    assert asyncio.run(collection.count_documents({}))==0

def test_create_requires_matching_readback(client,mentor_headers,monkeypatch,book_store):
    monkeypatch.setattr(book_store,'find_one',AsyncMock(return_value=None))
    assert create(client,mentor_headers).status_code==409

@pytest.mark.parametrize('published',[True,False])
@pytest.mark.parametrize('result,expected',[(SimpleNamespace(acknowledged=False,matched_count=1),503),(SimpleNamespace(acknowledged=True,matched_count=0),503),(SimpleNamespace(acknowledged=True,matched_count=1),409)],ids=['unacknowledged','unmatched','wrong-readback'])
def test_availability_requires_write_ack_match_and_readback(client,mentor_headers,book,monkeypatch,published,result,expected,book_store):
    collection=book_store
    asyncio.run(collection.update_one({'_id':book},{'$set':{'published':not published}}))
    monkeypatch.setattr(collection,'update_one',AsyncMock(return_value=result))
    response=client.post(PATH+'/'+book+('/publish' if published else '/unpublish'),headers=mentor_headers)
    assert response.status_code==expected
    assert asyncio.run(collection.find_one({'_id':book}))['published'] is not published

def test_missing_workbook_unpublish_is_not_false_success(client,mentor_headers):
    assert client.post(PATH+'/does-not-exist/unpublish',headers=mentor_headers).status_code==404
