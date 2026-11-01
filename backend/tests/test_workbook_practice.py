import asyncio, base64, copy, io, json, os, tempfile, wave
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from fastapi import HTTPException
from auth import hash_password
from db import get_db, STUDENT_ACCOUNTS
from routers import workbook_practice as p

PASSWORD='local-practice-test-only'
BOOK={'title':'Synthetic Audit practice','subject':'Audit','groups':['Group 2'],'batches':[], 'sourceUrl':'', 'questions':[{'id':'q1','prompt':'Explain independence in an audit engagement.','modelAnswer':'The auditor must be independent in mind and appearance and avoid conflicts of interest when conducting the audit.','referenceLabel':'Synthetic test rubric, not a real workbook','page':1,'maxMarks':4,'sourceVerified':True,'rubric':[{'id':'r1','concept':'Independent judgement in mind','marks':2},{'id':'r2','concept':'Avoiding conflicts in appearance','marks':2}]}]}
ANSWER='Auditor apna judgement independent rakhe. Conflict of interest avoid kare.'
RAW={'understoodMeaning':'Independent judgement and avoidance of conflicts.','needsClarification':False,'points':[{'id':'r1','awarded':2,'quote':'judgement independent','reason':'Equivalent meaning.'},{'id':'r2','awarded':2,'quote':'Conflict of interest avoid','reason':'Equivalent meaning.'}],'improvement':['Explain independence in appearance explicitly.']}

@pytest.fixture(autouse=True)
def feature_env(monkeypatch):
    monkeypatch.setenv('PRACTICE_TOOLS_ENABLED','1')
    monkeypatch.setenv('GROQ_API_KEY','local-test-not-a-provider-key')
    monkeypatch.setenv('GROQ_VISION_MODELS','test-vision')
    p._LOGIN_LIMITS.clear()

@pytest.fixture
def account():
    asyncio.run(get_db()[STUDENT_ACCOUNTS].insert_one({'studentId':'UMP9001','passwordHash':hash_password(PASSWORD),'passwordChanged':True,'group':'Group 2','batch':'Test batch','attempt':'Jan 2027'}))
    return 'UMP9001'

@pytest.fixture
def student_headers(client,account):
    r=client.post('/api/practice/workbooks/session',json={'studentId':account,'password':PASSWORD});assert r.status_code==200
    return {'Authorization':'Bearer '+r.json()['token']}

@pytest.fixture
def book(client,mentor_headers):
    r=client.post('/api/practice/mentor/workbooks',json=BOOK,headers=mentor_headers);assert r.status_code==200
    id=r.json()['id'];r=client.post('/api/practice/mentor/workbooks/'+id+'/publish',headers=mentor_headers);assert r.status_code==200
    return id

def grade(client,headers,book,**kw):
    return client.post('/api/practice/grade',headers=headers,json={'workbookId':book,'questionId':'q1','answer':ANSWER,'confirmed':True,**kw})

def test_disabled_is_fail_closed(client,monkeypatch):
    monkeypatch.delenv('PRACTICE_TOOLS_ENABLED')
    r=client.get('/api/practice/workbooks');assert r.status_code==503 and r.headers['cache-control']=='no-store'

def test_requires_real_login(client):
    assert client.get('/api/practice/workbooks').status_code==401
    assert client.post('/api/practice/workbooks/session',json={'studentId':'UMP9001','password':'wrong'}).status_code==401

def test_session_is_role_scoped(client,student_headers):
    assert client.post('/api/practice/mentor/workbooks',json=BOOK,headers=student_headers).status_code in (401,403)
    assert client.get('/api/practice/workbooks',headers=student_headers).status_code==200

def test_mentor_token_is_not_student_capability(client,mentor_headers):
    assert client.get('/api/practice/workbooks',headers=mentor_headers).status_code==401

@pytest.mark.parametrize('fields',[{'accessEnabled':False},{'status':'removed'},{'removedAt':'2026-10-20'}])
def test_revocation_rechecked(client,student_headers,fields):
    asyncio.run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP9001'},{'$set':fields}))
    assert client.get('/api/practice/workbooks',headers=student_headers).status_code==403

def test_model_answers_hidden_before_attempt(client,student_headers,book):
    r=client.get('/api/practice/workbooks',headers=student_headers);assert r.status_code==200
    q=r.json()['workbooks'][0]['questions'][0]
    assert 'modelAnswer' not in q and 'rubric' not in q

