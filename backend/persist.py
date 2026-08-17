"""File-backed snapshot of the content + analytics collections.

The in-memory Mongo mock loses mentor approvals on restart. This dump lets
the real dashboard keep Approve / Reject / Edit decisions across process
restarts without requiring a MongoDB server.

Disabled automatically in tests (DB_NAME=test_db) or when CONTENT_PERSIST=0.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from config import settings
from db import (
    ANALYTICS_AUDIT_SYNC,
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TRENDS,
    CONTENT_AUDIT,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_RELEASES,
    CONTENT_SCENARIOS,
    get_db,
)

logger = logging.getLogger(__name__)

COLLECTIONS = (
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    CONTENT_CHAPTERS,
    CONTENT_RELEASES,
    CONTENT_AUDIT,
    ANALYTICS_CONSENTS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TRENDS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_AUDIT_SYNC,
)

BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_STORE = BACKEND_DIR / "data" / "content-store.json"


def store_path() -> Path:
    return Path(os.environ.get("CONTENT_STORE", str(DEFAULT_STORE))).expanduser()


def should_persist() -> bool:
    if os.environ.get("CONTENT_PERSIST", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    if settings.db_name in {"test_db", "pytest"}:
        return False
    return True


async def restore_store() -> bool:
    """Load a previous snapshot into the current DB. Returns True if restored."""
    path = store_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[persist] could not read %s: %s", path, exc)
        return False
    if not isinstance(data, dict):
        return False

    db = get_db()
    restored = 0
    for name in COLLECTIONS:
        docs = data.get(name) or []
        if not isinstance(docs, list) or not docs:
            continue
        clean = []
        for doc in docs:
            if isinstance(doc, dict):
                doc = dict(doc)
                doc.pop("_id", None)
                clean.append(doc)
        if clean:
            await db[name].insert_many(clean)
            restored += len(clean)
    logger.info("[persist] restored %s documents from %s", restored, path)
    return restored > 0


async def _collect_snapshot() -> dict:
    db = get_db()
    out = {}
    for name in COLLECTIONS:
        docs = []
        async for doc in db[name].find({}):
            doc.pop("_id", None)
            docs.append(doc)
        out[name] = docs
    return out


def _write_snapshot(out: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


# Background dump machinery: mentor decisions (approve/reject/edit) only need
# the snapshot to hit disk EVENTUALLY, not inside the request. Serializing
# ~4700 questions inline made each decision take ~0.5s; scheduling it as a
# debounced background task brings the endpoint back to ~20ms.
_dump_task: asyncio.Task | None = None
_dump_again = False


async def _dump_worker() -> None:
    global _dump_task, _dump_again
    try:
        while True:
            _dump_again = False
            try:
                out = await _collect_snapshot()
                await asyncio.to_thread(_write_snapshot, out)
            except Exception:  # pragma: no cover - never break the caller
                logger.exception("[persist] background dump failed")
            if not _dump_again:
                break
    finally:
        _dump_task = None


async def dump_store() -> None:
    """Schedule a store snapshot. Returns immediately; the JSON serialization
    and file write happen in a background task (coalesced if one is already
    running). Use `dump_store_sync()` when the write must complete (shutdown)."""
    global _dump_task, _dump_again
    if not should_persist():
        return
    if _dump_task is not None and not _dump_task.done():
        # A dump is in flight — ask it to run once more with the fresh state.
        _dump_again = True
        return
    _dump_task = asyncio.get_running_loop().create_task(_dump_worker())


async def dump_store_sync() -> None:
    """Blocking variant: waits for any in-flight dump, then writes a final
    snapshot. Called on shutdown so the last mentor decisions are not lost."""
    global _dump_task
    if not should_persist():
        return
    task = _dump_task
    if task is not None and not task.done():
        try:
            await task
        except Exception:  # pragma: no cover
            pass
    out = await _collect_snapshot()
    _write_snapshot(out)
