"""Truthful source labels without changing existing fallback data behavior."""
import asyncio
import pytest
from routers import student_dashboard as sd

@pytest.mark.parametrize('rows', [[], None])
def test_empty_sheet_is_labeled_fallback(monkeypatch, rows):
    accounts = [{'studentId': 'UMP0001', 'group': 'Both', 'joinedOn': '2026-10-01'}]
    monkeypatch.setattr(sd, '_fetch_tracker_roster_sync', lambda: rows)
    roster, source = asyncio.run(sd._tracker_roster(accounts))
    assert roster is accounts
    assert source == 'Mongo fallback'

def test_failed_sheet_keeps_existing_accounts_and_warns(monkeypatch):
    accounts = [{'studentId': 'UMP0001', 'group': 'Group 1'}]
    def unavailable():
        raise RuntimeError('offline fixture')
    monkeypatch.setattr(sd, '_fetch_tracker_roster_sync', unavailable)
    roster, source = asyncio.run(sd._tracker_roster(accounts))
    assert roster is accounts
    assert source == 'Mongo fallback'

def test_nonempty_sheet_remains_authoritative_and_keeps_joining_date(monkeypatch):
    accounts = [{'studentId': 'UMP0001', 'group': 'Group 1', 'joinedOn': '2026-10-01'}]
    monkeypatch.setattr(sd, '_fetch_tracker_roster_sync', lambda: [{'studentId': 'UMP0001', 'group': 'Both'}])
    roster, source = asyncio.run(sd._tracker_roster(accounts))
    assert source == 'Students Sheet'
    assert roster[0]['group'] == 'Both'
    assert roster[0]['joinedOn'] == '2026-10-01'
    assert accounts[0]['group'] == 'Group 1'