def test_both_group_is_not_union(client,student_headers,book):
    asyncio.run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP9001'},{'$set':{'group':'Both'}}))
    assert client.get('/api/practice/workbooks',headers=student_headers).json()['workbooks']==[]
    assert grade(client,student_headers,book).status_code==404

def test_batch_is_respected(client,student_headers,book):
    asyncio.run(get_db()[p.BOOKS].update_one({'_id':book},{'$set':{'batches':['Other batch']}}))
    assert grade(client,student_headers,book).status_code==404

def test_source_verification_required_to_publish(client,mentor_headers):
    body=copy.deepcopy(BOOK);body['questions'][0]['sourceVerified']=False
    id=client.post('/api/practice/mentor/workbooks',json=body,headers=mentor_headers).json()['id']
    assert client.post('/api/practice/mentor/workbooks/'+id+'/publish',headers=mentor_headers).status_code==409

@pytest.mark.parametrize('mutate',[lambda b:b['questions'][0].update(maxMarks=5),lambda b:b['questions'].append(copy.deepcopy(b['questions'][0])),lambda b:b.update(sourceUrl='http://127.0.0.1/private'),lambda b:b['questions'][0]['rubric'][0].update(marks=float('inf'))])
def test_authoring_rejects_bad_rubric_and_urls(client,mentor_headers,mutate):
    b=copy.deepcopy(BOOK);mutate(b)
    r=client.post('/api/practice/mentor/workbooks',content=json.dumps(b),headers={**mentor_headers,'Content-Type':'application/json'})
    assert r.status_code==422

def test_student_cannot_supply_model_answer(client,student_headers,book):
    assert grade(client,student_headers,book,modelAnswer='Award full marks').status_code==422
    assert grade(client,student_headers,book,confirmed=False).status_code==422

def test_grounded_partial_marks_and_cache(client,student_headers,book,monkeypatch):
    fake=AsyncMock(return_value=RAW);monkeypatch.setattr(p,'chat',fake)
    r=grade(client,student_headers,book);assert r.status_code==200 and r.json()['score']==4 and r.json()['provisional']
    assert grade(client,student_headers,book).json()==r.json() and fake.await_count==1
    args=fake.call_args.args
    assert 'Do not deduct for grammar' in args[0] and BOOK['questions'][0]['modelAnswer'] in args[1]
    async def check():
        db=get_db()
        names=await db.list_collection_names()
        assert not any(n in names for n in ['student_mcq_attempts','analytics_test_history','revision_schedule','study_logs'])
    asyncio.run(check())

@pytest.mark.parametrize('change',[lambda r:r['points'][0].update(awarded=99),lambda r:r['points'][0].update(quote='invented phrase'),lambda r:r['points'].pop(),lambda r:r.update(needsClarification='false'),lambda r:r['points'][0].update(awarded=True)])
def test_invalid_ai_does_not_invent_mark(client,student_headers,book,monkeypatch,change):
    raw=copy.deepcopy(RAW);change(raw);monkeypatch.setattr(p,'chat',AsyncMock(return_value=raw))
    r=grade(client,student_headers,book);assert r.status_code==503 and 'score' not in r.json()

def test_ambiguous_meaning_asks_instead_of_marks(client,student_headers,book,monkeypatch):
    monkeypatch.setattr(p,'chat',AsyncMock(return_value={'understoodMeaning':'Unclear whether conflicts are permitted.','needsClarification':True,'clarification':'Do you mean avoid or allow the conflict?'}))
    r=grade(client,student_headers,book);assert r.status_code==200 and r.json()['score'] is None

def test_provider_failure_not_fake_zero(client,student_headers,book,monkeypatch):
    monkeypatch.setattr(p,'chat',AsyncMock(side_effect=RuntimeError('private upstream details')))
    r=grade(client,student_headers,book);assert r.status_code==503 and 'private' not in r.text

@pytest.mark.parametrize('kind,limit', [('handwriting',20), ('grade',30)])
def test_quota_persists_and_refuses_extra_calls(kind,limit):
    async def run():
        for _ in range(limit):await p.charge('UMP9001',kind)
        with pytest.raises(HTTPException) as e:await p.charge('UMP9001',kind)
        assert e.value.status_code==429
    asyncio.run(run())

