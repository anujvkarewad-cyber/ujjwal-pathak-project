"""Explicit mentor workspace operations. No startup migrations or scheduled writes.
Roster membership is read from Students, not copied from client-selected IDs.
A review plan is bound to a mentor and expires. Commit never automatically retries
an uncertain transfer. Bulk transfers are per-student, NOT all-or-nothing.
"""
import re
import os
import hashlib
import hmac
import jwt
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError

from auth import require_mentor
from config import settings
from db import STUDENT_ACCOUNTS, STUDENT_MESSAGES, get_db
from routers.student_auth import _sheet_students_rows, ALLOWED_STUDENT_BATCHES

router = APIRouter(prefix="/api/mentor-workspace", tags=["mentor-workspace"])
PLANS = "mentor_workspace_plans"
ANNOUNCEMENTS = "mentor_workspace_announcements"
LOCKS = "mentor_workspace_membership_locks"
GROUPS = {"group1": "Group 1", "group2": "Group 2", "both": "Both"}


def now():
    return datetime.now(timezone.utc).isoformat()


def group_key(value):
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if "both" in text or "combined" in text or re.search(r"group\s*(?:1|i)\s*(?:&|and|\+|/)\s*(?:group\s*)?(?:2|ii)\b", text):
        return "both"
    if re.fullmatch(r"(?:group\s*|g)?(?:1|i)", text):
        return "group1"
    if re.fullmatch(r"(?:group\s*|g)?(?:2|ii)", text):
        return "group2"
    return "unknown"


async def roster():
    raw = await _sheet_students_rows()
    if not raw or len(raw) >= 400:
        raise HTTPException(503, "Students source empty or bounded read reached its limit. No mutation allowed.")
    header = [str(x).strip().lower() for x in raw[0]]
    def column(*names):
        for name in names:
            if name in header:
                return header.index(name)
        raise HTTPException(503, "Students source schema is missing a required membership column.")
    si, bi, gi = column("student id", "studentid", "id"), column("batch"), column("group", "groups")
    ni = next((header.index(n) for n in ["student name", "name"] if n in header), None)
    accounts = {x["studentId"]: x async for x in get_db()[STUDENT_ACCOUNTS].find({}, {"studentId": 1, "batch": 1, "group": 1, "removedAt": 1, "status": 1, "accessEnabled": 1})}
    result, seen = [], set()
    for row in raw[1:]:
        def cell(i):
            return str(row[i] or "").strip() if i is not None and i < len(row) else ""
        sid = cell(si).upper()
        if not re.fullmatch(r"UMP\d{4,}", sid) or sid in {"UMP0000", "UMP9999"}:
            continue
        if sid in seen:
            raise HTTPException(503, "Duplicate Student IDs in authoritative roster. Resolve before proceeding.")
        seen.add(sid)
        account = accounts.get(sid)
        if account and (account.get("removedAt") or str(account.get("status") or "").lower() == "removed"):
            continue
        batch, raw_group = cell(bi), cell(gi)
        result.append({"id": sid, "studentId": sid, "name": cell(ni) or sid, "batch": batch, "group": raw_group,
                       "groupKey": group_key(raw_group), "mongoReady": bool(account),
                       "membershipConsistent": bool(account and account.get("batch") == batch and group_key(account.get("group")) == group_key(raw_group)),
                       "accessEnabled": bool(account and account.get("accessEnabled") is not False)})
    return result


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch: str = Field(min_length=1, max_length=80)
    group: str = Field(pattern=r"^(group1|group2|both)$")


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(transfer|message|announcement)$")
    studentIds: list[str] = Field(default_factory=list, max_length=100)
    scopes: list[Scope] = Field(default_factory=list, max_length=24)
    destination: Scope | None = None
    text: str = Field(default="", max_length=4000)
    title: str = Field(default="", max_length=200)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


