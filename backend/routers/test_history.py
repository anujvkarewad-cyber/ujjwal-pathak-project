"""Student test-history sync (consent-gated) + mentor read endpoints.

Students upload their mentor-test attempts here:
- MCQ tests: auto-graded score (score/total/scorePct).
- Paper tests: the submission record, then the SELF-EVALUATED marks the
  student writes after checking his answer sheet with the answer key and
  marking scheme — this is how the mentor learns what marks the student
  gave himself.

Sync contract mirrors /api/progress-sync (student_sync.py):
- Consent must be ON for the student (Profile → share progress).
- X-Sync-Token = HMAC-SHA256(studentId) when SYNC_SECRET is configured;
  without a secret the endpoint runs in documented dev mode.
- Paper-test entries upsert in place per student+test (one submission,
  marks can be updated); MCQ attempts append (entry id is unique).
"""
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

from auth import require_mentor, verify_sync_token
from config import settings
from db import (
    ANALYTICS_AUDIT_SYNC,
    ANALYTICS_CONSENTS,
    ANALYTICS_TEST_HISTORY,
    MENTOR_TESTS,
    STUDENT_ACCOUNTS,
    get_db,
)
from models import TestHistorySyncRequest
import push as push_service
from push import matches_audience  # still the rule for pushes; the sheet bucket rule below is what the rosters use

router = APIRouter(prefix="/api", tags=["test-history"])

_last_sync: dict = {}

# The Students sheet's Group cell is a BUCKET, not a set: "Group 1", "Group 2" or
# "Both" (live counts 17-Oct-2026 among students with an account: 77 / 54 / 37). A test
# is published to exactly one bucket and only that bucket's students owe it.
#
# This is the owner's rule, stated 17-Oct-2026 after the first sheet-backed version kept
# listing "Both" students under a "Group 2" test (because Both contains group 2) and
# printing them as "Group 1 + Group 2", which read like Group 1 students had been dragged
# into a Group 2 test. They were not, and they are not: a test aimed at Group 2 shows the
# Group 2 rows of that batch, full stop. A test aimed at "Both Groups" shows the "Both"
# rows. Nobody appears in a test they were not published for.
from group_bucket import GROUP_BUCKETS, bucket_of as _bucket, group_text_of as _group_text

_ALL_SCOPES = ("", "all", "all batches", "everyone")
SCOPE_TTL_SEC = 120
_scope_cache: dict = {"at": None, "rows": {}, "ok": False}


def _batch_matches(want: str, have: str) -> bool:
    w = str(want or "").strip().casefold()
    if not w or w in _ALL_SCOPES:
        return True  # no batch chosen = the whole program
    return w == str(have or "").strip().casefold()


def _header_index(header: list, *names: str) -> int:
    lowered = [str(h or "").strip().casefold() for h in header]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return -1