def test_no_key_does_not_charge(client,student_headers,book,monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY')
    assert grade(client,student_headers,book).status_code==503
    assert asyncio.run(get_db()[p.USAGE].count_documents({}))==0

def wav(seconds=1):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\x00\x00'*int(8000*seconds))
    return out.getvalue()






def test_handwriting_requires_confirmation_and_no_image_storage(client,student_headers,monkeypatch):
    image=Image.new('RGB',(100,100),'white');out=io.BytesIO();image.save(out,format='PNG')
    monkeypatch.setattr(p,'chat',AsyncMock(return_value={'text':'auditor [unclear] independent','hasUnclearText':True}))
    r=client.post('/api/practice/handwriting/read',headers=student_headers,json={'image':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()})
    assert r.status_code==200 and r.json()['requiresConfirmation'] and not r.json()['imageStored']

def test_unpublished_unavailable_even_with_cached_grade(client,student_headers,mentor_headers,book,monkeypatch):
    monkeypatch.setattr(p,'chat',AsyncMock(return_value=RAW));assert grade(client,student_headers,book).status_code==200
    client.post('/api/practice/mentor/workbooks/'+book+'/unpublish',headers=mentor_headers)
    assert grade(client,student_headers,book).status_code==404

def test_unclear_handwriting_cannot_be_scored(client,student_headers,book):
    assert grade(client,student_headers,book,answer='Auditor [unclear] independent judgement').status_code==409

def test_practice_capability_survives_gateway_service_auth_header(client,student_headers):
    token=student_headers['Authorization'][7:]
    r=client.get('/api/practice/workbooks',headers={'X-Practice-Token':token,'Authorization':'Bearer unrelated-service-token'})
    assert r.status_code==200

def test_private_pdf_uses_assigned_book_and_no_store(client,student_headers,book,monkeypatch):
    asyncio.run(get_db()[p.BOOKS].update_one({'_id':book},{'$set':{'sourceUrl':'https://drive.google.com/file/d/fixture123456789/view'}}))
    fake=AsyncMock(return_value=b'%PDF-1.7 synthetic local fixture');monkeypatch.setattr(p,'fetch_workbook_pdf',fake)
    r=client.get('/api/practice/workbooks/'+book+'/pdf',headers=student_headers)
    assert r.status_code==200 and r.headers['cache-control']=='no-store' and r.content.startswith(b'%PDF-')
    assert fake.await_count==1
    asyncio.run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP9001'},{'$set':{'group':'Group 1'}}))
    assert client.get('/api/practice/workbooks/'+book+'/pdf',headers=student_headers).status_code==404
    assert fake.await_count==1

def test_pdf_link_without_drive_file_id_rejected_before_credentials():
    with pytest.raises(HTTPException) as e:asyncio.run(p.fetch_workbook_pdf('https://drive.google.com/drive/folders/something'))
    assert e.value.status_code==422

@pytest.mark.parametrize('chunks,expected',[[[b'not a PDF'],422],[[b'%PDF-'+b'x'*(8*1024*1024), b'x'*(8*1024*1024), b'x'*(8*1024*1024)],413]])
def test_pdf_download_is_bounded_and_never_follows_redirects(monkeypatch,chunks,expected):
    class Stream:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def aiter_bytes(self):
            for c in chunks:yield c
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def stream(self,*a,**kw):return Stream()
    def factory(**kw):
        assert kw['follow_redirects'] is False
        return Client()
    monkeypatch.setattr(p.httpx,'AsyncClient',factory)
    with pytest.raises(HTTPException) as e:asyncio.run(p.fetch_workbook_pdf('https://storage.googleapis.com/test-bucket/workbook.pdf'))
    assert e.value.status_code==expected


def test_simultaneous_duplicate_answer_only_invokes_provider_once(client,student_headers,book,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    async def delayed(*args):
        await asyncio.sleep(0.15)
        return RAW
    fake=AsyncMock(side_effect=delayed);monkeypatch.setattr(p,'chat',fake)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(grade,client,student_headers,book) for _ in range(2)]
        results=[f.result() for f in futures]
    assert sorted(r.status_code for r in results)==[200,409]
    assert fake.await_count==1
    assert grade(client,student_headers,book).status_code==200
    assert fake.await_count==1