def select_recipients(rows, body):
    by_id = {r["id"]: r for r in rows}
    ids = list(dict.fromkeys(body.studentIds))
    if any(sid not in by_id for sid in ids):
        raise HTTPException(409, "Recipient missing or removed from current roster. Refresh.")
    scoped = {(s.batch, s.group) for s in body.scopes}
    if body.scopes:
        unknown = scoped - {(r["batch"], r["groupKey"]) for r in rows}
        if unknown:
            raise HTTPException(409, "Selected workspace has no current members.")
        matching = [r["id"] for r in rows if (r["batch"], r["groupKey"]) in scoped]
        if ids and not set(ids).issubset(matching):
            raise HTTPException(409, "Selected student is outside the reviewed workspace.")
        if not ids:
            ids = matching
    if not ids or len(ids) > 100:
        raise HTTPException(400, "Choose between 1 and 100 unique recipients per review.")
    chosen = [by_id[sid] for sid in ids]
    if any(not r["membershipConsistent"] or r["groupKey"] == "unknown" for r in chosen):
        raise HTTPException(409, "Enrollment and app membership must agree before this operation. No auto-repair.")
    return chosen


@router.get("/roster")
async def get_roster(_mentor=Depends(require_mentor)):
    return {"students": await roster(), "source": "authoritative Students roster", "mock": False}


async def membership_bridge_ready():
    url = str(getattr(settings, "student_admin_script_url", "") or "").strip()
    key = str(getattr(settings, "student_import_key", "") or "").strip()
    if not url or not key:
        raise HTTPException(503, "Protected membership bridge is not configured. Transfer is unavailable.")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.post(url, json={"action": "mentorMembershipCapabilities", "payload": {"adminKey": key}})
            response.raise_for_status()
            result = response.json().get("result", {})
        if result.get("membershipVersion") != 2 or not result.get("reconciliationFence"):
            raise ValueError("bridge version unavailable")
    except Exception as exc:
        raise HTTPException(503, "Protected membership bridge has not passed its read-only capability check. No transfer write attempted.") from exc


def require_communication_release(kind):
    if kind == "transfer" and os.getenv("MENTOR_WORKSPACE_TRANSFERS_ENABLED", "0") != "1":
        raise HTTPException(503, "New membership transfers are on hold until the protected Sheet bridge is verified. Nothing changed.")
    if kind in {"message", "announcement"} and os.getenv("MENTOR_WORKSPACE_COMMUNICATIONS_ENABLED", "0") != "1":
        raise HTTPException(503, "New workspace messages and announcements are on hold until compatible student readers are released. Existing inbox remains available.")


@router.post("/review")
async def review(body: ReviewBody, mentor=Depends(require_mentor)):
    require_communication_release(body.kind)
    rows = await roster()
    chosen = select_recipients(rows, body)
    if body.kind == "transfer":
        if not body.studentIds or body.scopes or len(chosen) > 30 or not body.destination:
            raise HTTPException(400, "Transfer requires 1–30 explicit students and a destination.")
        if body.destination.batch not in ALLOWED_STUDENT_BATCHES:
            raise HTTPException(400, "Destination batch must match enrollment labels.")
        if all(r["batch"] == body.destination.batch and r["groupKey"] == body.destination.group for r in chosen):
            raise HTTPException(400, "Destination is unchanged.")
        if await get_db()[LOCKS].find_one({"_id": {"$in": [r["id"] for r in chosen]}}):
            raise HTTPException(409, "An unresolved membership operation holds a student lock. Reconcile that operation first.")
        await membership_bridge_ready()
    elif not body.text.strip() or (body.kind == "announcement" and not body.title.strip()):
        raise HTTPException(400, "Message text and announcement title are required.")
    pid = str(uuid.uuid4())
    doc = {"_id": pid, "mentor": mentor.get("sub"), "createdAt": now(),
           "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
           "state": "review", "body": body.model_dump(), "recipients": chosen}
    await get_db()[PLANS].insert_one(doc)
    return {"planId": pid, "kind": body.kind, "recipients": chosen, "recipientCount": len(chosen),
            "expiresAt": doc["expiresAt"], "destination": body.destination.model_dump() if body.destination else None,
            "accessPolicy": "destination-only; preserve history and submitted work", "bulkAtomic": False}


