"""Objective workbook formats. Approved keys/marks only; no provider or DB I/O.

This belongs to the local, disabled workbook prototype, NOT the live backend.
Do not infer keys, aliases or questionwise marks from a chapter weightage table.
"""
import json
import math
import re
import unicodedata

FORMATS = {'written', 'mcq', 'blanks', 'matching'}


def _text(value, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid objective text')
    return value.strip()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', value):
        raise ValueError('Invalid objective ID')
    return value


def _items(value, minimum=1):
    if not isinstance(value, list) or not minimum <= len(value) <= 20:
        raise ValueError('Invalid objective items')
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'id', 'text'}:
            raise ValueError('Invalid objective item fields')
        key = _id(item['id'])
        if key in seen:
            raise ValueError('Duplicate objective ID')
        seen.add(key)
        _text(item['text'])
    return seen


def _normal(value):
    # Only case/Unicode/whitespace normalization. Never strip negation or guess synonyms.
    return ' '.join(unicodedata.normalize('NFKC', _text(value)).casefold().split())


def validate_objective(question):
    fmt = question.get('format', 'written')
    if fmt not in FORMATS:
        raise ValueError('Unsupported workbook format')
    objective = question.get('objective')
    if fmt == 'written':
        if objective is not None:
            raise ValueError('Written question cannot contain objective keys')
        return
    if not isinstance(objective, dict):
        raise ValueError('Approved objective key is required')
    rubric = question.get('rubric', [])
    if not isinstance(rubric, list) or not 1 <= len(rubric) <= 20:
        raise ValueError('Approved questionwise rubric is required')
    ids = set()
    for point in rubric:
        key = _id(point['id'])
        mark = point['marks']
        if key in ids or isinstance(mark, bool) or not isinstance(mark, (int, float)) or not math.isfinite(mark) or not 0 < mark <= 20:
            raise ValueError('Invalid objective marks')
        ids.add(key)
    maximum = question.get('maxMarks')
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or not 0 < maximum <= 100 or abs(sum(p['marks'] for p in rubric) - maximum) > .001:
        raise ValueError('Objective marks must match the approved maximum')
    if fmt == 'mcq':
        if set(objective) != {'options', 'correctOptionId'} or len(rubric) != 1:
            raise ValueError('MCQ requires one approved scoring point and a key')
        options = _items(objective['options'], minimum=2)
        if _id(objective['correctOptionId']) not in options:
            raise ValueError('MCQ key is not an option')
    elif fmt == 'blanks':
        if set(objective) != {'slots'} or not isinstance(objective['slots'], list) or not 1 <= len(objective['slots']) <= 20:
            raise ValueError('Invalid blank slots')
        slots = objective['slots']
        if any(not isinstance(s, dict) or set(s) != {'id', 'text', 'acceptedAnswers'} for s in slots):
            raise ValueError('Invalid blank fields')
        slot_ids = _items([{'id': s['id'], 'text': s['text']} for s in slots])
        if slot_ids != ids:
            raise ValueError('Blank IDs must match approved rubric points')
        for slot in slots:
            aliases = slot['acceptedAnswers']
            if not isinstance(aliases, list) or not 1 <= len(aliases) <= 8:
                raise ValueError('Approved blank answer required')
            normalized = [_normal(a) for a in aliases]
            if len(set(normalized)) != len(normalized):
                raise ValueError('Duplicate blank aliases')
    else:
        if set(objective) != {'left', 'right', 'matches'}:
            raise ValueError('Invalid matching fields')
        left, right = _items(objective['left'], 2), _items(objective['right'], 2)
        matches = objective['matches']
        if left != ids or not isinstance(matches, dict) or set(matches) != left or len(left) != len(right):
            raise ValueError('Matching requires approved marks for every left item')
        if any(not isinstance(v, str) for v in matches.values()) or set(matches.values()) != right:
            raise ValueError('Approved matching key must be one-to-one')


def public_format(question):
    validate_objective(question)
    fmt = question.get('format', 'written')
    if fmt == 'written':
        return {'format': fmt}
    source = question['objective']
    if fmt == 'mcq':
        public = {'options': source['options']}
    elif fmt == 'blanks':
        public = {'slots': [{'id': s['id'], 'text': s['text']} for s in source['slots']]}
    else:
        public = {'left': source['left'], 'right': source['right']}
    return {'format': fmt, 'objective': public}


def grade_objective(question, answer):
    validate_objective(question)
    fmt = question.get('format', 'written')
    if fmt == 'written':
        raise ValueError('Written answers require the existing reviewed evaluator')
    if question.get('sourceVerified') is not True:
        raise ValueError('The objective key has not been source-verified')
    if not isinstance(answer, str) or len(answer) > 12000:
        raise ValueError('Invalid objective answer')
    try:
        # Reject duplicate JSON fields instead of silently selecting the last answer.
        def unique(pairs):
            output = {}
            for key, value in pairs:
                if key in output:
                    raise ValueError('Duplicate answer field')
                output[key] = value
            return output
        submitted = json.loads(answer, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise ValueError('Use the structured objective answer controls') from None
    objective = question['objective']
    if not isinstance(submitted, dict):
        raise ValueError('Invalid objective answer shape')
    if fmt == 'mcq':
        if set(submitted) != {'choice'} or not isinstance(submitted['choice'], str) or submitted['choice'] not in {o['id'] for o in objective['options']}:
            raise ValueError('Choose one supplied option')
        responses = {question['rubric'][0]['id']: submitted['choice']}
        correct = {question['rubric'][0]['id']: submitted['choice'] == objective['correctOptionId']}
    else:
        if set(submitted) != {'responses'} or not isinstance(submitted['responses'], dict):
            raise ValueError('Invalid objective responses')
        responses = submitted['responses']
        required = {p['id'] for p in question['rubric']}
        if set(responses) != required or any(not isinstance(v, str) or not v.strip() or len(v) > 500 or '[unclear]' in v.lower() for v in responses.values()):
            raise ValueError('Complete and review every supplied item')
        if fmt == 'blanks':
            correct = {s['id']: _normal(responses[s['id']]) in {_normal(a) for a in s['acceptedAnswers']} for s in objective['slots']}
        else:
            right = {item['id'] for item in objective['right']}
            if any(v not in right for v in responses.values()) or len(set(responses.values())) != len(responses):
                raise ValueError('Choose a different supplied match for every item')
            correct = {key: value == objective['matches'][key] for key, value in responses.items()}
    points = [{'id': p['id'], 'concept': p['concept'], 'awarded': p['marks'] if correct[p['id']] else 0,
               'maxMarks': p['marks'], 'quote': responses[p['id']],
               'reason': 'Matches the mentor-approved key.' if correct[p['id']] else 'Does not match the mentor-approved key.'} for p in question['rubric']]
    return {'status': 'graded', 'assessmentMode': 'deterministic-approved-key', 'provisional': True,
            'score': round(sum(p['awarded'] for p in points), 2), 'maxMarks': question['maxMarks'],
            'understoodMeaning': 'Your reviewed objective selections were checked against the mentor-approved key.',
            'points': points, 'improvement': [], 'modelAnswer': question['modelAnswer'],
            'referenceLabel': question['referenceLabel'], 'page': question['page']}