async def _sheet_scopes() -> dict:
    """studentId -> {"batch","groups"} straight from the Students tab, cached briefly.

    Read failure is not fatal: the caller falls back to the app's own records and the
    response says so, because a Sheets hiccup must not blank out the submissions page.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if _scope_cache["rows"] and _scope_cache["at"] and (now - _scope_cache["at"]).total_seconds() < SCOPE_TTL_SEC:
        return _scope_cache["rows"]
    out: dict[str, dict] = {}
    ok = False
    try:
        from routers.student_auth import _sheet_students_rows

        rows = await _sheet_students_rows()
        ok = True
        header = rows[0] if rows else []
        i_sid = _header_index(header, "student id", "studentid", "id")
        i_grp = _header_index(header, "group")
        i_batch = _header_index(header, "batch")
        for row in rows[1:]:
            if i_sid < 0 or len(row) <= i_sid:
                continue
            sid = _clean_sid(row[i_sid])
            if not sid:
                continue
            raw_group = str(row[i_grp]).strip() if 0 <= i_grp < len(row) else ""
            out[sid] = {
                "batch": str(row[i_batch]).strip() if 0 <= i_batch < len(row) else "",
                "bucket": _bucket(raw_group),
                # displayed exactly as the sheet writes it: "Both" stays "Both"
                "groupText": _group_text(raw_group),
            }
    except Exception as exc:  # noqa: BLE001 - sheet is an enhancement, never a hard dep
        from logging import getLogger

        getLogger("push.test-history").warning("students sheet unreadable, using app records: %s", exc)
    if ok and out:
        _scope_cache.update(at=now, rows=out, ok=True)
    return out


def _clean_sid(value) -> str:
    return str(value or "").strip().upper()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/test-history/sync")
async def sync_test_history(
    body: TestHistorySyncRequest,
    request: Request,
    x_sync_token: str = Header(default=""),
):
    if not verify_sync_token(body.studentId, x_sync_token):
        raise HTTPException(status_code=401, detail="Invalid sync token")

    db = get_db()
    consent = await db[ANALYTICS_CONSENTS].find_one({"studentId": body.studentId})
    if not consent or not consent.get("sharing"):
        raise HTTPException(status_code=403, detail="Sharing is disabled for this student")

    now_ts = time.time()
    last = _last_sync.get(body.studentId, 0)
    if now_ts - last < settings.sync_rate_limit_seconds:
        raise HTTPException(status_code=429, detail="Rate limited")
    _last_sync[body.studentId] = now_ts

    stored = 0
    for entry in body.entries:
        data = entry.model_dump()
        data["entryId"] = entry.id
        data["studentId"] = body.studentId
        if body.studentName:
            data["studentName"] = body.studentName
        if body.batch:
            data["batch"] = body.batch
        data["syncedAt"] = _now()
        await db[ANALYTICS_TEST_HISTORY].update_one(
            {
                "studentId": body.studentId,
                "testId": entry.testId,
                "kind": entry.kind,
                "entryId": entry.id,
            },
            {"$set": data},
            upsert=True,
        )
        stored += 1

    await db[ANALYTICS_AUDIT_SYNC].insert_one(
        {"at": _now(), "studentId": body.studentId, "action": "test_history_sync", "detail": {"entries": stored}}
    )
    return {"ok": True, "accepted": stored}


@router.get("/test-history")
async def list_test_history(
    student_id: Optional[str] = None,
    claims: dict = Depends(require_mentor),
):
    """Mentor view: latest-first test attempts of all students (or one)."""
    db = get_db()
    query = {"studentId": student_id} if student_id else {}
    docs = await db[ANALYTICS_TEST_HISTORY].find(query).sort("at", -1).to_list(length=1000)
    for doc in docs:
        doc.pop("_id", None)
    return {"ok": True, "entries": docs}


@router.get("/test-history/groups")
async def mentor_test_history_groups(claims: dict = Depends(require_mentor)):
    """Mentor view: attempts folded per test + who is still missing.

    Declared BEFORE /test-history/{student_id} on purpose - FastAPI matches in
    registration order, and a route defined after would swallow "groups" as a
    student id and answer with an empty list.
    """
    db = get_db()
    groups = await build_test_groups(db)
    return {
        "ok": True,
        "groups": groups,
        "totalEntries": sum(g["entryCount"] for g in groups),
        "groupLabels": sorted({t for g in groups for t in g["groupLabels"]}),
        **_scope_summary(),
    }


@router.post("/test-history/groups/{test_key}/notify")
async def notify_missing_submissions(
    test_key: str,
    body: dict = Body(default_factory=dict),
    claims: dict = Depends(require_mentor),
):
    """Push ONLY the students listed as "still missing" for one test.

    Deliberately manual: the mentor clicks it per test. There is no auto-send, no
    schedule and no retry here - and it never touches the behaviour-push reminder
    budget, because a mentor asking "submit kar do" is an answer to a real gap, not a
    daily nudge. Students whose app is locked or who have no registered device are
    reported back instead of silently skipped.
    """
    db = get_db()
    groups = await build_test_groups(db)
    group = next((g for g in groups if g["key"] == test_key or g["testId"] == test_key), None)
    if not group:
        raise HTTPException(status_code=404, detail="Unknown test")
    if not group["knownAudience"]:
        raise HTTPException(status_code=400, detail="This record has no test on file, so its audience is unknown")
    missing = [r["studentId"] for r in group["notSubmitted"]]
    if not missing:
        return {"ok": True, "sent": 0, "targets": [], "reason": "everyone in the audience has submitted"}

    title = str(body.get("title") or group["title"] or "Pending test").strip()[:120]
    note = str(body.get("message") or "").strip()[:300]
    text = note or (
        f"{title} is still waiting for your submission. Open the Tests tab to attempt it."
        if group["kind"] != "paper-test" else
        f"Upload your answer for {title} and add the marks you scored."
    )
    registered = set(await push_service.students_with_devices())
    reachable = [sid for sid in missing if sid in registered]
    no_device = [sid for sid in missing if sid not in registered]
    sent = await push_service.push_to_students(
        reachable, f"📝 {title}"[:200], text[:180], link="tests", tag=f"test-missing-{test_key}"[:64],
    )
    await db[ANALYTICS_AUDIT_SYNC].insert_one({
        "at": _now(), "studentId": claims.get("sub") or "mentor", "action": "test_history_notify",
        "detail": {"testKey": test_key, "targets": len(reachable), "sent": sent, "noDevice": no_device},
    })
    return {"ok": True, "sent": sent, "targets": reachable, "noDevice": no_device}


@router.get("/test-history/{student_id}")
async def student_test_history(student_id: str, claims: dict = Depends(require_mentor)):
    db = get_db()
    docs = await db[ANALYTICS_TEST_HISTORY].find({"studentId": student_id}).sort("at", -1).to_list(length=300)
    for doc in docs:
        doc.pop("_id", None)
    return {"ok": True, "studentId": student_id, "entries": docs}


# --------------------------------------------------------------------------- #
# mentor view: submissions grouped per test, with the people who owe one
# --------------------------------------------------------------------------- #


async def build_test_groups(db) -> list[dict]:
    """One item per test that has submissions (or is published), with two rosters.

    A flat attempt list cannot answer the only question that matters after a test goes
    out: who has NOT submitted. That needs each student's batch and group, and here that
    lives in the Google Sheet (the app's own group column is empty for 163 of 168
    accounts). The rule, stated by the owner on 17-Oct-2026 after an earlier version
    listed the wrong people:

      * the sheet's Group cell is a bucket - "Group 1", "Group 2" or "Both" - and a
        test published to one bucket is owed by exactly that bucket of that batch;
      * a "Both" student is NOT a Group 2 student for this purpose, so they do not turn
        up in a Group 2 test, and no student is ever labelled "Group 1 + Group 2";
      * the app's records are the fallback only while the sheet is unreadable;
      * a student the sheet gives no group to is never counted as "did not submit" for a
        group test - they are listed under "group not set in the sheet" to be fixed,
        rather than accused of missing something they may never have received.
    """
    entries = await db[ANALYTICS_TEST_HISTORY].find({}).sort("at", -1).to_list(2000)
    sheet = await _sheet_scopes()
    tests: dict[str, dict] = {}
    async for doc in db[MENTOR_TESTS].find({}, {"_id": 0}):
        tid = _clean_sid(doc.get("testId"))
        if tid:
            doc["bucket"] = _bucket(doc.get("group"))
            tests[tid] = doc
    accounts: dict[str, dict] = {}
    async for acc in db[STUDENT_ACCOUNTS].find(
        {}, {"_id": 0, "studentId": 1, "studentName": 1, "batch": 1, "group": 1, "removedAt": 1, "accessEnabled": 1}
    ):
        sid = _clean_sid(acc.get("studentId"))
        if not sid:
            continue
        from_sheet = sheet.get(sid) or {}
        # The sheet wins outright - including when it says nothing, because an empty app
        # field is not evidence of a group and used to be read as "matches every test".
        acc["bucket"] = from_sheet.get("bucket") or _bucket(acc.get("group"))
        acc["groupText"] = from_sheet.get("groupText") or _group_text(acc.get("group"))
        acc["batch"] = from_sheet.get("batch") or acc.get("batch") or ""
        acc["scopeFrom"] = "sheet" if (from_sheet.get("bucket") or from_sheet.get("batch") or from_sheet.get("groupText")) else (
            "accounts" if acc["bucket"] else "")
        accounts[sid] = acc

    groups: dict[str, dict] = {}
    for e in entries:
        tid = _clean_sid(e.get("testId"))
        key = tid or f"title::{str(e.get('title') or '').strip().lower()}"
        groups.setdefault(key, {"testId": tid, "meta": tests.get(tid) if tid else None, "entries": []})
        groups[key]["entries"].append(e)
    for tid, doc in tests.items():
        if not doc.get("published"):
            continue  # an unpublished test cannot expect submissions
        g = groups.setdefault(tid, {"testId": tid, "meta": doc, "entries": []})
        g["meta"] = doc

    out: list[dict] = []
    for key, g in groups.items():
        meta = g["meta"] or {}
        by_sid: dict[str, dict] = {}
        for e in g["entries"]:
            sid = _clean_sid(e.get("studentId"))
            first = sid not in by_sid
            row = by_sid.setdefault(sid, {"entries": []})
            row["entries"].append(e)
            if first:
                acc = accounts.get(sid) or {}
                row["studentId"] = sid
                row["studentName"] = e.get("studentName") or acc.get("studentName") or sid
                row["batch"] = acc.get("batch") or e.get("batch") or ""
                row["groupText"] = acc.get("groupText") or ""
                row["bucket"] = acc.get("bucket") or ""
                row["scopeFrom"] = acc.get("scopeFrom") or ""
        audience_sids: list[str] = []
        unknown_scope: list[dict] = []
        no_access: list[str] = []
        known_audience = bool(meta)
        want_bucket = meta.get("bucket") or ""   # the one bucket this test was published for
        group_unreadable = bool(str(meta.get("group") or "").strip()) and not want_bucket
        if known_audience:
            for sid, acc in accounts.items():
                if acc.get("removedAt"):
                    continue
                if not _batch_matches(meta.get("batch"), acc.get("batch")):
                    continue
                if want_bucket:
                    if not acc.get("bucket"):
                        # The test is for one group and the sheet does not place this
                        # student in any: shown for the mentor to fix, never accused.
                        unknown_scope.append({
                            "studentId": sid,
                            "studentName": acc.get("studentName") or sid,
                            "batch": acc.get("batch") or "",
                            "groupText": acc.get("groupText") or "",
                        })
                        continue
                    if acc["bucket"] != want_bucket:
                        continue  # a different bucket: they were never in this test
                if acc.get("accessEnabled") is False:
                    no_access.append(sid)  # app locked for them: they cannot submit, don't count them as absent
                    continue
                audience_sids.append(sid)
        missing = [
            {
                "studentId": sid,
                "studentName": accounts[sid].get("studentName") or sid,
                "batch": accounts[sid].get("batch") or "",
                "groupText": accounts[sid].get("groupText") or "",
                "bucket": accounts[sid].get("bucket") or "",
                "scopeFrom": accounts[sid].get("scopeFrom") or "",
            }
            for sid in sorted(audience_sids)
            if sid not in by_sid
        ]
        submitted = []
        for sid, row in by_sid.items():
            attempts = sorted(row["entries"], key=lambda d: str(d.get("at") or ""), reverse=True)
            best = next((a for a in attempts if a.get("scorePct") is not None), attempts[0])
            submitted.append({
                "studentId": sid,
                "studentName": row["studentName"],
                "batch": row["batch"],
                "groupText": row.get("groupText") or "",
                "bucket": row.get("bucket") or "",
                "scopeFrom": row.get("scopeFrom") or "",
                "attempts": len(attempts),
                "lastAt": best.get("at"),
                "score": best.get("score"),
                "total": best.get("total"),
                "scorePct": best.get("scorePct"),
                "selfMarks": bool(best.get("selfMarks")),
                "kind": best.get("kind") or meta.get("kind") or "",
            })
        submitted.sort(key=lambda r: (-(r.get("scorePct") if r.get("scorePct") is not None else -1), str(r["studentId"])))

        # A submission from somebody the sheet puts in another bucket/batch is real data
        # (they clearly got the test) but it is not part of THIS roster, and mixing the two
        # is what made the screen look wrong. So they are split out, kept visible, and
        # never counted in the audience.
        def _outside_this_audience(r: dict) -> bool:
            if not known_audience:
                return False
            if not _batch_matches(meta.get("batch"), r.get("batch")):
                return True
            return bool(want_bucket) and bool(r.get("bucket")) and r["bucket"] != want_bucket

        outside = [r for r in submitted if _outside_this_audience(r)]
        submitted = [r for r in submitted if not _outside_this_audience(r)]
        # Which of the sheet's group values appear in this test, spelled as the sheet
        # spells them. No union, no expansion: a Both test says "Both", not
        # "Group 1 + Group 2", which is what made it look like other students were in it.
        group_labels = sorted({r.get("groupText") or r.get("bucket") for r in (submitted + missing)
                               if (r.get("groupText") or r.get("bucket"))})
        out.append({
            "key": key,
            "testId": g["testId"] or "",
            "title": meta.get("title") or (g["entries"][0].get("title") if g["entries"] else "Untitled test"),
            "kind": meta.get("kind") or (g["entries"][0].get("kind") if g["entries"] else ""),
            "subject": meta.get("subject") or (g["entries"][0].get("subject") if g["entries"] else ""),
            "testDate": meta.get("test_date") or "",
            "batch": meta.get("batch") or "",
            "audienceGroup": meta.get("group") or "",
            "audienceBucket": want_bucket,
            "audienceGroupUnreadable": group_unreadable,
            "groupLabels": group_labels,
            "published": bool(meta.get("published")),
            "knownAudience": known_audience,
            "totalStudents": len(submitted),
            "outsideAudience": outside,
            "outsideAudienceCount": len(outside),
            "audienceSize": len(audience_sids) if known_audience else 0,
            "submitted": submitted,
            "notSubmitted": missing,
            "unknownScope": unknown_scope,
            "noAccess": no_access,
            "entryCount": len(g["entries"]),
        })
    # Newest test first: that is the one a mentor opens the screen to look at.
    out.sort(key=lambda d: (d.get("testDate") or "", d["title"]), reverse=True)
    return out


def _scope_summary() -> dict:
    """Tell the UI where the batch/group data came from; a silent fallback to app
    records would look identical to a correct sheet-backed answer."""
    ok = bool(_scope_cache.get("ok") and _scope_cache.get("rows"))
    return {
        "groupOptions": list(GROUP_BUCKETS),
        "scopeSource": "sheet" if ok else "accounts",
        "scopeNote": ("batch + group read from the Students sheet" if ok else
                      "Students sheet unreadable - using the app's own records, so group targeting may be wider than reality"),
    }
