import asyncio
import pytest
from fastapi import HTTPException
from db import get_db, STUDENT_ACCOUNTS, STUDENT_MESSAGES
from routers import mentor_workspace as ws

B1 = 'Before Result Batch 1'
B2 = 'Before Result Batch 2'


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def current(monkeypatch):
    monkeypatch.setenv("MENTOR_WORKSPACE_COMMUNICATIONS_ENABLED", "1")
    monkeypatch.setenv("MENTOR_WORKSPACE_TRANSFERS_ENABLED", "1")
    rows = [
        {'id': 'UMP0001', 'name': 'Student One', 'batch': B1, 'group': 'Group 1', 'groupKey': 'group1', 'membershipConsistent': True, 'mongoReady': True},
        {'id': 'UMP0002', 'name': 'Student Two', 'batch': B1, 'group': 'Group 2', 'groupKey': 'group2', 'membershipConsistent': True, 'mongoReady': True},
        {'id': 'UMP0003', 'name': 'Student Both', 'batch': B1, 'group': 'Both', 'groupKey': 'both', 'membershipConsistent': True, 'mongoReady': True},
    ]
    async def fake_roster():
        return [dict(r) for r in rows]
    monkeypatch.setattr(ws, 'roster', fake_roster)
    async def fake_capability():
        return True
    monkeypatch.setattr(ws, 'membership_bridge_ready', fake_capability)
    async def fake_fence(plan, row):
        r = next(r for r in rows if r['id'] == row['id'])
        return {'success':True, 'operationClosed':True, 'studentId':r['id'], 'batch':r['batch'], 'group':r['group']}
    monkeypatch.setattr(ws, 'fence_membership', fake_fence)
    import push
    monkeypatch.setattr(push, 'spawn', lambda coro: coro.close())
    for r in rows:
        run(get_db()[STUDENT_ACCOUNTS].insert_one({'studentId': r['id'], 'batch': r['batch'], 'group': r['group'], 'passwordHash': 'DO-NOT-TOUCH', 'attempt': 'Jan 2027', 'validUntil': '2027-05-31', 'hours': 97.7, 'streak': 16}))
    return rows


def review(client, headers, **kwargs):
    return client.post('/api/mentor-workspace/review', headers=headers, json=kwargs)


def commit(client, headers, pid):
    return client.post(f'/api/mentor-workspace/plans/{pid}/commit', headers=headers, json={'confirm': 'CONFIRM'})


@pytest.mark.parametrize('value,key', [('Group I','group1'),('Group II','group2'),('Both Groups','both'),('Group 1 + Group 2','both'),('', 'unknown')])
def test_group_keys(value, key):
    assert ws.group_key(value) == key


def test_new_endpoints_require_mentor(client):
    assert client.get('/api/mentor-workspace/roster').status_code in (401,403)
    assert client.post('/api/mentor-workspace/review', json={'kind':'message'}).status_code in (401,403)
    assert client.get('/api/mentor-workspace/announcements').status_code in (401,403)


def test_review_deduplicates_and_respects_exclusive_scope(client, mentor_headers, current):
    res = review(client, mentor_headers, kind='message', studentIds=['UMP0001','UMP0001'], scopes=[{'batch':B1,'group':'group1'}], text='Hi')
    assert res.status_code == 200
    assert res.json()['recipientCount'] == 1
    assert 'passwordHash' not in str(res.json())
    assert run(get_db()[STUDENT_MESSAGES].count_documents({})) == 0
    bad = review(client, mentor_headers, kind='message', studentIds=['UMP0003'], scopes=[{'batch':B1,'group':'group1'}], text='Hi')
    assert bad.status_code == 409


def test_message_commit_is_private_and_idempotent(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='message', studentIds=['UMP0001'], text='Keep this private').json()['planId']
    assert commit(client, mentor_headers, p).json()['state'] == 'completed'
    assert commit(client, mentor_headers, p).json()['state'] == 'completed'
    one = run(get_db()[STUDENT_MESSAGES].find_one({'studentId':'UMP0001'}))
    assert len(one['messages']) == 1 and one['messages'][0]['text'] == 'Keep this private'
    assert run(get_db()[STUDENT_MESSAGES].find_one({'studentId':'UMP0002'})) is None