async def sheet_membership(sid, old, destination, operation_id):
    url = str(getattr(settings, "student_admin_script_url", "") or "").strip()
    key = str(getattr(settings, "student_import_key", "") or "").strip()
    if not url or not key:
        raise HTTPException(503, "Protected membership bridge is not configured. No write attempted.")
    payload = {"studentId": sid, "expectedBatch": old["batch"], "expectedGroup": old["group"],
               "batch": destination["batch"], "group": GROUPS[destination["group"]],
               "operationId": operation_id, "adminKey": key}
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.post(url, json={"action": "mentorChangeMembership", "payload": payload})
            res.raise_for_status()
            result = res.json().get("result", {})
    except Exception as exc:
        raise HTTPException(502, "Sheet outcome is unknown; do not retry. Reconcile membership before a new transfer.") from exc
    if not result.get("success"):
        raise HTTPException(409 if result.get("code") == "membership_conflict" else 503,
                            "Protected Sheet membership write rejected. No Mongo membership write attempted.")
    if result.get("studentId") != sid or result.get("batch") != destination["batch"] or group_key(result.get("group")) != destination["group"]:
        raise HTTPException(502, "Sheet readback mismatch; manual reconciliation required.")
    return result


async def transfer_one(plan, row):
    db = get_db()
    sid = row["id"]
    # A durable exclusive lock is retained on uncertain failure, rather than
    # silently expiring and allowing an unsafe retry. Operator reconciliation required.
    try:
        await db[LOCKS].insert_one({"_id": sid, "planId": plan["_id"], "at": now()})
    except DuplicateKeyError:
        return {"studentId": sid, "state": "blocked", "message": "Another/unresolved transfer holds the membership lock."}
    stage = "before_sheet"
    try:
        dest = plan["body"]["destination"]
        account = await db[STUDENT_ACCOUNTS].find_one({"studentId": sid})
        if not account or account.get("batch") != row["batch"] or group_key(account.get("group")) != row["groupKey"]:
            await db[LOCKS].delete_one({"_id": sid, "planId": plan["_id"]})
            return {"studentId": sid, "state": "conflict"}
        stage = "sheet_attempted"
        await sheet_membership(sid, row, dest, plan["_id"] + ":" + sid)
        stage = "sheet_updated"
        update = await db[STUDENT_ACCOUNTS].update_one(
            {"studentId": sid, "batch": row["batch"], "group": account.get("group"), "membershipVersion": account.get("membershipVersion")},
            {"$set": {"batch": dest["batch"], "group": GROUPS[dest["group"]], "updatedAt": now(),
                      "membershipVersion": str(uuid.uuid4()), "membershipUpdatedBy": plan["mentor"], "membershipOperationId": plan["_id"]}})
        if not update.matched_count:
            raise RuntimeError("Mongo membership conflict after Sheet write")
        # No credentials, progress, submitted work, ranks, validity or historical
        # snapshots are touched. Existing current-membership ACLs pick up destination.
        await db[LOCKS].delete_one({"_id": sid, "planId": plan["_id"]})
        return {"studentId": sid, "state": "completed"}
    except Exception:
        return {"studentId": sid, "state": "needs_reconciliation", "stage": stage,
                "message": "No automatic retry. Verify Students + Mongo; lock retained."}


