"""The Students sheet must open at once.

Why this exists: the mentor's Students screen hung for about two minutes on
every visit. The cause was compute, not data - `coverage_of()` bcrypt-checks
every student serially inside the async request handler, and bcrypt releases
the GIL while it works, so the event loop stood still and every other request
(the roster behind the same screen) queued up behind it.

The rule under test:
  * a sheet cell that has not changed is not verified twice - the verdict is
    remembered, so a repeat sweep costs no bcrypt time,
  * a cell that DID change (or an account hash that changed) is verified again,
  * the classification itself is unchanged - same verdicts, same numbers,
  * the coverage payload is served from a shared cache; an old copy is served
    immediately and refreshed behind the request, and an explicit refresh
    recomputes.
"""
import asyncio

import bcrypt

import password_sheet_sync as pss
import sheet_coverage


HEADER = ["Student ID", "Student Name", "Email", "CA Level", "Group", "Attempt", "Batch",
          "Passwords", "Password Changed"]
KNOWN = "KnownGood123"


def _hash(text=KNOWN):
    return bcrypt.hashpw(text.encode(), bcrypt.gensalt(rounds=4)).decode()


def _rows(*pairs):
    out = [HEADER]
    for sid, value in pairs:
        out.append([sid, f"Name {sid}", "x@y.z", "IP", "Group 1", "Jan 2027",
                    "Before Result Batch 1", value, ""])
    return out


def _acc(sid, hashed, **extra):
    return {"studentId": sid, "studentName": f"Name {sid}", "batch": "Before Result Batch 1",
            "passwordHash": hashed, **extra}


def _count_checks(monkeypatch):
    """Count how many times bcrypt is actually asked to verify something."""
    calls = []
    real = bcrypt.checkpw

    def counting_checkpw(value, hashed):
        calls.append((value, hashed))
        return real(value, hashed)

    monkeypatch.setattr(pss.bcrypt, "checkpw", counting_checkpw)
    return calls


# ── the verification memo ───────────────────────────────────────────────────
def test_a_repeat_sweep_does_not_verify_the_same_cell_twice(monkeypatch):
    pss._VERIFY_CACHE.clear()
    calls = _count_checks(monkeypatch)
    hashed = _hash()
    rows = _rows(("UMP0132", KNOWN))
    accounts = [_acc("UMP0132", hashed)]

    first = pss.coverage_of(rows, accounts)
    after_first = len(calls)
    second = pss.coverage_of(rows, accounts)

    assert after_first == 1
    assert len(calls) == 1, "the second sweep must not re-verify an unchanged cell"
    assert first == second
    assert first["valid"] == 1 and first["total"] == 1


def test_a_changed_cell_is_verified_again(monkeypatch):
    pss._VERIFY_CACHE.clear()
    calls = _count_checks(monkeypatch)
    hashed = _hash()
    accounts = [_acc("UMP0132", hashed)]

    pss.coverage_of(_rows(("UMP0132", KNOWN)), accounts)
    changed = pss.coverage_of(_rows(("UMP0132", "SomethingElse99")), accounts)

    assert len(calls) == 2
    assert changed["valid"] == 0
    assert changed["pending"][0]["state"] == "stale"


def test_a_changed_hash_is_verified_again(monkeypatch):
    pss._VERIFY_CACHE.clear()
    calls = _count_checks(monkeypatch)
    rows = _rows(("UMP0132", KNOWN))

    pss.coverage_of(rows, [_acc("UMP0132", _hash())])
    pss.coverage_of(rows, [_acc("UMP0132", _hash())])

    assert len(calls) == 2


# ── the shared cache ────────────────────────────────────────────────────────
def test_the_cached_copy_is_served_without_recomputing():
    sheet_coverage.reset()
    calls = []

    async def producer():
        calls.append(1)
        return {"total": 2, "valid": 2}

    async def scenario():
        first = await sheet_coverage.coverage_for(producer)
        second = await sheet_coverage.coverage_for(producer)
        return first, second

    first, second = asyncio.run(scenario())
    assert len(calls) == 1, "the payload must be computed once, not per request"
    assert first == second
    sheet_coverage.reset()


def test_an_old_copy_is_served_immediately_and_refreshed_behind_the_request():
    sheet_coverage.reset()
    calls = []

    async def producer():
        calls.append(1)
        return {"total": len(calls)}

    async def scenario():
        await sheet_coverage.coverage_for(producer)
        sheet_coverage.store({"total": "cached-copy"})
        sheet_coverage._state["at"] = 0.0  # pretend the copy is old
        served = await sheet_coverage.coverage_for(producer)
        await asyncio.sleep(0)  # let the background refresh run
        return served, sheet_coverage.payload()

    served, stored = asyncio.run(scenario())
    assert served == {"total": "cached-copy"}, "an old copy must still answer at once"
    assert stored["total"] == 2, "the refresh must land behind the request"
    sheet_coverage.reset()


def test_an_explicit_refresh_recomputes():
    sheet_coverage.reset()
    calls = []

    async def producer():
        calls.append(1)
        return {"total": len(calls)}

    async def scenario():
        await sheet_coverage.coverage_for(producer)
        await sheet_coverage.coverage_for(producer, refresh=True)
        return len(calls)

    assert asyncio.run(scenario()) == 2
    sheet_coverage.reset()


def test_the_cache_survives_a_failing_refresh():
    sheet_coverage.reset()

    async def broken():
        raise RuntimeError("sheet unreachable")

    async def scenario():
        await sheet_coverage.coverage_for(broken)  # nothing cached yet -> raises
        return None

    try:
        asyncio.run(scenario())
    except RuntimeError:
        pass
    assert sheet_coverage.payload() is None
    sheet_coverage.reset()


def test_a_failed_background_refresh_keeps_the_old_copy():
    sheet_coverage.reset()

    async def broken():
        raise RuntimeError("sheet unreachable")

    async def scenario():
        await sheet_coverage.refresh(broken)
        return sheet_coverage.payload()

    assert asyncio.run(scenario()) is None
    sheet_coverage.reset()