def test_missing_confirmation_no_write(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='message', studentIds=['UMP0001'], text='Hi').json()['planId']
    assert client.post(f'/api/mentor-workspace/plans/{p}/commit', headers=mentor_headers, json={'confirm':'YES'}).status_code == 400
    assert run(get_db()[STUDENT_MESSAGES].count_documents({})) == 0


def test_stale_membership_blocks_before_commit(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='message', studentIds=['UMP0001'], text='Hi').json()['planId']
    current[0]['batch'] = B2
    assert commit(client, mentor_headers, p).status_code == 409
    assert run(get_db()[STUDENT_MESSAGES].count_documents({})) == 0


def test_group_addition_requires_recipient_rereview(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='announcement', scopes=[{'batch':B1,'group':'group1'}], text='Welcome', title='Test').json()['planId']
    current.append({**current[0], 'id':'UMP0004'})
    assert commit(client, mentor_headers, p).status_code == 409
    assert run(get_db()[ws.ANNOUNCEMENTS].count_documents({})) == 0


def test_announcement_visibility_and_no_duplicate_send(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='announcement', scopes=[{'batch':B1,'group':'group1'}], text='One only', title='Test').json()['planId']
    assert commit(client, mentor_headers, p).status_code == 200
    assert commit(client, mentor_headers, p).status_code == 200
    assert run(get_db()[ws.ANNOUNCEMENTS].count_documents({})) == 1
    assert len(run(ws.announcements_for_student(get_db(),'UMP0001'))) == 1
    assert run(ws.announcements_for_student(get_db(),'UMP0002')) == []
    assert run(ws.announcements_for_student(get_db(),'UMP0003')) == []
    # A transferred student no longer sees old-cohort announcements.
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001'},{'$set':{'batch':B2}}))
    assert run(ws.announcements_for_student(get_db(),'UMP0001')) == []


def test_transfer_preserves_unrelated_fields(client, mentor_headers, current, monkeypatch):
    calls=[]
    async def fake(sid, old, dest, operation):
        calls.append((sid, old, dest, operation))
        return {'success':True}
    monkeypatch.setattr(ws,'sheet_membership',fake)
    p=review(client,mentor_headers,kind='transfer',studentIds=['UMP0001'],destination={'batch':B2,'group':'both'}).json()['planId']
    res=commit(client,mentor_headers,p)
    assert res.status_code == 200 and res.json()['state']=='completed'
    acc=run(get_db()[STUDENT_ACCOUNTS].find_one({'studentId':'UMP0001'}))
    assert acc['batch']==B2 and acc['group']=='Both'
    assert (acc['passwordHash'],acc['hours'],acc['streak'],acc['attempt'],acc['validUntil'])==('DO-NOT-TOUCH',97.7,16,'Jan 2027','2027-05-31')
    assert len(calls)==1
    commit(client,mentor_headers,p)
    assert len(calls)==1


def test_unknown_transfer_stops_bulk_and_locks_student(client,mentor_headers,current,monkeypatch):
    calls=[]
    async def failing(sid,*args):
        calls.append(sid)
        raise HTTPException(502,'Unknown')
    monkeypatch.setattr(ws,'sheet_membership',failing)
    p=review(client,mentor_headers,kind='transfer',studentIds=['UMP0001','UMP0002'],destination={'batch':B2,'group':'both'}).json()['planId']
    res=commit(client,mentor_headers,p).json()
    assert res['state']=='partial' and len(res['outcomes'])==1
    assert calls==['UMP0001']
    assert run(get_db()[ws.LOCKS].find_one({'_id':'UMP0001'}))
    assert run(get_db()[STUDENT_ACCOUNTS].find_one({'studentId':'UMP0001'}))['batch']==B1
    commit(client,mentor_headers,p)
    assert len(calls)==1


def test_review_expires(client,mentor_headers,current):
    p=review(client,mentor_headers,kind='message',studentIds=['UMP0001'],text='Hi').json()['planId']
    run(get_db()[ws.PLANS].update_one({'_id':p},{'$set':{'expiresAt':'2000-01-01'}}))
    assert commit(client,mentor_headers,p).status_code==409