@router.post("/plans/{plan_id}/commit")
async def commit(plan_id: str, body: ConfirmBody, mentor=Depends(require_mentor)):
    db = get_db()
    plan = await db[PLANS].find_one({"_id": plan_id, "mentor": mentor.get("sub")})
    if not plan:
        raise HTTPException(404, "Review plan not found.")
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "Explicit confirmation required.")
    if plan["state"] != "review":
        return {"state": plan["state"], "outcomes": plan.get("outcomes", []), "retryAllowed": False}
    require_communication_release(plan["body"]["kind"])
    if plan["expiresAt"] < now():
        raise HTTPException(409, "Review expired. Prepare a new review.")
    fresh = {r["id"]: r for r in await roster()}
    reviewed_body = ReviewBody(**plan["body"])
    if reviewed_body.scopes and not reviewed_body.studentIds:
        current_ids = {r["id"] for r in select_recipients(list(fresh.values()), reviewed_body)}
        if current_ids != {r["id"] for r in plan["recipients"]}:
            raise HTTPException(409, "Group membership changed since review. Review recipient count again.")
    for old in plan["recipients"]:
        current = fresh.get(old["id"])
        if not current or not current["membershipConsistent"] or (current["batch"], current["groupKey"]) != (old["batch"], old["groupKey"]):
            raise HTTPException(409, "Membership changed since review. Nothing committed; review again.")
    claimed = await db[PLANS].update_one({"_id": plan_id, "state": "review"}, {"$set": {"state": "running", "startedAt": now()}})
    if not claimed.modified_count:
        raise HTTPException(409, "Operation already claimed. Read status; do not retry.")
    outcomes = []
    try:
        kind = plan["body"]["kind"]
        if kind == "announcement":
            item = {"_id": plan_id, "id": "WS-" + plan_id, "title": plan["body"]["title"].strip(),
                    "body": plan["body"]["text"].strip(), "message": plan["body"]["text"].strip(),
                    "date": now(), "author": "Mentor", "pinned": False,
                    "workspaceTargets": [s for s in plan["body"]["scopes"]],
                    "recipientIds": [r["id"] for r in plan["recipients"]], "audience": "Workspace recipients"}
            await db[ANNOUNCEMENTS].insert_one(item)
        for row in plan["recipients"]:
            if kind == "transfer":
                outcome = await transfer_one(plan, row)
            elif kind == "message":
                message = {"id": "ws-" + plan_id, "from": "mentor", "text": plan["body"]["text"].strip(), "at": plan["createdAt"]}
                await db[STUDENT_MESSAGES].update_one({"studentId": row["id"]},
                    {"$addToSet": {"messages": message}, "$set": {"studentName": row["name"], "batch": row["batch"], "updatedAt": now()}}, upsert=True)
                outcome = {"studentId": row["id"], "state": "completed"}
            else:
                outcome = {"studentId": row["id"], "state": "completed"}
            outcomes.append(outcome)
            await db[PLANS].update_one({"_id": plan_id}, {"$set": {"outcomes": outcomes}})
            if outcome["state"] not in {"completed", "blocked", "conflict"}:
                break  # uncertain writes stop the bulk; never blindly retry remaining
        state = "completed" if len(outcomes) == len(plan["recipients"]) and all(x["state"] == "completed" for x in outcomes) else "partial"
        await db[PLANS].update_one({"_id": plan_id}, {"$set": {"state": state, "outcomes": outcomes, "finishedAt": now()}})
        # Inbox persists even if push is unavailable. No WhatsApp calls.
        if kind in {"message", "announcement"}:
            import push as push_service
            async def notify():
                for row in plan["recipients"]:
                    try:
                        await push_service.push_to_student(row["id"], "New mentor message" if kind == "message" else "New announcement",
                                                           "Open the app to read it.", link="home", tag="ws-" + plan_id)
                    except Exception:
                        pass
            push_service.spawn(notify())
        return {"state": state, "kind": kind, "outcomes": outcomes, "retryAllowed": False}
    except Exception as exc:
        await db[PLANS].update_one({"_id": plan_id}, {"$set": {"state": "needs_reconciliation", "outcomes": outcomes}})
        raise HTTPException(502, "Operation interrupted. Read plan status; do not automatically resend.") from exc


