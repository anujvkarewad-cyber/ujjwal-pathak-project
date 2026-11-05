"""One cached classification of the Students-sheet password cells.

Checking a sheet cell means bcrypt-verifying it against the stored account
hash, and bcrypt is slow on purpose: ~0.3 s per student. Doing that for every
student on every page view took the mentor's Students screen about two minutes
to open - and because the sweep ran inside the async handler it also held the
event loop, so every other dashboard request (the roster, the tracker
metrics) queued up behind it and the screen looked frozen.

The check itself is unchanged - same sheet, same hashes, same verdicts. What
changed is when it runs:

  * a verification is remembered, so an unchanged cell is never re-checked
    (see password_sheet_sync._verify_sheet_value),
  * the result is cached and served immediately,
  * the next refresh happens in the background, in a worker thread, so the
    event loop keeps serving requests while it runs,
  * a stale copy is served right away and refreshed behind the request, so a
    mentor never waits on the ledger.

The ledger only moves when a student signs in, so a cache that is a few
minutes old is as true as a fresh read.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

TTL_SEC = 900  # the sheet ledger only moves when a student signs in

_state: dict = {"at": 0.0, "payload": None, "refreshing": False, "task": None}


def payload() -> Optional[dict]:
    """The last computed coverage, if there is one."""
    return _state.get("payload")


def age_sec() -> float:
    at = _state.get("at") or 0.0
    return max(0.0, time.time() - at)


def is_fresh(max_age: float = TTL_SEC) -> bool:
    return bool(_state.get("payload")) and age_sec() < max_age


def is_refreshing() -> bool:
    return bool(_state.get("refreshing"))


def store(value: dict) -> None:
    _state["payload"] = value
    _state["at"] = time.time()


def reset() -> None:
    """Test helper: forget the cached copy."""
    _state.update(at=0.0, payload=None, refreshing=False)


async def refresh(producer: Callable[[], Awaitable[dict]]) -> None:
    """Recompute in the background. Never raises into a request."""
    if _state.get("refreshing"):
        return
    _state["refreshing"] = True
    try:
        _state["task"] = asyncio.current_task()
        result = await producer()
        if result:
            store(result)
    except Exception as exc:  # noqa: BLE001 - a background refresh must never crash the app
        logger.warning("[sheet-coverage] background refresh failed: %s", type(exc).__name__)
    finally:
        _state["refreshing"] = False
        _state["task"] = None


def schedule_refresh(producer: Callable[[], Awaitable[dict]]) -> None:
    """Fire-and-forget refresh from inside a request handler."""
    try:
        asyncio.get_running_loop().create_task(refresh(producer))
    except RuntimeError:  # no loop (sync caller) - the next request will do it
        pass


async def coverage_for(
    producer: Callable[[], Awaitable[dict]],
    refresh: bool = False,
) -> dict:
    """The coverage payload, without making the caller wait for the ledger.

    * a cached copy is returned immediately; if it is old, a refresh is
      scheduled behind the request,
    * an explicit refresh recomputes - which is cheap once the per-cell
      verifications are remembered,
    * with nothing cached the first computation is awaited, because there is
      simply nothing to show yet.
    """
    cached = payload()
    if cached:
        if not is_fresh():
            schedule_refresh(producer)
        if not refresh or is_refreshing():
            return cached
    elif is_refreshing():
        # A sweep is already running (the startup warm, or another request).
        # Wait for it instead of starting a second one.
        task = _state.get("task")
        if task is not None:
            try:
                await asyncio.shield(task)
            except Exception as exc:  # noqa: BLE001 - fall through and compute it here
                logger.warning("[sheet-coverage] running sweep failed: %s", type(exc).__name__)
            cached = payload()
            if cached:
                return cached
    result = await producer()
    if result:
        store(result)
    return result