def test_unknown_group_or_missing_account_blocks_write(client,mentor_headers,current):
    current[0]['membershipConsistent']=False
    assert review(client,mentor_headers,kind='message',studentIds=['UMP0001'],text='Hi').status_code==409
    assert review(client,mentor_headers,kind='message',studentIds=['UMP5555'],text='Hi').status_code==409


def test_empty_or_noop_transfer_rejected(client,mentor_headers,current):
    assert review(client,mentor_headers,kind='transfer',studentIds=['UMP0001'],destination={'batch':B1,'group':'group1'}).status_code==400
    assert review(client,mentor_headers,kind='message',studentIds=['UMP0001'],text=' ').status_code==400


def test_new_exclusive_test_and_push_targets_match():
    from routers.student_tests import matches_target
    import push
    doc={'batch':B1,'group':'Both Groups','exclusiveGroup':True}
    for group,expected in [('Both',True),('Group 1',False),('Group 2',False),('',False)]:
        account={'batch':B1,'group':group}
        assert matches_target(doc,account)==expected
        assert push.matches_audience(doc,account)==expected
    assert not matches_target(doc,{'batch':B2,'group':'Both'})


def test_student_announcement_read_uses_backend_filter(client,mentor_headers,current):
    p=review(client,mentor_headers,kind='announcement',scopes=[{'batch':B1,'group':'group1'}],title='Private group',text='Only group1').json()['planId']
    commit(client,mentor_headers,p)
    one=client.post('/api/student-dashboard/get',json={'action':'getAnnouncements','studentId':'UMP0001'}).json()
    other=client.post('/api/student-dashboard/get',json={'action':'getAnnouncements','studentId':'UMP0002'}).json()
    assert not one.get('result') and not other.get('result')
    private = run(ws.announcements_for_student(get_db(), 'UMP0001'))
    assert len(private) == 1
    assert 'recipientIds' not in private[0] and 'workspaceTargets' not in private[0]


def test_roster_sanitizes_raw_sheet_and_fails_on_duplicate(monkeypatch):
    async def sheet():
        return [['Student ID','Student Name','Batch','Group','Password'],['UMP0001','One',B1,'Both','NEVER_RETURN']]
    monkeypatch.setattr(ws,'_sheet_students_rows',sheet)
    run(get_db()[STUDENT_ACCOUNTS].insert_one({'studentId':'UMP0001','batch':B1,'group':'Both','passwordHash':'NEVER_RETURN'}))
    rows=run(ws.roster())
    assert rows[0]['membershipConsistent'] and rows[0]['groupKey']=='both'
    assert 'NEVER_RETURN' not in str(rows)
    async def duplicate():
        r=await sheet()
        return r+[r[1]]
    monkeypatch.setattr(ws,'_sheet_students_rows',duplicate)
    with pytest.raises(HTTPException) as exc:
        run(ws.roster())
    assert exc.value.status_code==503


def test_missing_bridge_blocks_review_before_plan_saved(client,mentor_headers,current,monkeypatch):
    async def unavailable():
        raise HTTPException(503,'Bridge unavailable')
    monkeypatch.setattr(ws,'membership_bridge_ready',unavailable)
    res=review(client,mentor_headers,kind='transfer',studentIds=['UMP0001'],destination={'batch':B2,'group':'both'})
    assert res.status_code==503
    assert run(get_db()[ws.PLANS].count_documents({}))==0
    assert run(get_db()[ws.LOCKS].count_documents({}))==0


def test_explicit_reconciliation_releases_only_consistent_old_membership(client,mentor_headers,current,monkeypatch):
    async def unknown(*args):
        raise HTTPException(502,'Unknown')
    monkeypatch.setattr(ws,'sheet_membership',unknown)
    p=review(client,mentor_headers,kind='transfer',studentIds=['UMP0001'],destination={'batch':B2,'group':'both'}).json()['planId']
    commit(client,mentor_headers,p)
    assert run(get_db()[ws.LOCKS].count_documents({}))==1
    res=client.post(f'/api/mentor-workspace/plans/{p}/reconcile',headers=mentor_headers,json={'confirm':'RECONCILE'})
    assert res.json()['state']=='reconciled'
    assert res.json()['outcomes'][0]['state']=='not_applied'
    assert run(get_db()[ws.LOCKS].count_documents({}))==0