@router.get("/plans/{plan_id}")
async def status(plan_id: str, mentor=Depends(require_mentor)):
    row = await get_db()[PLANS].find_one({"_id": plan_id, "mentor": mentor.get("sub")}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Plan not found.")
    return row


async def announcements_for_student(db, student_id):
    account = await db[STUDENT_ACCOUNTS].find_one({"studentId": student_id})
    if not account:
        return []
    result = []
    async for item in db[ANNOUNCEMENTS].find({}, {"_id": 0}):
        targets = item.get("workspaceTargets") or []
        allowed = any(s["batch"] == account.get("batch") and s["group"] == group_key(account.get("group")) for s in targets) if targets else student_id in item.get("recipientIds", [])
        if allowed and student_id in item.get("recipientIds", []):
            # Internal recipient lists/review metadata never reach student apps.
            result.append({k: item[k] for k in ("id", "title", "body", "message", "date", "author", "pinned", "audience") if k in item})
    return result


@router.get("/announcements")
async def list_announcements(_mentor=Depends(require_mentor)):
    from routers.student_dashboard import _visible_announcements
    db = get_db()
    rows = [x async for x in db[ANNOUNCEMENTS].find({}, {"_id": 0})]
    return {"announcements": await _visible_announcements(db, rows)}


@router.post("/announcements/{announcement_id}/pin")
async def pin_announcement(announcement_id: str, _mentor=Depends(require_mentor)):
    from routers.student_dashboard import _visible_announcements
    db = get_db()
    doc = await db[ANNOUNCEMENTS].find_one({"id": announcement_id})
    if not doc or not await _visible_announcements(db, [doc]):
        raise HTTPException(404, "Announcement not found.")
    changed = await db[ANNOUNCEMENTS].update_one({"_id":doc["_id"], "pinned":doc.get("pinned")}, {"$set":{"pinned":not bool(doc.get("pinned"))}})
    if not changed.matched_count:
        raise HTTPException(409, "Announcement changed; refresh before pinning again.")
    return {"ok":True, "id":announcement_id, "pinned":not bool(doc.get("pinned"))}


async def fence_membership(plan, row):
    key = str(getattr(settings, "student_import_key", "") or "").strip()
    url = str(getattr(settings, "student_admin_script_url", "") or "").strip()
    if not key or not url:
        raise HTTPException(503, "Protected reconciliation fence unavailable; locks retained.")
    dest = plan["body"]["destination"]
    payload = {"adminKey": key, "studentId": row["id"], "operationId": plan["_id"] + ":" + row["id"],
               "expectedBatch": row["batch"], "expectedGroup": row["group"], "batch": dest["batch"], "group": GROUPS[dest["group"]]}
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            reply = await client.post(url, json={"action": "mentorMembershipFence", "payload": payload})
            reply.raise_for_status()
            result = reply.json().get("result", {})
        if not result.get("success") or not result.get("operationClosed") or result.get("studentId") != row["id"]:
            raise ValueError("Unverified fence")
        return result
    except Exception as exc:
        raise HTTPException(503, "Could not close the old Sheet operation. Membership locks retained; no automatic retry.") from exc


@router.post("/plans/{plan_id}/reconcile")
async def reconcile(plan_id: str, body: ConfirmBody, mentor=Depends(require_mentor)):
    """Explicit readback-only reconciliation. Never changes Sheet/account membership.
    Release a transfer lock only if both stores demonstrably agree on original
    or requested membership. A mixed state remains locked for operator review.
    """
    if body.confirm != "RECONCILE":
        raise HTTPException(400, "Explicit reconciliation confirmation required.")
    db = get_db()
    plan = await db[PLANS].find_one({"_id": plan_id, "mentor": mentor.get("sub")})
    if not plan or plan["body"]["kind"] != "transfer":
        raise HTTPException(404, "Transfer plan not found.")
    if plan["state"] not in {"partial", "needs_reconciliation", "reconciled"}:
        raise HTTPException(409, "Only terminal interrupted transfers may be reconciled; a running request must finish first.")
    fenced = {r['id']: await fence_membership(plan, r) for r in plan['recipients']}
    # Fence a delayed Mongo CAS too. This changes recovery metadata only,
    # never batch/group, so an old in-flight write cannot apply after unlock.
    for old in plan['recipients']:
        account = await db[STUDENT_ACCOUNTS].find_one({'studentId': old['id']})
        if not account:
            raise HTTPException(409, "Missing account; membership locks retained.")
        changed = await db[STUDENT_ACCOUNTS].update_one(
            {'studentId':old['id'], 'batch':account.get('batch'), 'group':account.get('group'), 'membershipVersion':account.get('membershipVersion')},
            {'$set': {'membershipVersion':str(uuid.uuid4()), 'membershipFencePlanId':plan_id}})
        if not changed.matched_count:
            raise HTTPException(409, "Concurrent membership change; locks retained. Recheck status.")
    rows = {r['id']: r for r in await roster()}
    outcomes = []
    dest = plan['body']['destination']
    for old in plan['recipients']:
        r = rows.get(old['id'])
        same = (r['batch'], r['groupKey']) if r and r['membershipConsistent'] else None
        fence = fenced[old['id']]
        if same != (fence['batch'], group_key(fence['group'])):
            same = None
        if same == (dest['batch'], dest['group']):
            state = 'completed'
        elif same == (old['batch'], old['groupKey']):
            state = 'not_applied'
        else:
            state = 'needs_reconciliation'
        if state != 'needs_reconciliation':
            await db[LOCKS].delete_one({'_id': old['id'], 'planId': plan_id})
        outcomes.append({'studentId': old['id'], 'state': state})
    state = 'reconciled' if all(r['state'] != 'needs_reconciliation' for r in outcomes) else 'needs_reconciliation'
    await db[PLANS].update_one({'_id': plan_id}, {'$set': {'state': state, 'outcomes': outcomes, 'reconciledAt': now()}})
    return {'state': state, 'outcomes': outcomes, 'retryAllowed': False}


class StudentSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    studentId: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


def credential_binding(account):
    # Signed proof is revoked immediately by password reset. No raw password
    # or password hash is placed in the token, response or application log.
    value = str(account.get("passwordHash") or account.get("password") or "")
    return hmac.new(settings.jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def student_access_ok(account):
    from routers.student_auth import _attempt_access_allowed
    return bool(account and not account.get("removedAt") and str(account.get("status") or "").lower() != "removed"
                and account.get("accessEnabled") is not False
                and (account.get("master") or _attempt_access_allowed(str(account.get("attempt") or ""), str(account.get("batch") or ""))))


@router.post("/student/session")
async def student_session(body: StudentSessionBody, response: Response):
    response.headers["Cache-Control"] = "no-store"
    from routers.student_auth import normalize_student_id, _password_ok
    sid = normalize_student_id(body.studentId)
    account = await get_db()[STUDENT_ACCOUNTS].find_one({"studentId": sid})
    if not student_access_ok(account):
        raise HTTPException(401, "Student session could not be verified.")
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    limits = get_db()["workspace_session_limits"]
    # One bounded counter per real account, not one document per request/minute.
    matched = await limits.update_one({"_id": sid, "bucket": bucket}, {"$inc": {"attempts": 1}})
    if not matched.matched_count:
        try:
            await limits.update_one({"_id": sid, "bucket": {"$ne": bucket}}, {"$set": {"bucket": bucket, "attempts": 1}}, upsert=True)
        except DuplicateKeyError:
            await limits.update_one({"_id": sid, "bucket": bucket}, {"$inc": {"attempts": 1}})
    limit = await limits.find_one({"_id": sid})
    if limit.get("attempts", 0) > 20:
        raise HTTPException(429, "Too many session checks. Wait one minute before trying again.")
    if not student_access_ok(account) or not _password_ok(body.password, account):
        raise HTTPException(401, "Student session could not be verified.")
    token = jwt.encode({"sub": sid, "role": "student_workspace", "binding": credential_binding(account),
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, settings.jwt_secret, algorithm="HS256")
    return {"studentId": sid, "token": token, "expiresIn": 900}


async def workspace_student(x_workspace_token: str = Header(default="")):
    try:
        proof = jwt.decode(x_workspace_token, settings.jwt_secret, algorithms=["HS256"])
    except Exception as exc:
        raise HTTPException(401, "Private inbox session required.") from exc
    if proof.get("role") != "student_workspace":
        raise HTTPException(403, "Private student session required.")
    account = await get_db()[STUDENT_ACCOUNTS].find_one({"studentId": proof.get("sub")})
    if not student_access_ok(account) or not hmac.compare_digest(str(proof.get("binding") or ""), credential_binding(account)):
        raise HTTPException(401, "Student session changed. Sign in again.")
    return account


@router.get("/student/messages")
async def student_private_messages(response: Response, account=Depends(workspace_student)):
    response.headers["Cache-Control"] = "no-store"
    row = await get_db()[STUDENT_MESSAGES].find_one({"studentId": account["studentId"]}) or {}
    return {"studentId": account["studentId"], "messages": row.get("messages", [])}


@router.get("/student/announcements")
async def student_private_announcements(response: Response, account=Depends(workspace_student)):
    response.headers["Cache-Control"] = "no-store"
    from routers.student_dashboard import _visible_announcements
    rows = await announcements_for_student(get_db(), account["studentId"])
    return {"studentId": account["studentId"], "announcements": await _visible_announcements(get_db(), rows)}
