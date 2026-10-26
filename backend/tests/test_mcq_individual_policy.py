"""Canonical Full-10 policy: individual verified MCQ credit, no cohort gate; explicit safe cutover.

These tests cover policy only. They do not certify sync, server grading, selected-
period input filtering, or immutable publication storage (separate release gates).
"""
from dataclasses import asdict
from datetime import date, timedelta

import pytest
from routers import ranking as r

CUTOVER = date(2026, 10, 25)  # Test fixture, not an approved production start date.
END = CUTOVER + timedelta(days=6)
DAYS = {CUTOVER + timedelta(days=i) for i in range(7)}


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    monkeypatch.setattr(r, 'INDIVIDUAL_MCQ_FROM', CUTOVER)
    monkeypatch.setattr(r, 'MCQ_MODE', 'auto')
    monkeypatch.setattr(r, 'MCQ_MIN_COVERAGE', .6)


def person(sid, attempted=0, correct=0, group='Group 1'):
    return r.StudentActivity(sid, batch='B1', group=group,
        hours_by_date={d: 6 for d in DAYS}, submitted_dates=DAYS.copy(),
        questions_attempted=attempted, questions_correct=correct,
        verified_mcq_by_date={CUTOVER+timedelta(days=i): [10, max(0,min(10,correct-i*10))] for i in range(attempted//10)} if attempted%10==0 else {})


def rows(people, period='weekly', segment='batch'):
    return r.rank_segments(people, CUTOVER, END, period, segment)


@pytest.mark.parametrize('coverage_count', [0, 1, 5, 6, 10])
def test_credit_does_not_depend_on_zero_ten_fifty_sixty_or_full_coverage(coverage_count):
    people = [person(str(i), 20 if i < coverage_count else 0,
                     20 if i < coverage_count else 0) for i in range(10)]
    result = rows(people)['B1']
    assert r.mcq_coverage(people, CUTOVER, END) == coverage_count / 10
    assert all(x.mcq_used for x in result)
    for x in result:
        assert x.breakdown == {'hoursScore':20., 'mcqScore':30. if int(x.student_id) < coverage_count else 0., 'attendanceScore':30.}
        assert x.score == (80. if int(x.student_id) < coverage_count else 50.)


def test_single_solver_gains_priority_over_equal_effort_peers():
    result = rows([person('A'), person('B', 20, 20), person('C')])['B1']
    assert [x.student_id for x in result] == ['B', 'A', 'C']
    assert result[0].breakdown['mcqScore'] == 30.


def test_no_mcq_does_not_renormalize_hours_and_attendance():
    p = person('A'); p.hours_by_date = {d:12 for d in DAYS}
    result = rows([p])['B1'][0]
    assert result.score == 70.
    assert result.breakdown == {'hoursScore':40., 'mcqScore':0., 'attendanceScore':30.}
    assert r.weights(True) == (40.,30.,30.)
    assert r.MIN_QUESTIONS['weekly'] == 20


@pytest.mark.parametrize('attempted,correct,points', [(1,1,0.), (9,9,0.), (10,10,15.), (20,15,22.5), (20,20,30.), (40,20,15.)])
def test_existing_performance_and_volume_formula_is_unchanged(attempted, correct, points):
    result = rows([person('solver', attempted, correct), person('peer')])['B1']
    solver = next(x for x in result if x.student_id == 'solver')
    assert solver.breakdown['mcqScore'] == points


def test_another_student_syncing_across_sixty_percent_cannot_change_my_score():
    people = [person(str(i), 20 if i in (1,2) else 0, 20 if i in (1,2) else 0) for i in range(5)]
    before = {x.student_id:asdict(x) for x in rows(people)['B1']}
    people[3].questions_attempted = people[3].questions_correct = 20
    after = {x.student_id:asdict(x) for x in rows(people)['B1']}
    # Rank may legitimately move when a peer earns points; MY points must not.
    assert before['0']['score'] == after['0']['score'] == 50.
    assert before['0']['breakdown'] == after['0']['breakdown']


@pytest.mark.parametrize('legacy_mode', ['auto','on','off'])
def test_old_mode_and_coverage_settings_cannot_disable_active_individual_policy(monkeypatch, legacy_mode):
    monkeypatch.setattr(r, 'MCQ_MODE', legacy_mode)
    monkeypatch.setattr(r, 'MCQ_MIN_COVERAGE', 1.)
    assert r.mcq_enabled([person('A', 1, 1), person('B')], CUTOVER, END)


@pytest.mark.parametrize('period', ['weekly','monthly','overall'])
def test_all_live_periods_use_individual_policy_for_their_asof_week(period):
    result = rows([person('solver', 20, 20), person('other')], period)['B1']
    assert all(x.mcq_used for x in result)
    assert next(x for x in result if x.student_id == 'solver').breakdown['mcqScore'] > 0


def test_batch_group_boards_stay_exclusive():
    people = [person('g1',1,1,'Group 1'), person('g2',1,1,'Group 2'),
              person('both',1,1,'Both'), person('unknown',1,1,'')]
    grouped = rows(people, segment='batch_group')
    assert len(grouped) == 4
    assert {x.student_id for group in grouped.values() for x in group} == {'g1','g2','both','unknown'}
    assert [x.student_id for x in grouped['B1 · Both']] == ['both']
    assert [x.student_id for x in grouped['B1 · (no group set)']] == ['unknown']
    assert all(x.mcq_used for group in grouped.values() for x in group)


@pytest.mark.parametrize('legacy_mode', ['auto','on','off'])
def test_pre_cutover_closed_week_matches_original_results_exactly(monkeypatch, legacy_mode):
    monkeypatch.setattr(r, 'MCQ_MODE', legacy_mode)
    people = [person('a',20,20), person('b'), person('c')]
    start, end = CUTOVER-timedelta(days=7), CUTOVER-timedelta(days=1)
    for p in people:
        p.hours_by_date = {d-timedelta(days=7):h for d,h in p.hours_by_date.items()}
        p.submitted_dates = {d-timedelta(days=7) for d in p.submitted_dates}
    with_cutover = [asdict(x) for x in r.rank_segments(people,start,end)['B1']]
    monkeypatch.setattr(r, 'INDIVIDUAL_MCQ_FROM', None)
    unarmed = [asdict(x) for x in r.rank_segments(people,start,end)['B1']]
    assert with_cutover == unarmed


def test_sunday_cutover_is_exact_and_invalid_window_does_not_activate():
    assert not r.individual_mcq_active(CUTOVER-timedelta(days=7), CUTOVER-timedelta(days=1))
    assert r.individual_mcq_active(CUTOVER,CUTOVER)
    assert not r.individual_mcq_active(END,CUTOVER)


def test_metadata_does_not_claim_a_sixty_percent_requirement():
    meta = r.mcq_policy_metadata(CUTOVER,END)
    assert meta['mcqMode'] == 'on'
    assert meta['mcqMinCoverage'] is None
    assert meta['mcqCoverageInformational'] is True
    assert meta['mcqPolicy'] == 'individual-daily-full10-v2'
    assert meta['mcqEffectiveFrom'] == CUTOVER.isoformat()


def test_missing_cutover_is_unarmed_not_an_accidental_rollout(monkeypatch):
    monkeypatch.delenv('RANKING_INDIVIDUAL_MCQ_FROM',raising=False)
    assert r._individual_mcq_from_env() is None
    monkeypatch.setattr(r,'INDIVIDUAL_MCQ_FROM',None)
    assert not r.individual_mcq_active(CUTOVER,END)
    assert r.mcq_policy_metadata(CUTOVER,END)['mcqPolicy'] == 'legacy-coverage-v1'


@pytest.mark.parametrize('value', ['2026-10-26','not-a-date','2026-10-25T00:00:00','20261025'])
def test_non_sunday_or_noncanonical_configuration_is_rejected(monkeypatch,value):
    monkeypatch.setenv('RANKING_INDIVIDUAL_MCQ_FROM',value)
    with pytest.raises(ValueError,match='ISO Sunday'):
        r._individual_mcq_from_env()


def test_sunday_configuration_is_accepted(monkeypatch):
    monkeypatch.setenv('RANKING_INDIVIDUAL_MCQ_FROM',CUTOVER.isoformat())
    assert r._individual_mcq_from_env() == CUTOVER