def test_reconciliation_never_repairs_mixed_membership(client,mentor_headers,current,monkeypatch):
    async def unknown(*args):
        raise HTTPException(502,'Unknown')
    monkeypatch.setattr(ws,'sheet_membership',unknown)
    p=review(client,mentor_headers,kind='transfer',studentIds=['UMP0001'],destination={'batch':B2,'group':'both'}).json()['planId']
    commit(client,mentor_headers,p)
    current[0]['membershipConsistent']=False
    res=client.post(f'/api/mentor-workspace/plans/{p}/reconcile',headers=mentor_headers,json={'confirm':'RECONCILE'})
    assert res.json()['state']=='needs_reconciliation'
    assert run(get_db()[ws.LOCKS].count_documents({}))==1
    assert run(get_db()[STUDENT_ACCOUNTS].find_one({'studentId':'UMP0001'}))['batch']==B1


def test_plan_is_bound_to_mentor(client,mentor_headers,current,monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "mentor_accounts", "other-mentor@test.local:synthetic-not-used")
    from auth import create_token
    p=review(client,mentor_headers,kind='message',studentIds=['UMP0001'],text='Private').json()['planId']
    other={'Authorization':'Bearer '+create_token('other-mentor@test.local')}
    assert client.get(f'/api/mentor-workspace/plans/{p}',headers=other).status_code==404
    assert commit(client,other,p).status_code==404


def test_cached_materials_respect_current_destination_without_deleting_history(client,mentor_headers,current):
    from db import DASHBOARD_STUDENTS
    cached=[{'id':'old','title':'Old','audience':B1,'group':'Both Groups'},{'id':'new','title':'New','audience':B2,'group':'Both Groups'}]
    run(get_db()[DASHBOARD_STUDENTS].insert_one({'studentId':'UMP0001','notes':cached,'studyLog':[{'id':'keep'}]}))
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001'},{'$set':{'batch':B2,'group':'Both'}}))
    denied=client.post('/api/student-dashboard/get',json={'action':'notes.listForStudent','studentId':'UMP0001'})
    assert denied.status_code==401
    student_proof(client)  # establish a real synthetic hashed credential
    unavailable=client.post('/api/student-dashboard/get',headers={'X-Student-Id':'UMP0001','X-Session-Password':'synthetic-local-only'},json={'action':'notes.listForStudent','studentId':'UMP0001'})
    # 200 + the safe projection (a business rule never answers 5xx). The student
    # is in B2 now, so only the B2 material is visible - the stale B1 material
    # must not be served, and the stored history must stay untouched.
    assert unavailable.status_code==200
    served=unavailable.json()['result']
    assert [n['id'] for n in served]==['new'], served
    saved=run(get_db()[DASHBOARD_STUDENTS].find_one({'studentId':'UMP0001'}))
    assert saved['notes']==cached and saved['studyLog']==[{'id':'keep'}]


def student_proof(client, sid='UMP0001', password='synthetic-local-only'):
    from auth import hash_password
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId': sid}, {'$set': {'passwordHash': hash_password(password)}}))
    response = client.post('/api/mentor-workspace/student/session', json={'studentId':sid, 'password':password})
    assert response.status_code == 200, response.text
    return {'X-Workspace-Token': response.json()['token']}


def test_private_workspace_reader_requires_credential_proof(client, current):
    for section in ('messages', 'announcements'):
        assert client.get('/api/mentor-workspace/student/' + section).status_code == 401
        assert client.get('/api/mentor-workspace/student/' + section, headers={'X-Workspace-Token':'not-a-token'}).status_code == 401
    assert client.post('/api/mentor-workspace/student/session', json={'studentId':'UMP0001','password':'wrong'}).status_code == 401
    assert client.post('/api/mentor-workspace/student/session', json={'studentId':'UMP9999','password':'wrong'}).status_code == 401


