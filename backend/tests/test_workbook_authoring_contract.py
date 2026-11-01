"""Actual authoring helper payload -> existing local workbook API, synthetic only."""
import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from routers import workbook_practice as p
from test_workbook_practice import feature_env, account, student_headers

FIXTURES = json.loads((Path(__file__).parent/'fixtures/workbook_authoring_payloads.json').read_text())

@pytest.mark.parametrize('payload', FIXTURES, ids=lambda b:b['questions'][0]['format'])
def test_real_authoring_payload_roundtrip(client, mentor_headers, student_headers, monkeypatch, payload):
    asyncio.run(p.get_db()[p.STUDENT_ACCOUNTS].update_one({'studentId':'UMP9001'},{'$set':{'batch':'Test A'}}))
    original=copy.deepcopy(payload)
    created=client.post('/api/practice/mentor/workbooks',headers=mentor_headers,json=payload)
    assert created.status_code==200
    bid=created.json()['id']
    assert client.post('/api/practice/mentor/workbooks/'+bid+'/publish',headers=mentor_headers).status_code==200
    response=client.get('/api/practice/workbooks',headers=student_headers)
    assert response.status_code==200 and len(response.json()['workbooks'])==1
    question=response.json()['workbooks'][0]['questions'][0]
    assert question['format']==payload['questions'][0]['format']
    public=json.dumps(question)
    assert all(s not in public for s in ['correctOptionId','acceptedAnswers','"matches"','modelAnswer','rubric'])
    kind=question['format']
    if kind!='written':
        provider=AsyncMock(side_effect=AssertionError('No objective AI call'))
        monkeypatch.setattr(p,'chat',provider)
        answer={'mcq':{'choice':'B'},'blanks':{'responses':{'p1':'independence','p2':'appearance'}},'matching':{'responses':{'p1':'Y','p2':'X'}}}[kind]
        graded=client.post('/api/practice/grade',headers=student_headers,json={'workbookId':bid,'questionId':'q1','answer':json.dumps(answer),'confirmed':True})
        assert graded.status_code==200 and graded.json()['score']==4
        assert graded.json()['assessmentMode']=='deterministic-approved-key'
        provider.assert_not_awaited()
        assert asyncio.run(p.get_db()[p.FEEDBACK].count_documents({}))==0
        assert asyncio.run(p.get_db()[p.USAGE].count_documents({}))==0
    assert payload==original

@pytest.mark.parametrize('payload',FIXTURES,ids=lambda b:b['questions'][0]['format'])
def test_unverified_new_draft_cannot_publish(client,mentor_headers,payload):
    body=copy.deepcopy(payload);body['questions'][0]['sourceVerified']=False
    result=client.post('/api/practice/mentor/workbooks',headers=mentor_headers,json=body)
    assert result.status_code==200
    assert client.post('/api/practice/mentor/workbooks/'+result.json()['id']+'/publish',headers=mentor_headers).status_code==409
