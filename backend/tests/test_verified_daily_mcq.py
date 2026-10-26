import asyncio
from datetime import date, timedelta
import pytest
from fastapi import HTTPException
from db import get_db, CONTENT_QUESTIONS, CONTENT_RELEASES
from routers import student_attempts, student_sync, ranking, student_dashboard
from daily_mcq_verification import now

@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv('MCQ_VERIFIED_DAILY_ENABLED', '1')
    async def validate(sid, password):
        if password != 'test-only-password': raise HTTPException(401, 'Denied')
        return {'success': True, 'studentId': sid, 'group': 'Group 1'}
    monkeypatch.setattr(student_attempts, '_validate_existing_student_login', validate)
    student_sync._last_sync.clear()
    async def seed():
        db=get_db()
        await db[CONTENT_RELEASES].insert_one({'revision':12})
        for i in range(12):
            await db[CONTENT_QUESTIONS].insert_one({'id':f'q{i}', 'status':'published',
                'subject':'Advanced Accounting', 'chapterId':'chapter-1', 'prompt':f'Question {i}',
                'questionType':'scenario_mcq' if i>=7 else 'normal',
                'options':[{'id':'a','text':'A'},{'id':'b','text':'B'}], 'correctOptionId':'a'})
    asyncio.run(seed())

def credentials(sid='UMP0001'):
    return {'studentId':sid, 'password':'test-only-password'}

def issue(client, sid='UMP0001', group='Group I'):
    result=client.post('/api/student-attempts/daily-set',json=credentials(sid)|{'group':group})
    assert result.status_code==200,result.text
    return result.json()

def attempt(official, count=10, correct=7):
    ids=official['questionIds'];ts=int(now().timestamp()*1000)
    return {'attemptId':f"daily:{official['date']}:{official['group']}", 'kind':'daily',
        **{k:official[k] for k in ('officialSetId','date','group','bankRevision','questionIds')},
        'answers':{qid:0 if i<correct else 1 for i,qid in enumerate(ids[:count])},
        'startedAt':official['issuedAt'],'completedAt':ts, 'score':10, 'total':10,'durationSeconds':1}

def submit(client, a, sid='UMP0001'):
    return client.post('/api/student-attempts/sync',json=credentials(sid)|{'attempts':[a]})

def restored(client):
    r=client.post('/api/student-attempts/restore',json=credentials())
    assert r.status_code==200;return r.json()['daily']

def test_complete_ten_earns_accuracy_not_perfect_score(client):
    r=submit(client,attempt(issue(client),correct=7));assert r.status_code==200,r.text
    assert r.json()['acknowledgements'][0]['rankingEligible'] is True
    row=restored(client)[0]
    assert row['score']==7 and row['rankingVerification']['correct']==7
    assert 'password' not in row

def test_zero_correct_is_valid_completion_but_zero_points(client):
    assert submit(client,attempt(issue(client),correct=0)).status_code==200
    v=restored(client)[0]['rankingVerification'];assert v['eligible'] is True and v['correct']==0

def test_nine_answers_backup_without_credit(client):
    r=submit(client,attempt(issue(client),count=9));assert r.status_code==200
    assert r.json()['acknowledgements'][0]['rankingEligible'] is False

def test_client_daily_label_without_assignment_never_earns_credit(client):
    a=attempt(issue(client));a.pop('officialSetId');a['rankingVerification']={'eligible':True,'correct':10}
    assert submit(client,a).status_code==200
    assert restored(client)[0]['rankingVerification']['eligible'] is False

def test_practice_perfect_never_earns_ranking_credit(client):
    a=attempt(issue(client));a.update(kind='practice',attemptId='practice:1',config={});a.pop('officialSetId')
    r=submit(client,a);assert r.status_code==200
    assert r.json()['acknowledgements'][0]['rankingEligible'] is False

def test_duplicate_sync_and_new_attempt_id_do_not_inflate_credit(client):
    a=attempt(issue(client));assert submit(client,a).status_code==200
    a['attemptId']='different-client-id'
    r=submit(client,a);assert r.status_code==200
    assert r.json()['acknowledgements'][0]['status']=='duplicate'
    assert len(restored(client))==1
    days=asyncio.run(student_dashboard._verified_daily_days(get_db()))
    assert list(days['UMP0001'].values())==[[10,7]]

def test_conflicting_rewrite_refused_and_original_backup_preserved(client):
    a=attempt(issue(client));assert submit(client,a).status_code==200
    a['answers'][a['questionIds'][-1]]=0
    assert submit(client,a).status_code==409
    assert restored(client)[0]['score']==7