def test_workspace_messages_hidden_from_id_only_legacy_reader(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='message', studentIds=['UMP0001'], text='Private new inbox message').json()['planId']
    commit(client, mentor_headers, p)
    assert client.get('/api/messages/thread?studentId=UMP0001').status_code == 401
    proof = student_proof(client)
    own = client.get('/api/mentor-workspace/student/messages', headers=proof).json()
    assert own['studentId'] == 'UMP0001' and own['messages'][0]['text'] == 'Private new inbox message'
    other = student_proof(client, 'UMP0002')
    assert client.get('/api/mentor-workspace/student/messages?studentId=UMP0001', headers=other).json()['messages'] == []


def test_workspace_proof_cannot_be_used_as_mentor_and_revokes_on_password_reset(client, current):
    proof = student_proof(client)
    assert client.get('/api/mentor-workspace/roster', headers={'Authorization':'Bearer ' + proof['X-Workspace-Token']}).status_code == 403
    assert client.get('/api/mentor-workspace/student/messages', headers=proof).status_code == 200
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001'}, {'$set': {'passwordHash':'new-password-binding'}}))
    assert client.get('/api/mentor-workspace/student/messages', headers=proof).status_code == 401


@pytest.mark.parametrize('change', [{'removedAt':'2026-01-01'}, {'accessEnabled':False}])
def test_workspace_proof_respects_removed_and_disabled_accounts(client, current, change):
    proof = student_proof(client)
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001'}, {'$set': change}))
    assert client.get('/api/mentor-workspace/student/messages', headers=proof).status_code == 401
    assert client.post('/api/mentor-workspace/student/session', json={'studentId':'UMP0001','password':'synthetic-local-only'}).status_code == 401


def test_workspace_announcements_require_proof_and_keep_recipient_lists_private(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='announcement', scopes=[{'batch':B1,'group':'group1'}], title='Group One', text='Private notice').json()['planId']
    commit(client, mentor_headers, p)
    legacy = client.post('/api/student-dashboard/get', json={'action':'getAnnouncements','studentId':'UMP0001'}).json()
    assert not legacy.get('result')
    own = client.get('/api/mentor-workspace/student/announcements', headers=student_proof(client)).json()['announcements']
    assert len(own) == 1 and own[0]['title'] == 'Group One'
    assert 'recipientIds' not in own[0] and 'workspaceTargets' not in own[0]
    other = client.get('/api/mentor-workspace/student/announcements', headers=student_proof(client, 'UMP0002')).json()['announcements']
    assert other == []
    run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001'}, {'$set': {'group':'Group 2'}}))
    assert client.get('/api/mentor-workspace/student/announcements', headers=student_proof(client)).json()['announcements'] == []


def test_workspace_session_throttle_is_bounded_per_account(client, current):
    from datetime import datetime, timezone
    run(get_db()['workspace_session_limits'].insert_one({'_id':'UMP0001','bucket':datetime.now(timezone.utc).strftime('%Y%m%d%H%M'),'attempts':20}))
    assert client.post('/api/mentor-workspace/student/session', json={'studentId':'UMP0001','password':'wrong'}).status_code == 429
    assert run(get_db()['workspace_session_limits'].count_documents({})) == 1


def test_failed_sheet_fence_retains_membership_lock(client, mentor_headers, current, monkeypatch):
    async def unknown(*args):
        raise HTTPException(502, 'Unknown')
    async def busy(*args):
        raise HTTPException(503, 'Bridge is busy')
    monkeypatch.setattr(ws, 'sheet_membership', unknown)
    monkeypatch.setattr(ws, 'fence_membership', busy)
    p = review(client, mentor_headers, kind='transfer', studentIds=['UMP0001'], destination={'batch':B2,'group':'both'}).json()['planId']
    commit(client, mentor_headers, p)
    assert client.post(f'/api/mentor-workspace/plans/{p}/reconcile', headers=mentor_headers, json={'confirm':'RECONCILE'}).status_code == 503
    assert run(get_db()[ws.LOCKS].count_documents({})) == 1


