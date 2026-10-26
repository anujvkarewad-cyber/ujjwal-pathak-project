"""Authenticated personal targets, atomic progress and shared revision summaries.

No Sheets mutations or receipt/audio storage. Mongo _id + version CAS provides
cross-worker safety; local locks and device clocks are not authoritative.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo.errors import DuplicateKeyError

from auth import require_mentor
from db import get_db, STUDENT_ACCOUNTS
from routers.daily_targets import _audience_matches
from routers.student_auth import authenticate_student, normalize_student_id, _sheet_students_rows
from routers.student_attempts import _validate_existing_student_login
from routers.revision_schedule import PLAN as REVISIONS, _public, _today, _now, record_written_mark
from routers.smart_target_engine import snapshot, view, complete_task

router = APIRouter(prefix='/api/smart-targets', tags=['smart-targets'])
PROGRESS = 'target_progress'
PLANS = 'target_plans'


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    studentId: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class SessionRequest(Login):
    sessionId: str = Field(min_length=8, max_length=96)


class PlanRequest(Login):
    planId: str = Field(min_length=3, max_length=80)


class CompleteRequest(PlanRequest):
    taskId: str = Field(min_length=3, max_length=120)


class ExtensionRequest(PlanRequest):
    requestId: str = Field(min_length=8, max_length=96)
    days: int = Field(ge=1, le=60)
    reason: str = Field(min_length=3, max_length=300)


class ExtensionDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    studentId: str = Field(min_length=3, max_length=32)
    requestId: str = Field(min_length=8, max_length=96)
    decision: Literal['approved', 'rejected']
    days: int = Field(default=1, ge=1, le=60)
    note: str = Field(default='', max_length=300)


class Assessment(Login):
    eventId: str = Field(min_length=8, max_length=128)
    sessionId: str = Field(min_length=8, max_length=96)
    planId: str = Field(default='', max_length=80)
    taskId: str = Field(default='', max_length=120)
    revisionKey: str = Field(default='', max_length=260)
    revisionVersion: int = Field(default=0, ge=0)
    attempted: int = Field(ge=1, le=1000)
    correct: int = Field(ge=0, le=1000)
    durationSeconds: int = Field(ge=1, le=86400)
    confidence: Literal['Low', 'Medium', 'High'] = 'Medium'
    shareSummary: Literal[True]

    @model_validator(mode='after')
    def validate_link(self):
        if self.correct > self.attempted:
            raise ValueError('Correct answers cannot exceed attempted questions.')
        if bool(self.revisionKey) == bool(self.planId and self.taskId):
            raise ValueError('Link exactly one current target OR revision.')
        return self


async def _student(body):
    sid = normalize_student_id(body.studentId)
    # Never fall back around an existing disabled/removed/closed/wrong-password
    # Mongo account. Apps Script fallback is only for a not-yet-imported ID.
    result = await authenticate_student(sid, body.password)
    if result.get('success') is not True:
        if result.get('code') != 'not_found':
            raise HTTPException(403 if result.get('code') in ('removed', 'access_blocked', 'group_closed') else 401,
                                result.get('message') or 'Login required.')
        result = await _validate_existing_student_login(sid, body.password)
    if normalize_student_id(result.get('studentId', sid)) != sid:
        raise HTTPException(401, 'Student identity mismatch.')
    return sid, result


async def _authoritative_students():
    """Fresh bounded Students read, using the existing protected Sheet reader.

    Fail closed on missing/duplicate/truncated roster; never auto-repair account
    membership. Revisions use student auth independently of this availability.
    """
    from routers.daily_targets import _group_key
    raw = await _sheet_students_rows()
    if not raw or len(raw) >= 400:
        raise HTTPException(503, 'Students roster unavailable or bounded read limit reached. No target change allowed.')
    header = [str(v).strip().lower() for v in raw[0]]
    def col(*names):
        return next((header.index(n) for n in names if n in header), None)
    si, bi, gi = col('student id', 'studentid', 'id'), col('batch'), col('group', 'groups')
    ai, ni = col('attempt'), col('student name', 'name')
    if any(i is None for i in (si, bi, gi)):
        raise HTTPException(503, 'Students roster is missing a required membership column.')
    projection = {k: 1 for k in ('studentId', 'studentName', 'batch', 'group', 'attempt', 'removedAt', 'status', 'accessEnabled')}
    accounts = {r['studentId']: r async for r in get_db()[STUDENT_ACCOUNTS].find({}, projection)}
    locked = {r['_id'] async for r in get_db()['mentor_workspace_membership_locks'].find({}, {'_id': 1})}
    result, seen = [], set()
    for row in raw[1:]:
        def cell(i): return str(row[i] or '').strip() if i is not None and i < len(row) else ''
        sid = normalize_student_id(cell(si))
        if not sid:
            continue
        if sid in seen:
            raise HTTPException(503, 'Duplicate Student IDs in Students roster. Resolve before target changes.')
        seen.add(sid)
        account = accounts.get(sid, {})
        if account.get('removedAt') or str(account.get('status', '')).lower() == 'removed':
            continue
        batch, group = cell(bi), cell(gi)
        ready = bool(account and sid not in locked and batch == account.get('batch') and
                     _group_key(group) in {'g1', 'g2', 'both'} and _group_key(group) == _group_key(account.get('group')))
        result.append({'studentId': sid, 'studentName': cell(ni) or account.get('studentName') or sid,
                       'batch': batch, 'group': group, 'attempt': cell(ai) if ai is not None else account.get('attempt', ''),
                       'membershipConsistent': ready, 'accessEnabled': account.get('accessEnabled') is not False})
    return result


def _membership(rows, sid):
    row = next((r for r in rows if r['studentId'] == sid), None)
    if not row:
        raise HTTPException(403, 'Your ID is not in the current Students roster.')
    if not row['membershipConsistent']:
        raise HTTPException(409, 'Enrollment and app membership must agree before target changes. No automatic repair.')
    return row


async def _plan(sid, profile, plan_id):
    plan = await get_db()[PLANS].find_one({'id': plan_id, 'mode': 'personal'})
    if not plan:
        raise HTTPException(404, 'Personal plan not found.')
    membership = _membership(await _authoritative_students(), sid)
    if not _audience_matches(membership, plan):
        raise HTTPException(403, 'This plan is not assigned to your current batch/group/attempt.')
    return plan


async def _state(sid, plan_id):
    state = await get_db()[PROGRESS].find_one({'_id': f'{sid}:{plan_id}'})
    if not state:
        raise HTTPException(409, 'Start My Targets first.')
    return state


async def _mutate(sid, plan_id, fn):
    for _ in range(8):
        old = await _state(sid, plan_id)
        new = fn(deepcopy(old))
        if new == old:
            return old
        new['version'] = old['version'] + 1
        new['updatedAt'] = _now()
        changes = {k: v for k, v in new.items() if k != '_id'}
        result = await get_db()[PROGRESS].update_one({'_id': old['_id'], 'version': old['version']}, {'$set': changes})
        if result.matched_count:
            return new
    raise HTTPException(409, 'Progress changed on another device. Refresh and retry.')


async def _revision_view(sid, budget=30):
    # Unlike the legacy 40-row endpoint, return every due chapter. Workload
    # suggestions never hide/defer/reschedule additional overdue revisions.
    rows = await get_db()[REVISIONS].find({'studentId': sid}).sort('dueOn', 1).to_list(None)
    chapters = [_public(r) for r in rows]
    due = [r for r in chapters if r['dueOn'] and r['dueOn'] <= _today().isoformat()]
    due.sort(key=lambda r: (r['dueOn'], r['accuracy'], r['concept']))
    for i, row in enumerate(due):
        row['suggestedToday'] = i < max(1, budget//15)
        row['estimatedMinutes'] = min(15, budget)
    return {'chapters': chapters, 'due': due, 'budgetMinutes': budget,
            'suggestedMinutes': min(len(due), max(1, budget//15))*min(15, budget),
            'additionalDueCount': max(0, len(due)-max(1, budget//15))}


@router.post('/student/dashboard')
async def dashboard(body: Login):
    sid, profile = await _student(body)
    plans = await get_db()[PLANS].find({'mode': 'personal', 'status': 'active'}).to_list(None)
    access_error = ''
    try:
        membership = _membership(await _authoritative_students(), sid)
        assigned = [p for p in plans if _audience_matches(membership, p)]
    except HTTPException as exc:
        assigned = []
        access_error = str(exc.detail)
    states = await get_db()[PROGRESS].find({'studentId': sid}).to_list(None)
    by_id = {s['planId']: s for s in states}
    cards = []
    for p in assigned:
        state = by_id.get(p['id'])
        cards.append({'planId': p['id'], 'name': p['name'], 'startAvailableOn': p['startDate'],
                      'includedBackupDays': p.get('includedBackupDays', 0), 'totalDays': len(p['days']),
                      'progress': view(state, _today()) if state else None})
    # Read-only history survives cancellation/transfer, without reopening old
    # batch materials or allowing further mutations after audience changes.
    historical = [dict(view(s, _today()), readOnly=True) for s in states if s['planId'] not in {p['id'] for p in assigned}]
    assigned_ids = {p['id'] for p in assigned}
    budget = min([s.get('revisionBudgetMinutes', 30) for s in states
                  if s['planId'] in assigned_ids and not all(d.get('completedOn') for d in s['days'])] or [30])
    return {'studentId': sid, 'today': _today().isoformat(), 'plans': cards,
            'history': historical, 'targetAccessError': access_error, 'revisions': await _revision_view(sid, budget)}


@router.post('/student/session')
async def session_summary(body: SessionRequest):
    sid, _ = await _student(body)
    saved = await get_db()['focus_sessions'].find_one({'_id': sid + ':' + body.sessionId})
    if not saved:
        return {'summary': None}
    return {'summary': {k: saved.get(k) for k in ('sessionId', 'concept', 'subject', 'attempted', 'correct', 'confidence', 'status', 'assessment')}}


@router.post('/student/start')
async def start(body: PlanRequest):
    sid, profile = await _student(body)
    p = await _plan(sid, profile, body.planId)
    existing = await get_db()[PROGRESS].find_one({'_id': f'{sid}:{body.planId}'})
    if existing:
        return {'progress': view(existing, _today())}
    if p.get('status') != 'active' or p['startDate'] > _today().isoformat():
        raise HTTPException(409, 'This plan is not open for starting yet.')
    state = snapshot(p, sid, _today(), _now())
    try:
        await get_db()[PROGRESS].insert_one(state)
    except DuplicateKeyError:
        state = await _state(sid, body.planId)
    return {'progress': view(state, _today())}


async def _active_plan(sid, profile, plan_id):
    p = await _plan(sid, profile, plan_id)
    if p.get('status') != 'active':
        raise HTTPException(409, 'This plan is cancelled. Saved progress is read-only.')
    return p


@router.post('/student/complete')
async def complete(body: CompleteRequest):
    sid, profile = await _student(body)
    await _active_plan(sid, profile, body.planId)
    state = await _mutate(sid, body.planId, lambda s: complete_task(s, body.taskId, _today(), _now()))
    return {'progress': view(state, _today())}


@router.post('/student/extension')
async def request_extension(body: ExtensionRequest):
    sid, profile = await _student(body)
    await _active_plan(sid, profile, body.planId)
    def change(s):
        for e in s['extensions']:
            if e['id'] == body.requestId:
                if e['requestedDays'] != body.days or e['reason'] != body.reason:
                    raise HTTPException(409, 'This request ID already has different details.')
                return s
        if view(s, _today())['complete']:
            raise HTTPException(409, 'This plan is already complete.')
        if any(e['status'] == 'pending' for e in s['extensions']):
            raise HTTPException(409, 'An extension request is already pending.')
        s['extensions'].append({'id': body.requestId, 'requestedDays': body.days,
                               'reason': body.reason, 'status': 'pending', 'requestedAt': _now()})
        return s
    state = await _mutate(sid, body.planId, change)
    return {'progress': view(state, _today())}


@router.post('/mentor/{plan_id}/extension')
async def decide_extension(plan_id: str, body: ExtensionDecision, mentor=Depends(require_mentor)):
    sid = normalize_student_id(body.studentId)
    p = await get_db()[PLANS].find_one({'id': plan_id, 'mode': 'personal', 'status': 'active'})
    if not p:
        raise HTTPException(409, 'Personal plan is not active.')
    if body.decision == 'approved':
        member = _membership(await _authoritative_students(), sid)
        if not _audience_matches(member, p):
            raise HTTPException(409, 'Student is no longer in this plan audience.')
    def change(s):
        e = next((x for x in s['extensions'] if x['id'] == body.requestId), None)
        if not e:
            raise HTTPException(404, 'Extension request not found.')
        if e['status'] != 'pending':
            if e['status'] != body.decision or (body.decision == 'approved' and e['approvedDays'] != body.days):
                raise HTTPException(409, 'This request already has an immutable decision.')
            return s
        e.update(status=body.decision, approvedDays=body.days if body.decision == 'approved' else 0,
                 note=body.note, decidedAt=_now(), decidedBy=mentor.get('sub') or 'mentor')
        return s
    return {'progress': view(await _mutate(sid, plan_id, change), _today())}


class AudienceRequest(BaseModel):
    attempt: str = Field(default='All', max_length=80)
    group: str = Field(default='All', max_length=80)
    batch: str = Field(default='All', max_length=80)


@router.post('/mentor/audience')
async def audience_preview(body: AudienceRequest, _mentor=Depends(require_mentor)):
    rows = [r for r in await _authoritative_students() if _audience_matches(r, body.model_dump())]
    return {'count': len(rows), 'readyCount': sum(r['membershipConsistent'] for r in rows),
            'names': [r['studentName'] for r in rows[:8]], 'source': 'Students Sheet'}


@router.get('/mentor/{plan_id}')
async def mentor_dashboard(plan_id: str, _mentor=Depends(require_mentor)):
    p = await get_db()[PLANS].find_one({'id': plan_id, 'mode': 'personal'})
    if not p:
        raise HTTPException(404, 'Personal plan not found.')
    profiles = await _authoritative_students()
    states = await get_db()[PROGRESS].find({'planId': plan_id}).to_list(None)
    by_sid = {s['studentId']: s for s in states}
    roster = {s['studentId']: s for s in profiles if _audience_matches(s, p)}
    all_profiles = {s['studentId']: s for s in profiles}
    # Keep departed/cancelled progress visible as read-only history, not as
    # active batch members. No guessed names or fabricated zero mastery.
    rows = []
    for sid in sorted(set(roster) | set(by_sid)):
        profile = all_profiles.get(sid, {})
        state = by_sid.get(sid)
        revisions = await _revision_view(sid, p.get('revisionBudgetMinutes', 30))
        rows.append({'studentId': sid, 'studentName': profile.get('studentName') or '',
                     'inAudience': sid in roster, 'membershipReady': profile.get('membershipConsistent', False), 'progress': view(state, _today()) if state else None,
                     'chapters': revisions['chapters'], 'dueRevisions': revisions['due']})
    return {'planId': plan_id, 'today': _today().isoformat(), 'students': rows,
            'started': len(states), 'notStarted': sum(r['progress'] is None for r in rows),
            'fallingBehind': sum(bool(r['progress'] and not r['progress']['complete'] and r['progress']['overdueDays']) for r in rows),
            'pendingRequests': sum(e['status'] == 'pending' for s in states for e in s['extensions'])}


@router.post('/student/assessment')
async def assessment(body: Assessment):
    sid, profile = await _student(body)
    # Use a server-derived idempotency key; one focus session cannot be counted
    # repeatedly by changing the client eventId. Payload changes return 409.
    event_id = 'focus:' + body.sessionId
    meta = {'source': 'student-reported-question-score', 'kind': 'target' if body.planId else 'revision',
            'sessionId': body.sessionId, 'durationSeconds': body.durationSeconds,
            'planId': body.planId, 'taskId': body.taskId}
    import json
    fingerprint = sha256(json.dumps(body.model_dump(exclude={'password', 'eventId', 'studentId'}), sort_keys=True).encode()).hexdigest()
    sessions = get_db()['focus_sessions']
    session_key = sid + ':' + body.sessionId
    saved = await sessions.find_one({'_id': session_key})
    if saved and saved['fingerprint'] != fingerprint:
        raise HTTPException(409, 'This focus session already has a different chapter/score summary.')
    if saved and saved['status'] == 'complete':
        return {'assessment': dict(saved['assessment'], alreadyRecorded=True)}
    if not saved:
        if body.planId:
            await _active_plan(sid, profile, body.planId)
            state = await _state(sid, body.planId)
            day = next((d for d in state['days'] if any(t['id'] == body.taskId for t in d['tasks'])), None)
            if not day:
                raise HTTPException(404, 'Target not found in your plan snapshot.')
            status = view(state, _today())
            # A completion followed by a delayed retry is allowed. Future chapter
            # marks cannot be used to bypass the target sequence.
            if body.taskId not in day['completions'] and (day['day'] != status['currentDay'] or not status['canWork']):
                raise HTTPException(409, 'Future/blocked target assessments are locked.')
            task = next(t for t in day['tasks'] if t['id'] == body.taskId)
            concept, subject, expected = task['topic'], task['subject'], None
        else:
            row = await get_db()[REVISIONS].find_one({'studentId': sid, 'conceptKey': body.revisionKey})
            if not row:
                raise HTTPException(404, 'Revision not found.')
            event_key = sha256(event_id.encode()).hexdigest()
            if row.get('dueOn', '') > _today().isoformat() and event_key not in row.get('assessmentEvents', {}):
                raise HTTPException(409, 'This revision is not due yet.')
            concept, subject, expected = row['concept'], row.get('subject', ''), body.revisionVersion
            meta['revisionKey'] = body.revisionKey
        saved = {'_id': session_key, 'studentId': sid, 'sessionId': body.sessionId,
                 'fingerprint': fingerprint, 'status': 'pending', 'concept': concept,
                 'subject': subject, 'expectedVersion': expected, 'meta': meta,
                 'attempted': body.attempted, 'correct': body.correct, 'confidence': body.confidence, 'acceptedAt': _now()}
        try:
            await sessions.insert_one(saved)
        except DuplicateKeyError:
            saved = await sessions.find_one({'_id': session_key})
            if saved['fingerprint'] != fingerprint:
                raise HTTPException(409, 'This session was saved concurrently with different details.')
    concept, subject, expected, meta = saved['concept'], saved['subject'], saved['expectedVersion'], saved['meta']
    result = await record_written_mark(student_id=sid, concept=concept, subject=subject,
        score=10*body.correct/body.attempted, confidence=body.confidence,
        event_id=event_id, question_attempted=body.attempted, question_correct=body.correct,
        event_meta=meta, expected_version=expected)
    # Assessment and completion intentionally remain separate: no timer or
    # question score can silently tick an unfinished mandatory target.
    await sessions.update_one({'_id': session_key}, {'$set': {'status': 'complete', 'assessment': result, 'completedAt': _now()}})
    return {'assessment': result}