@pytest.mark.parametrize('field,value',[('bankRevision','forged'),('group','Group II'),('date','2025-01-01'),('questionIds',['forged']*10)])
def test_assignment_binding_rejects_tampering(client,field,value):
    a=attempt(issue(client));a[field]=value
    assert submit(client,a).status_code in (409,422)

def test_assignment_is_student_bound(client):
    assert submit(client,attempt(issue(client)),sid='UMP0002').status_code==409

def test_unknown_or_other_roster_group_not_issued(client):
    assert client.post('/api/student-attempts/daily-set',json=credentials()|{'group':'Group II'}).status_code==403

def test_assignment_frozen_across_bank_revision_changes(client):
    first=issue(client)
    asyncio.run(get_db()[CONTENT_RELEASES].insert_one({'revision':13}))
    assert issue(client)==first

def test_short_bank_fails_closed(client):
    asyncio.run(get_db()[CONTENT_QUESTIONS].delete_many({'questionType':'scenario_mcq'}))
    assert client.post('/api/student-attempts/daily-set',json=credentials()|{'group':'Group I'}).status_code==409

def test_future_time_and_out_of_option_answer_rejected(client):
    a=attempt(issue(client));a['completedAt']+=86400000
    assert submit(client,a).status_code==409
    a=attempt(issue(client));a['answers'][a['questionIds'][0]]=3
    assert submit(client,a).status_code==422

def test_bool_answers_cannot_be_coerced_to_integer(client):
    a=attempt(issue(client));a['answers'][a['questionIds'][0]]=True
    assert submit(client,a).status_code==422

def test_selected_period_verified_only_and_volume_20_unchanged(monkeypatch):
    start=date(2026,10,18);end=start+timedelta(days=6)
    monkeypatch.setattr(ranking,'INDIVIDUAL_MCQ_FROM',start)
    a=ranking.StudentActivity(student_id='UMP0001',joined_on=start,
        questions_attempted=10000,questions_correct=10000,
        verified_mcq_by_date={start:[10,7], start-timedelta(days=1):[10,10],end+timedelta(days=1):[10,10]})
    assert ranking.mcq_enabled([a],start,end) is True
    result=ranking.score_student(a,start,end,'weekly',start)
    assert result.breakdown['mcqScore']==10.5
    assert ranking.weights()==(40,30,30)
    a.verified_mcq_by_date={}
    assert ranking.score_student(a,start,end,'weekly',start).breakdown['mcqScore']==0


def test_issuance_disabled_by_default(client,monkeypatch):
    monkeypatch.delenv('MCQ_VERIFIED_DAILY_ENABLED')
    assert client.post('/api/student-attempts/daily-set',json=credentials()|{'group':'Group I'}).status_code==503

@pytest.mark.parametrize('peers',[0,1,5,6,10])
def test_individual_credit_never_depends_on_peer_coverage(monkeypatch,peers):
    start=date(2026,10,18);end=start+timedelta(days=6)
    monkeypatch.setattr(ranking,'INDIVIDUAL_MCQ_FROM',start)
    solver=ranking.StudentActivity(student_id='solver', joined_on=start, verified_mcq_by_date={start:[10,7]})
    others=[ranking.StudentActivity(student_id=f'p{i}', joined_on=start) for i in range(peers)]
    use=ranking.mcq_enabled([solver]+others,start,end,start)
    assert use is True
    assert ranking.score_student(solver,start,end,'weekly',start,use).breakdown['mcqScore']==10.5
    assert ranking.mcq_coverage([solver]+others,start,end,start)==1/(peers+1)


def test_restart_retains_official_assignment_id_and_exact_answers(client, monkeypatch, tmp_path):
    """Actual file snapshot/reset/reload, not just a restore endpoint in one process."""
    import persist
    from db import reset_db, STUDENT_MCQ_ATTEMPTS
    from daily_mcq_verification import SETS
    monkeypatch.setenv('CONTENT_STORE', str(tmp_path / 'store.json'))
    monkeypatch.setattr(persist, 'should_persist', lambda: True)
    official = issue(client)
    a = attempt(official, correct=7)
    assert submit(client, a).status_code == 200
    async def restart():
        await persist.dump_store_sync()
        await reset_db()
        assert await persist.restore_store()
        return await get_db()[SETS].find_one({'_id': official['officialSetId']})
    saved = asyncio.run(restart())
    assert saved is not None, 'Official assignment identity lost across snapshot restart'
    assert saved['questionIds'] == official['questionIds']
    r = submit(client, a)
    assert r.status_code == 200, r.text
    assert r.json()['acknowledgements'][0]['status'] == 'duplicate'
    assert restored(client)[0]['answers'] == a['answers']
    assert asyncio.run(get_db()[STUDENT_MCQ_ATTEMPTS].count_documents({})) == 1


