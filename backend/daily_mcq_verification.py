"""Server-issued Daily MCQ sets. Local candidate only; issuance is OFF by default.
The legacy client-only selection is backup data, never verified ranking evidence.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from db import CONTENT_QUESTIONS, CONTENT_RELEASES, CONTENT_SCENARIOS, STUDENT_OFFICIAL_DAILY_SETS
from group_bucket import bucket_of
from routers.student_content import _student_question

SETS = STUDENT_OFFICIAL_DAILY_SETS
IST = timezone(timedelta(hours=5, minutes=30))
POLICY = 'official-daily-full10-v1'

def now():
    return datetime.now(timezone.utc)

def subject_group(subject):
    value = str(subject or '').strip().lower()
    if re.search(r'cost|audit|financial management|strategic management|^(fm|sm)(\b|\s|&)', value):
        return 'Group II'
    if re.search(r'account|law|tax|gst|corporate', value):
        return 'Group I'
    return ''

def allowed_group(profile, group):
    # Do not treat unknown roster membership as Both.
    raw = profile.get('group') or ''
    bucket = bucket_of({'Group I': 'Group 1', 'Group II': 'Group 2'}.get(raw, raw))
    return bucket == 'Both' or bucket == {'Group I': 'Group 1', 'Group II': 'Group 2'}.get(group)

async def issue_set(db, student_id, profile, group):
    if os.environ.get('MCQ_VERIFIED_DAILY_ENABLED') != '1':
        raise HTTPException(503, 'Official Daily MCQ verification is not enabled yet')
    if group not in ('Group I', 'Group II') or not allowed_group(profile, group):
        raise HTTPException(403, 'Daily MCQ group is not established for this student')
    stamp = now(); day = stamp.astimezone(IST).date().isoformat()
    key = hashlib.sha256(f'{POLICY}:{student_id}:{day}:{group}'.encode()).hexdigest()
    existing = await db[SETS].find_one({'_id': key})
    if not existing:
        release = await db[CONTENT_RELEASES].find_one({}, sort=[('revision', -1)])
        revision = f"published-r{int((release or {}).get('revision') or 0)}"
        scenarios = {s['scenarioId']: s async for s in db[CONTENT_SCENARIOS].find({})}
        pool = []
        async for q in db[CONTENT_QUESTIONS].find({'status': 'published'}):
            opts = q.get('options') or []
            if subject_group(q.get('subject')) != group or not 2 <= len(opts) <= 4:
                continue
            if not any(o.get('id') == q.get('correctOptionId') for o in opts if isinstance(o, dict)):
                continue
            pool.append(_student_question(q, scenarios))
        # Immutable per-student/day assignment; preserve the existing 7 direct +3 case format.
        pool.sort(key=lambda q: hashlib.sha256(f'{key}:{revision}:{q["id"]}'.encode()).hexdigest())
        direct = [q for q in pool if q['kind'] != 'case-study'][:7]
        cases = [q for q in pool if q['kind'] == 'case-study'][:3]
        selected = direct + cases
        if len(selected) != 10 or len({q['id'] for q in selected}) != 10:
            raise HTTPException(409, 'The published bank cannot provide a complete official 10-question set')
        doc = {'_id': key, 'studentId': student_id, 'date': day, 'group': group,
               'bankRevision': revision, 'issuedAt': int(stamp.timestamp()*1000),
               'questionIds': [q['id'] for q in selected], 'questions': selected}
        try:
            await db[SETS].update_one({'_id': key}, {'$setOnInsert': doc}, upsert=True)
        except DuplicateKeyError:
            pass  # Concurrent issuance returns the already-fixed assignment.
        existing = await db[SETS].find_one({'_id': key})
    return {k: existing[k] for k in ('date','group','bankRevision','questionIds','questions','issuedAt')} | {'officialSetId': key}

async def verify_attempt(db, student_id, attempt):
    verdict = {'policy': POLICY, 'eligible': False, 'attempted': 0, 'correct': 0,
               'reason': 'not-official-daily'}
    if attempt.get('kind') != 'daily' or not attempt.get('officialSetId'):
        return verdict
    official = await db[SETS].find_one({'_id': attempt['officialSetId'], 'studentId': student_id})
    if not official:
        raise HTTPException(409, 'Official Daily MCQ assignment not found for this student')
    for field in ('date', 'group', 'bankRevision', 'questionIds'):
        if attempt.get(field) != official.get(field):
            raise HTTPException(409, 'Daily MCQ submission does not match its official assignment')
    answers = attempt.get('answers') or {}; questions = official['questions']
    ids = official['questionIds']
    verdict.update(day=official['date'], setId=official['_id'])
    if len(ids) != 10 or set(answers) != set(ids):
        return verdict | {'reason': 'incomplete-full10'}
    for q in questions:
        choice = answers.get(q['id'])
        if type(choice) is not int or not 0 <= choice < len(q['options']):
            raise HTTPException(422, 'Invalid response for an official Daily MCQ question')
    completed = attempt['completedAt']; started = attempt['startedAt']
    if started < official['issuedAt'] - 300000 or completed < started or completed > int(now().timestamp()*1000)+300000:
        raise HTTPException(409, 'Invalid official Daily MCQ submission time')
    try:
        completed_day = datetime.fromtimestamp(completed/1000, timezone.utc).astimezone(IST).date().isoformat()
    except (ValueError, OverflowError, OSError):
        raise HTTPException(409, 'Invalid official Daily MCQ submission time')
    if completed_day != official['date']:
        raise HTTPException(409, 'Daily MCQ completion day does not match its official assignment')
    correct = sum(answers[q['id']] == q['answer'] for q in questions)
    return verdict | {'eligible': True, 'attempted': 10, 'correct': correct, 'reason': 'verified-full10'}

def response_fingerprint(doc):
    fields = {k: doc.get(k) for k in ('officialSetId','date','group','bankRevision','questionIds','answers','startedAt','completedAt')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':')).encode()).hexdigest()
