"""Student IDs must be read the way students type them (synthetic data only).

On 04-Nov-2026, 15 of the 37 open failed logins were a mistyped prefix or a
letter O instead of a zero, and the app told those students "Student ID not
found" while their account existed.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from auth import hash_password
from routers.student_auth import normalize_student_id


@pytest.mark.parametrize("typed,expected", [
    ("UMP0092", "UMP0092"),
    ("ump0092", "UMP0092"),
    ("UPM0092", "UMP0092"),      # letters swapped - the most common typo
    ("UPM0092 ", "UMP0092"),
    ("UMPO350", "UMP0350"),      # letter O instead of zero
    ("UMPO349", "UMP0349"),
    ("UMP00092", "UMP0092"),     # one zero too many
    ("UMP92", "UMP0092"),
    ("UMP0001", "UMP0001"),
    ("UMP0001UMP0001", "UMP0001"),
])
def test_typos_are_read_as_the_real_id(typed, expected):
    assert normalize_student_id(typed) == expected


@pytest.mark.parametrize("typed", [
    "UMP2026@9911",           # phone number glued on, not a guessable repair
    "WRO0860202",
    "AJAYNARYAL10@GMAIL.COM",
    "",
])
def test_unknown_forms_are_not_guessed_into_an_id(typed):
    assert normalize_student_id(typed) == (typed or "").strip().upper()


def test_prefix_repair_never_invents_an_account():
    # "UPM2026" and "UMO0238" are repaired into the UMP form, but no account has
    # that number, so the login still fails with not_found instead of succeeding.
    assert normalize_student_id("UPM2026") == "UMP2026"
    assert normalize_student_id("UMO0238") == "UMP0238"


def test_login_accepts_a_swapped_prefix_and_letter_o():
    sid, password = "UMP0092", "local-synthetic-password"
    from db import STUDENT_ACCOUNTS, get_db

    async def setup():
        await get_db()[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid},
            {"$set": {"studentId": sid, "passwordHash": hash_password(password),
                      "batch": "LOCAL BATCH", "group": "Group 1",
                      "attempt": "Jan 2027", "accessEnabled": True}},
            upsert=True,
        )

    asyncio.run(setup())
    from server import app
    client = TestClient(app)
    for typed in ("UPM0092", "UMPO092", "UMP92"):
        res = client.post("/api/student-auth/login", json={"studentId": typed, "password": password})
        assert res.status_code == 200, typed
        body = res.json()["result"]
        assert body["success"] is True, (typed, body)
        assert body["studentId"] == sid


def test_an_unknown_id_still_fails_with_the_format_hint():
    from server import app
    client = TestClient(app)
    res = client.post("/api/student-auth/login", json={"studentId": "WRO0860202", "password": "x"})
    result = res.json()["result"]
    assert result["success"] is False
    assert result["code"] == "not_found"
    assert "UMP" in result["message"] and "4 digits" in result["message"]