def test_offline_completed_daily_keeps_original_day_after_late_sync(client, monkeypatch):
    from datetime import timedelta
    import daily_mcq_verification as daily
    original_now = daily.now()
    official = issue(client)
    a = attempt(official)
    monkeypatch.setattr(daily, 'now', lambda: original_now + timedelta(days=2))
    r = submit(client, a)
    assert r.status_code == 200, r.text
    row = restored(client)[0]
    assert row['date'] == official['date']
    assert row['rankingVerification']['day'] == official['date']
    assert row['completedAt'] == a['completedAt']


def test_assignment_ack_has_durable_snapshot_before_return(client, monkeypatch, tmp_path):
    import json, persist
    from daily_mcq_verification import SETS
    path = tmp_path / 'store.json'
    monkeypatch.setenv('CONTENT_STORE', str(path))
    monkeypatch.setattr(persist, 'should_persist', lambda: True)
    official = issue(client)
    rows = json.loads(path.read_text())[SETS]
    assert rows[0]['_id'] == official['officialSetId']
    assert rows[0]['questions'] and rows[0]['studentId'] == 'UMP0001'


def test_snapshot_restore_never_overwrites_existing_official_assignment(client, monkeypatch, tmp_path):
    import json, persist
    from daily_mcq_verification import SETS
    official = issue(client)
    path = tmp_path / 'store.json'
    path.write_text(json.dumps({SETS: [{'_id': official['officialSetId'], 'studentId': 'different-owner', 'questions': []}]}))
    monkeypatch.setenv('CONTENT_STORE', str(path))
    asyncio.run(persist.restore_store())
    saved = asyncio.run(get_db()[SETS].find_one({'_id': official['officialSetId']}))
    assert saved['studentId'] == 'UMP0001'
    assert saved['questionIds'] == official['questionIds']


def test_snapshot_write_failure_never_returns_success_ack(client, monkeypatch, tmp_path):
    import persist
    official = issue(client)
    a = attempt(official)
    monkeypatch.setenv('CONTENT_STORE', str(tmp_path / 'store.json'))
    monkeypatch.setattr(persist, 'should_persist', lambda: True)
    def disk_failure(_):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(persist, '_write_snapshot', disk_failure)
    with pytest.raises(OSError, match='synthetic disk failure'):
        submit(client, a)


@pytest.fixture
def client():
    """Actual primary router in isolation: candidate owner-only ASGI dispatch is NOT bypassed in production."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(student_attempts.router)
    with TestClient(app) as transport:
        yield transport


def test_actual_server_keeps_existing_candidate_owner_issuance_fence():
    from fastapi.testclient import TestClient
    import server
    response = TestClient(server.app).post('/api/student-attempts/daily-set', json=credentials()|{'group':'Group I'})
    assert response.status_code == (403 if 'candidate' in server.__file__ else 200)


@pytest.mark.parametrize('answered',[9,10])
def test_legacy_retention_never_deletes_official_fingerprint_or_ranking_evidence(client,monkeypatch,answered):
    from config import settings
    from db import STUDENT_MCQ_ATTEMPTS
    monkeypatch.setattr(settings,'mcq_daily_retention',1)
    original=attempt(issue(client),count=answered)
    assert submit(client,original).status_code==200
    for i in range(3):
        legacy=attempt(issue(client));legacy.pop('officialSetId');legacy['attemptId']=f'legacy-{i}'
        assert submit(client,legacy).status_code==200
    async def saved():
        return [x async for x in get_db()[STUDENT_MCQ_ATTEMPTS].find({'studentId':'UMP0001'})]
    rows=asyncio.run(saved());assert len(rows)==2
    official=next(row for row in rows if row.get('officialSetId'))
    assert official['answers']==original['answers'] and official['responseFingerprint']
    assert official['rankingVerification']['eligible'] is (answered==10)
    conflicting=dict(original);conflicting['answers']=dict(original['answers']);conflicting['answers'][original['questionIds'][0]]=1
    assert submit(client,conflicting).status_code==409
