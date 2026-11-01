"""Synthetic approved keys only. No academic rubric or production publication."""
import copy
import json
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from routers import workbook_practice as p
from workbook_formats import public_format, grade_objective
from test_workbook_practice import BOOK, ANSWER, student_headers, account, feature_env


def question(kind):
    q=copy.deepcopy(BOOK['questions'][0]);q['format']=kind
    if kind=='mcq':
        q['rubric']=[{'id':'r1','concept':'Synthetic approved option','marks':4}]
        q['objective']={'options':[{'id':'A','text':'Synthetic choice A'},{'id':'B','text':'Synthetic choice B'}],'correctOptionId':'B'}
    elif kind=='blanks':
        q['objective']={'slots':[{'id':'r1','text':'Synthetic first blank','acceptedAnswers':['Independent','Independence']},{'id':'r2','text':'Synthetic second blank','acceptedAnswers':['Appearance']}]}
    else:
        q['objective']={'left':[{'id':'r1','text':'Synthetic item one'},{'id':'r2','text':'Synthetic item two'}],'right':[{'id':'X','text':'Synthetic match X'},{'id':'Y','text':'Synthetic match Y'}],'matches':{'r1':'Y','r2':'X'}}
    return q


@pytest.mark.parametrize('kind',['mcq','blanks','matching'])
def test_model_validates_and_student_descriptor_hides_keys(kind):
    q=question(kind);p.Question.model_validate(q)
    public=json.dumps(public_format(q))
    for secret in ['acceptedAnswers','correctOptionId','"matches"','modelAnswer','rubric']:
        assert secret not in public


@pytest.mark.parametrize('choice,score',[('B',4),('A',0)])
def test_mcq_is_deterministic_including_valid_zero(choice,score):
    assert grade_objective(question('mcq'),json.dumps({'choice':choice}))['score']==score


def test_blanks_only_accept_explicit_aliases_and_preserve_negation():
    q=question('blanks')
    assert grade_objective(q,json.dumps({'responses':{'r1':'  INDEPENDENT  ','r2':'appearance'}}))['score']==4
    assert grade_objective(q,json.dumps({'responses':{'r1':'not independent','r2':'appearance'}}))['score']==2
    assert grade_objective(q,json.dumps({'responses':{'r1':'unapproved synonym','r2':'wrong'}}))['score']==0


def test_matching_scores_approved_pairs_only():
    q=question('matching')
    assert grade_objective(q,json.dumps({'responses':{'r1':'Y','r2':'X'}}))['score']==4
    assert grade_objective(q,json.dumps({'responses':{'r1':'X','r2':'Y'}}))['score']==0
    with pytest.raises(ValueError):grade_objective(q,json.dumps({'responses':{'r1':'X','r2':'X'}}))


@pytest.mark.parametrize('answer',['{}','{"choice":"Z"}','{"choice":"A","choice":"B"}','{"choice":"B","score":100}','null','[]','{"choice":true}'])
def test_mcq_bad_or_forged_answer_has_no_score(answer):
    with pytest.raises(ValueError):grade_objective(question('mcq'),answer)


@pytest.mark.parametrize('values',[{}, {'r1':'Independent'}, {'r1':'[unclear]','r2':'appearance'}, {'r1':'Independent','r2':'appearance','r3':'extra'}, {'r1':True,'r2':'appearance'}])
def test_blanks_require_complete_reviewed_response(values):
    with pytest.raises(ValueError):grade_objective(question('blanks'),json.dumps({'responses':values}))


def test_malformed_keys_marks_and_formats_cannot_be_approved():
    cases=[]
    q=question('mcq');q['objective']['correctOptionId']='Z';cases.append(q)
    q=question('mcq');q['maxMarks']=7;cases.append(q)
    q=question('blanks');q['objective']['slots'][1]['id']='other';cases.append(q)
    q=question('matching');q['objective']['matches']['r1']='X';cases.append(q)
    q=question('mcq');q['format']='unknown';cases.append(q)
    for q in cases:
        with pytest.raises(ValidationError):p.Question.model_validate(q)


@pytest.mark.parametrize('kind,response,score',[
 ('mcq',{'choice':'B'},4),
 ('blanks',{'responses':{'r1':'Independence','r2':'Appearance'}},4),
 ('matching',{'responses':{'r1':'Y','r2':'X'}},4)
])
def test_actual_authenticated_route_uses_approved_key_without_ai_or_score_writes(client,mentor_headers,student_headers,monkeypatch,kind,response,score):
    body=copy.deepcopy(BOOK);body['questions']=[question(kind)]
    created=client.post('/api/practice/mentor/workbooks',json=body,headers=mentor_headers);assert created.status_code==200
    bid=created.json()['id'];assert client.post('/api/practice/mentor/workbooks/'+bid+'/publish',headers=mentor_headers).status_code==200
    provider=AsyncMock(side_effect=AssertionError('No provider call for objective formats'));monkeypatch.setattr(p,'chat',provider)
    listing=client.get('/api/practice/workbooks',headers=student_headers);assert listing.status_code==200
    public=json.dumps(listing.json());assert 'correctOptionId' not in public and 'acceptedAnswers' not in public and '"matches"' not in public
    r=client.post('/api/practice/grade',headers=student_headers,json={'workbookId':bid,'questionId':'q1','answer':json.dumps(response),'confirmed':True})
    assert r.status_code==200 and r.json()['score']==score and r.json()['assessmentMode']=='deterministic-approved-key';provider.assert_not_awaited()
    import asyncio
    assert asyncio.run(p.get_db()[p.FEEDBACK].count_documents({}))==0
    assert asyncio.run(p.get_db()[p.USAGE].count_documents({}))==0


def test_written_question_default_is_backward_compatible():
    q=p.Question.model_validate(BOOK['questions'][0]);assert q.format=='written' and q.objective is None


def test_unverified_objective_key_cannot_be_used_even_if_a_stored_book_was_marked_published():
    q=question('mcq');q['sourceVerified']=False
    with pytest.raises(ValueError,match='source-verified'):
        grade_objective(q,'{"choice":"B"}')


def test_malformed_nested_key_is_a_validation_error_not_an_internal_type_error():
    q=question('mcq');q['objective']['correctOptionId']=[]
    with pytest.raises(ValidationError):p.Question.model_validate(q)