def test_reconciliation_fences_a_delayed_mongo_compare_and_set(client, mentor_headers, current, monkeypatch):
    async def unknown(*args):
        raise HTTPException(502, 'Unknown')
    monkeypatch.setattr(ws, 'sheet_membership', unknown)
    p = review(client, mentor_headers, kind='transfer', studentIds=['UMP0001'], destination={'batch':B2,'group':'both'}).json()['planId']
    commit(client, mentor_headers, p)
    res = client.post(f'/api/mentor-workspace/plans/{p}/reconcile', headers=mentor_headers, json={'confirm':'RECONCILE'})
    assert res.json()['state'] == 'reconciled'
    late = run(get_db()[STUDENT_ACCOUNTS].update_one({'studentId':'UMP0001','batch':B1,'group':'Group 1','membershipVersion':None}, {'$set':{'batch':B2,'group':'Both'}}))
    assert late.matched_count == 0
    assert run(get_db()[STUDENT_ACCOUNTS].find_one({'studentId':'UMP0001'}))['batch'] == B1


def test_exclusive_test_validation_rejects_unscoped_and_unknown_groups():
    from routers.mentor_tests import validate_exclusive_audience
    assert validate_exclusive_audience({'exclusiveGroup':True,'batch':'All Batches','group':'Both'})
    assert validate_exclusive_audience({'exclusiveGroup':True,'batch':B1,'group':'unknown'})
    assert validate_exclusive_audience({'exclusiveGroup':True,'batch':B1,'group':'Both'}) is None
    assert validate_exclusive_audience({'exclusiveGroup':False,'batch':'All Batches','group':'Both'}) is None


def test_workspace_announcement_pin_and_deletion_preserve_global_admin_actions(client, mentor_headers, current):
    p = review(client, mentor_headers, kind='announcement', scopes=[{'batch':B1,'group':'group1'}], title='Pin test', text='Notice').json()['planId']
    commit(client, mentor_headers, p)
    aid = 'WS-' + p
    assert client.post(f'/api/mentor-workspace/announcements/{aid}/pin').status_code == 401
    assert client.post(f'/api/mentor-workspace/announcements/{aid}/pin', headers=mentor_headers).json()['pinned'] is True
    assert client.get('/api/mentor-workspace/announcements', headers=mentor_headers).json()['announcements'][0]['pinned'] is True
    client.delete('/api/student-dashboard/announcements/' + aid, headers=mentor_headers)
    assert client.get('/api/mentor-workspace/announcements', headers=mentor_headers).json()['announcements'] == []
    assert client.post(f'/api/mentor-workspace/announcements/{aid}/pin', headers=mentor_headers).status_code == 404
    assert client.get('/api/mentor-workspace/student/announcements', headers=student_proof(client)).json()['announcements'] == []


def test_mentor_only_release_blocks_new_communication_review_and_stale_commit(client, mentor_headers, current, monkeypatch):
    p = review(client, mentor_headers, kind='message', studentIds=['UMP0001'], text='Not released').json()['planId']
    monkeypatch.delenv('MENTOR_WORKSPACE_COMMUNICATIONS_ENABLED', raising=False)
    for kind in ('message', 'announcement'):
        res = review(client, mentor_headers, kind=kind, studentIds=['UMP0001'], text='Must not send', title='Hold')
        assert res.status_code == 503
    assert commit(client, mentor_headers, p).status_code == 503
    assert run(get_db()[STUDENT_MESSAGES].count_documents({})) == 0
    assert run(get_db()[ws.ANNOUNCEMENTS].count_documents({})) == 0
    assert run(get_db()[ws.PLANS].count_documents({})) == 1


def test_mentor_only_transfer_gate_never_probes_an_unverified_legacy_script(client, mentor_headers, current, monkeypatch):
    async def forbidden():
        raise AssertionError('Must not probe a legacy script before bridge approval')
    monkeypatch.setattr(ws, 'membership_bridge_ready', forbidden)
    monkeypatch.delenv('MENTOR_WORKSPACE_TRANSFERS_ENABLED', raising=False)
    response = review(client, mentor_headers, kind='transfer', studentIds=['UMP0001'], destination={'batch':B2,'group':'both'})
    assert response.status_code == 503
    assert run(get_db()[ws.PLANS].count_documents({})) == 0
    assert run(get_db()[ws.LOCKS].count_documents({})) == 0
