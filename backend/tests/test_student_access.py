"""Mentor access ON/OFF (the owner flow: block students who stop studying,
with a visible reason; turning access back on restores them).

Contract checked here:
- authenticate_student blocks with code "access_blocked" + the mentor's reason
  when accessEnabled is False (even for the correct password).
- POST /students/{sid}/access writes Mongo (accessEnabled/Reason/UpdatedAt/By).
- GET /students/{sid}/admin-state reports access + removal state.
- The student /get dispatcher and /api/targets/complete refuse blocked students.
- Turning access back ON clears the block.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeDB:
    def __init__(self, collections=None):
        self._collections = collections or {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, FakeCollection())


class FakeCollection:
    def __init__(self):
        self.docs = []

    def add(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", f"id{len(self.docs) + 1}")
        self.docs.append(doc)
        return self

    def _match(self, doc, flt):
        if not flt:
            return True
        for key, want in flt.items():
            if key == "$or":
                if not any(self._match(doc, sub) for sub in want):
                    return False
            elif isinstance(want, dict):
                for op, val in want.items():
                    if op == "$in":
                        if doc.get(key) not in val:
                            return False
                    elif op == "$gte":
                        if not (doc.get(key) is not None and doc.get(key) >= val):
                            return False
                    elif op == "$lte":
                        if not (doc.get(key) is not None and doc.get(key) <= val):
                            return False
                    elif op == "$regex":
                        import re

                        if not re.search(val, str(doc.get(key) or "")):
                            return False
                    elif op == "$exists":
                        if (key in doc) != bool(val):
                            return False
                    else:
                        raise NotImplementedError(op)
            elif doc.get(key) != want:
                return False
        return True

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", f"id{len(self.docs) + 1}")
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def count_documents(self, flt=None):
        return len([d for d in self.docs if self._match(d, flt or {})])

    async def find_one(self, flt, projection=None):
        for doc in self.docs:
            if self._match(doc, flt):
                if projection and isinstance(projection, dict):
                    keep = {k for k, v in projection.items() if v}
                    return {k: v for k, v in doc.items() if k in keep}
                return dict(doc)
        return None

    async def update_one(self, flt, update, upsert=False):
        for doc in self.docs:
            if self._match(doc, flt):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        if upsert:
            doc = dict(flt)
            doc.update(update.get("$set", {}))
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, upserted_id=1)
        return SimpleNamespace(matched_count=0)

    def find(self, flt=None, projection=None):
        matched = [dict(d) for d in self.docs if self._match(d, flt or {})]
        if projection and isinstance(projection, dict):
            keep = {k for k, v in projection.items() if v}
            matched = [{k: v for k, v in d.items() if k in keep} for d in matched]

        class _Cursor:
            def __init__(self, rows):
                self._rows = rows

            def sort(self, key, direction=1):
                self._rows = sorted(self._rows, key=lambda row: row.get(key), reverse=direction < 0)
                return self

            async def to_list(self, length=None):
                return self._rows[:length]

        return _Cursor(matched)


@pytest.fixture()
def env(monkeypatch):
    accounts = FakeCollection().add(
        {
            "studentId": "UMP0094",
            "studentName": "Karan Nagila",
            "password": "secret1",
            "batch": "Before Result Batch 2",
            "group": "Group 1",
            "attempt": "Jan 2027",
            "joinedOn": "2026-09-25",
            "accessEnabled": False,
            "accessReason": "Due to Non submission of tracker",
            "accessUpdatedAt": "2026-10-09 18:12",
        }
    ).add(
        {
            "studentId": "UMP0039",
            "studentName": "Neer Tanna",
            "password": "secret2",
            "batch": "Before Result Batch 2",
            "group": "Group 1",
            "attempt": "Jan 2027",
            "joinedOn": "2026-09-25",
            "accessEnabled": True,
            "accessReason": "",
        }
    )
    db = FakeDB({"student_accounts": accounts})

    student_auth = importlib.import_module("routers.student_auth")
    student_dashboard = importlib.import_module("routers.student_dashboard")
    daily_targets = importlib.import_module("routers.daily_targets")
    monkeypatch.setattr(student_auth, "get_db", lambda: db, raising=False)
    monkeypatch.setattr(student_dashboard, "get_db", lambda: db, raising=False)
    monkeypatch.setattr(daily_targets, "get_db", lambda: db, raising=False)
    from routers import dashboard_access
    monkeypatch.setattr(dashboard_access, "get_db", lambda: db)
    # Never touch the real Google Sheet during unit tests.
    async def _no_mirror(sid, enabled, reason):
        return False

    monkeypatch.setattr(student_dashboard, "_mirror_access_to_sheet", _no_mirror)
    yield SimpleNamespace(
        db=db,
        accounts=accounts,
        student_auth=student_auth,
        student_dashboard=student_dashboard,
        daily_targets=daily_targets,
    )


def test_authenticate_blocks_access_off_with_reason(env):
    result = asyncio.run(env.student_auth.authenticate_student("ump0094", "secret1"))
    assert result["success"] is False
    assert result["code"] == "access_blocked"
    assert "non submission" in result["message"].lower()
    assert "tracker" in result["message"].lower()


def test_authenticate_passes_access_on(env):
    result = asyncio.run(env.student_auth.authenticate_student("ump0039", "secret2"))
    assert result.get("success") is True


def test_set_access_off_then_on(env):
    import json

    async def _run():
        body = env.student_dashboard.StudentAccessBody(
            enabled=False, reason="Due to Non submission of tracker"
        )
        response = await env.student_dashboard.set_student_access(
            "UMP0094", body, mentor={"sub": "mentor1"}
        )
        assert response["ok"] is True
        assert response["accessEnabled"] is False
        assert "Non submission" in response["reason"]

        state = await env.student_dashboard.student_admin_state("UMP0094", _mentor={"sub": "mentor1"})
        data = json.loads(state.body)
        assert data["accessEnabled"] is False
        assert "Non submission" in data["accessReason"]
        assert data["accessUpdatedAt"]

        on_body = env.student_dashboard.StudentAccessBody(enabled=True, reason="")
        response = await env.student_dashboard.set_student_access(
            "UMP0094", on_body, mentor={"sub": "mentor1"}
        )
        assert response["accessEnabled"] is True
        result = await env.student_auth.authenticate_student("UMP0094", "secret1")
        assert result.get("success") is True

        # Only a real change lands on the lockout timeline (the student was already
        # OFF, so switching "off" again must not fake a second lockout), and it is the
        # only thing that can later prove how long they were shut out - which is what
        # grants makeup time on a test they could not open.
        from db import STUDENT_ACCESS_EVENTS

        events = env.db[STUDENT_ACCESS_EVENTS].docs
        assert [doc["enabled"] for doc in events] == [True], events
        assert events[0]["studentId"] == "UMP0094"

        await env.student_dashboard.set_student_access(
            "UMP0094",
            env.student_dashboard.StudentAccessBody(enabled=False, reason="Back to watching"),
            mentor={"sub": "mentor1"},
        )
        events = env.db[STUDENT_ACCESS_EVENTS].docs
        assert [doc["enabled"] for doc in events] == [True, False], events
        assert events[1]["reason"] == "Back to watching"

    asyncio.run(_run())


def test_access_off_requires_reason(env):
    async def _run():
        await env.student_dashboard.set_student_access(
            "UMP0039",
            env.student_dashboard.StudentAccessBody(enabled=False, reason="  "),
            mentor={"sub": "mentor1"},
        )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_run())
    assert exc.value.status_code == 400


def test_get_dispatcher_blocks_access_off(env,client):
    body={"action":"getStudyLog","payload":{"studentId":"UMP0094"}}
    assert client.post('/api/student-dashboard/get',json=body).status_code==401
    denied=client.post('/api/student-dashboard/get',headers={"X-Student-Id":"UMP0094","X-Session-Password":"secret1"},json=body)
    assert denied.status_code==403 and 'access' in denied.json()['detail'].lower()
    assert client.post('/api/student-dashboard/get',headers={"X-Student-Id":"UMP0039","X-Session-Password":"secret2"},json={"action":"getStudyLog"}).status_code==200



def test_targets_complete_blocks_access_off(env,client):
    body={"studentId":"UMP0094","taskId":"t1"}
    assert client.post('/api/targets/complete',json=body).status_code==401
    denied=client.post('/api/targets/complete',headers={"X-Student-Id":"UMP0094","X-Session-Password":"secret1"},json=body)
    assert denied.status_code==403 and 'access' in denied.json()['detail'].lower()

