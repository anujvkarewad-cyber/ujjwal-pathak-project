"""Mentor Notes Inbox — server-side replacement for the flaky Apps Script inbox.

Lists PDFs waiting in the Drive "UMP Notes Inbox" folder and publishes them in
the mentor's preferred one-file-at-a-time format:

    Name of file -> Batches (multi) -> Group (1/2/Both) -> Subject (fixed CA list)

Publish does, per selected batch:
  1. make the inbox file link-readable (students open a direct-download URL),
  2. append one row to the tracker Sheet "Notes" tab (one row per batch,
     sharing the single fileId).
The student app reads the Notes sheet (not the Drive tree), so this is all it
needs. A service account cannot copy (zero storage quota) or re-file (non-owner
addParents) the PDF into the batch/group/subject folders, so Drive tree filing
is intentionally not attempted. The inbox queue advances by sheet membership:
once a fileId appears in the Notes sheet it no longer shows as waiting.

Google access uses a service-account JSON from env (reuses the proofs SA when
present) and mints scoped Drive+Sheets tokens via a RS256 JWT assertion, the
same pattern lib/proof-upload.js uses on the gateway.
"""
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import urllib.parse

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import require_mentor
from db import DASHBOARD_SHARED, get_db
import push as push_service

router = APIRouter(prefix="/api/notes-inbox", tags=["notes-inbox"])

IST = timezone(timedelta(hours=5, minutes=30))

INBOX_FOLDER_ID = os.environ.get(
    "NOTES_INBOX_FOLDER_ID", "1YUpTGxH8f-SjtZi9ykZXBSmqYGS07BR2"
).strip()
ROOT_FOLDER_ID = os.environ.get(
    "NOTES_ROOT_FOLDER_ID", "1m_baXOoneBdmojh603WyBJvceHtghrpR"
).strip()
SHEET_ID = os.environ.get(
    "NOTES_SHEET_ID", "1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc"
).strip()
SHEET_TAB = os.environ.get("NOTES_SHEET_TAB", "Notes").strip()
UPLOADED_BY = os.environ.get("NOTES_UPLOADED_BY", "ujjwal pathak mentorship program")

SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"

BATCHES = [
    "Before Result Batch 1",
    "Before Result Batch 2",
    "After Result Batch 1",
    "After Result Batch 2",
]
GROUPS = ["Group 1", "Group 2", "Both Groups"]
# display label -> (sheet subject value, drive folder name)
SUBJECTS = {
    "Accounts": "Accounts",
    "Law": "Law",
    "DT": "DT",
    "GST": "GST",
    "Costing": "Costing",
    "Audit": "Audit",
    "FM": "FM",
    "SM": "SM",
}
GROUP_FOLDER = {"Group 1": "Group 1", "Group 2": "Group 2", "Both Groups": "Both Groups"}

# ── Chapter folder + series (teacher) ────────────────────────────────────────
# Owner ka FINAL structure (14 Oct 2026, dusra screenshot): subject ke andar
# app ka STEP-3 folder = **SERIES** — "Super 75" ya teacher ka naam (owner:
# "super 75 mai ye saare notes hone chahie"). Us folder ke andar notes
# **chapter-wise** naam ke saath dikhte hain ("Ch 2 · Chapter 2 Audit Test QP",
# "Ch 11 · …") aur chapter number se sorted hote hain. Isliye `category` me
# series jaata hai (app isi field par folder banata hai) aur `chapter` me ICAI
# chapter label. App update ki zaroorat NAHI hai.
SERIES_DEFAULT = "Super 75"
MAX_SERIES = 60
MAX_CHAPTER = 90
SUBJECT_ORDER = ["Accounts", "Law", "DT", "GST", "Costing", "Audit", "FM", "SM"]

_token_cache: Dict[str, Any] = {"value": "", "expires_at": 0.0}
_sheet_cols_cache: Dict[str, str] = {}


def _sa_credentials() -> Dict[str, str]:
    raw = (
        os.environ.get("NOTES_GOOGLE_SA_JSON")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or ""
    ).strip()
    if not raw:
        raise HTTPException(
            status_code=501,
            detail="Notes inbox Google service account is not configured on this server.",
        )
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=501, detail="Service account JSON is invalid.") from exc
    email = str(parsed.get("client_email") or "").strip()
    key = str(parsed.get("private_key") or "").replace("\\n", "\n")
    if not email or not key:
        raise HTTPException(status_code=501, detail="Service account JSON lacks credentials.")
    return {"email": email, "private_key": key}


def _google_token() -> str:
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"]
    import jwt  # PyJWT (RS256 needs cryptography, present in requirements)

    creds = _sa_credentials()
    iat = int(now)
    claim = {
        "iss": creds["email"],
        "scope": SCOPES,
        "aud": TOKEN_URI,
        "iat": iat,
        "exp": iat + 3300,
    }
    assertion = jwt.encode(claim, creds["private_key"], algorithm="RS256")
    resp = requests.post(
        TOKEN_URI,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=20,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or not data.get("access_token"):
        raise HTTPException(status_code=502, detail=f"Google token exchange failed ({resp.status_code}).")
    _token_cache["value"] = data["access_token"]
    _token_cache["expires_at"] = now + max(60, int(data.get("expires_in", 3600)) - 300)
    return _token_cache["value"]


def _drive_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_google_token()}"}


def _drive_get(path: str, **params: Any) -> Any:
    resp = requests.get(f"{DRIVE}{path}", headers=_drive_headers(), params=params, timeout=30)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Drive read failed ({resp.status_code}).")
    return resp.json()


def _drive_post(path: str, body: Dict[str, Any], **params: Any) -> Any:
    resp = requests.post(
        f"{DRIVE}{path}", headers=_drive_headers(), json=body, params=params, timeout=60
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Drive write failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _drive_patch(path: str, body: Dict[str, Any]) -> Any:
    resp = requests.patch(f"{DRIVE}{path}", headers=_drive_headers(), json=body, timeout=30)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Drive update failed ({resp.status_code}).")
    return resp.json()


def _drive_relink(path: str, **params: Any) -> Any:
    """files.update with query params (addParents/removeParents) and empty body."""
    resp = requests.patch(f"{DRIVE}{path}", headers=_drive_headers(), params=params, json={}, timeout=30)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Drive relink failed ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


def _find_child_folder(parent_id: str, name: str) -> Optional[str]:
    q = f"'{parent_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' and name='{name}'"
    found = _drive_get("/files", q=q, fields="files(id,name)")
    files = found.get("files") or []
    return files[0]["id"] if files else None


def _ensure_folder(parent_id: str, name: str) -> str:
    existing = _find_child_folder(parent_id, name)
    if existing:
        return existing
    created = _drive_post(
        "/files",
        {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
    )
    return created["id"]


def _sheet_columns() -> Dict[str, str]:
    """Header row padho: column name (lowercase) → letter.

    Sheet ke columns hardcode karna risky tha (live sheet me 15 columns hain,
    script ka ensureSheet 14 likhta hai). Ek hi baar padh ke map cache kar lete
    hain, taaki 'category'/'chapter' jaisa field ho to wahi likha jaye.
    """
    global _sheet_cols_cache
    if _sheet_cols_cache:
        return _sheet_cols_cache
    try:
        rng = urllib.parse.quote(f"{SHEET_TAB}!1:1")
        resp = requests.get(
            f"{SHEETS}/{SHEET_ID}/values/{rng}", headers=_drive_headers(), timeout=30
        )
        if resp.status_code < 400:
            header = (resp.json().get("values") or [[]])[0]
            mapping: Dict[str, str] = {}
            for i, name in enumerate(header):
                key = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
                if key:
                    mapping[key] = _col_letter(i)
            _sheet_cols_cache = mapping
    except Exception:
        pass
    return _sheet_cols_cache


def _col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _sheet_append_values(values: Dict[str, Any]) -> None:
    """Header-aware append: {field: value} ko sahi columns me likho.

    Fallback (header read fail) = purana positional format, taaki publish kabhi
    sheet ki wajah se na ruke.
    """
    cols = _sheet_columns()
    if not cols:
        raise RuntimeError("sheet header unavailable")
    def letter_index(letter: str) -> int:
        n = 0
        for ch in letter:
            n = n * 26 + (ord(ch) - 64)
        return n

    width = max(letter_index(c) for c in cols.values())
    row: List[Any] = [""] * width
    for field, value in values.items():
        key = re.sub(r"[^a-z0-9]", "", field.lower())
        letter = cols.get(key)
        if not letter:
            continue
        row[letter_index(letter) - 1] = value
    resp = requests.post(
        f"{SHEETS}/{SHEET_ID}/values:append",
        headers=_drive_headers(),
        params={"range": f"{SHEET_TAB}!A:O", "valueInputOption": "USER_ENTERED"},
        json={"values": [row]},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Sheet append failed ({resp.status_code}): {resp.text[:300]}"
        )


def _sheet_append(row: List[Any]) -> None:
    resp = requests.post(
        f"{SHEETS}/{SHEET_ID}/values:append",
        headers=_drive_headers(),
        params={"range": f"{SHEET_TAB}!A:O", "valueInputOption": "USER_ENTERED"},
        json={"values": [row]},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Sheet append failed ({resp.status_code}): {resp.text[:300]}"
        )


def _published_file_ids() -> set:
    """fileIds already present in the Notes sheet (column H) => already published.

    The service account cannot remove the inbox parent (non-owner), so the queue
    advances logically: anything already written to the sheet is considered done.
    """
    import urllib.parse

    rng = urllib.parse.quote(f"{SHEET_TAB}!H:H")
    try:
        resp = requests.get(
            f"{SHEETS}/{SHEET_ID}/values/{rng}", headers=_drive_headers(), timeout=30
        )
        if resp.status_code >= 400:
            return set()
        vals = resp.json().get("values") or []
        return {str(r[0]).strip() for r in vals if r and str(r[0]).strip()}
    except Exception:
        return set()


def _norm_series(value: Any) -> str:
    """Series / teacher name — free text, trimmed, capped. '' means clear."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_SERIES]


def _norm_chapter(value: Any) -> str:
    """Chapter label, e.g. 'Ch 5 — Assets Based Accounting Standards'."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_CHAPTER]


def _chapter_prefix(chapter: str) -> str:
    """'Ch 5 — Assets Based ...' -> 'Ch 5' (title ke aage lagta hai)."""
    match = re.match(r"\s*(ch(?:apter)?\.?\s*\d+[a-z]?)", chapter or "", re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _chapter_number(label: str) -> int:
    """'Ch 10 — Audit of Banks' -> 10 (folder order isse banta hai)."""
    match = re.search(r"\d+", _chapter_prefix(label))
    return int(match.group()) if match else 999


def _looks_like_chapter(label: str) -> bool:
    return bool(_chapter_prefix(label))


def _title_for(base_title: str, chapter: str = "") -> str:
    """Title ke aage chapter ka prefix: ``"Ch 5 · AS 13 …"``.

    Owner ka FINAL structure (14 Oct): app me folder = SERIES ("Super 75" /
    teacher ka naam) aur uske andar notes **chapter-wise** naam ke saath
    ("Ch 2 ·", "Ch 10 ·", "Ch 11 ·" …) dikhte hain. Purana prefix pehle hata
    dete hain, taaki chapter badalne par prefix stack na ho.
    """
    base = str(base_title or "").strip()
    if not base:
        return base
    stripped = re.sub(
        r"^\s*(?:ch(?:apter)?\.?\s*\d+[a-z]?)\s*[·:\-–—]\s*", "", base, flags=re.IGNORECASE
    ).strip()
    prefix = _chapter_prefix(chapter)
    if not prefix:
        return stripped or base
    return f"{prefix} · {stripped or base}"


def _norm_subject(value: Any) -> str:
    return str(value or "").strip()


def _sort_notes(notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Subject → series folder → chapter number → title.

    App notes ko isi array order me dikhata hai: isliye folder = series
    ("Super 75") pehle, aur us folder ke andar **chapter number** se order
    (Ch 2 → Ch 10 → Ch 11, alphabet ka Ch 10 < Ch 2 wala bug nahi).
    """

    def key(note: Dict[str, Any]):
        subject = _norm_subject(note.get("subject"))
        idx = SUBJECT_ORDER.index(subject) if subject in SUBJECT_ORDER else len(SUBJECT_ORDER)
        # Folder = category (series). Chapter uske andar ka order deta hai.
        folder = _norm_series(note.get("category") or note.get("series"))
        chapter = _norm_chapter(note.get("chapter"))
        return (
            idx,
            subject.lower(),
            folder.lower(),
            _chapter_number(chapter),
            str(note.get("title") or "").lower(),
        )

    return sorted([n for n in notes if isinstance(n, dict)], key=key)


class PublishBody(BaseModel):
    fileId: str = Field(min_length=1, max_length=64)
    batches: List[str] = Field(min_length=1)
    group: str
    subject: str
    title: str = ""
    # Series = student app ka folder (Super 75 / teacher); chapter title me prefix.
    category: str = ""
    chapter: str = ""
    series: str = ""


class FileIdBody(BaseModel):
    fileId: str = Field(min_length=1, max_length=64)


@router.get("")
async def list_inbox(claims: dict = Depends(require_mentor)):
    if not INBOX_FOLDER_ID:
        raise HTTPException(status_code=501, detail="Notes inbox folder is not configured.")
    found = _drive_get(
        "/files",
        q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,name,size,modifiedTime,mimeType)",
        orderBy="modifiedTime",
        pageSize=200,
    )
    published_ids = _published_file_ids()
    try:
        db = get_db()
        shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
        for n in shared.get("notes") or []:
            fid = str((n or {}).get("fileId") or "").strip()
            if fid:
                published_ids.add(fid)
    except Exception:
        pass
    files = [
        {
            "id": f["id"],
            "name": f["name"],
            "size": int(f.get("size") or 0),
            "modifiedTime": f.get("modifiedTime") or "",
            "mimeType": f.get("mimeType") or "",
        }
        for f in (found.get("files") or [])
        if f["id"] not in published_ids
    ]
    return {
        "ok": True,
        "files": files,
        "batches": BATCHES,
        "groups": GROUPS,
        "subjects": list(SUBJECTS.keys()),
    }


@router.post("/publish")
async def publish(body: PublishBody, claims: dict = Depends(require_mentor)):
    group = body.group.strip()
    if group not in GROUPS:
        raise HTTPException(status_code=400, detail="Choose Group 1, Group 2 or Both.")
    subject = body.subject.strip()
    if subject not in SUBJECTS:
        raise HTTPException(status_code=400, detail="Choose a subject from the list.")
    batches = [b for b in dict.fromkeys(x.strip() for x in body.batches) if b in BATCHES]
    if not batches:
        raise HTTPException(status_code=400, detail="Select at least one batch.")

    meta = _drive_get(f"/files/{body.fileId}", fields="id,name,size,mimeType")
    file_name = meta.get("name") or "file.pdf"
    file_size = int(meta.get("size") or 0)
    base_title = (body.title or "").strip() or os.path.splitext(file_name)[0]
    # FINAL structure: folder (category) = series/teacher, chapter title ke aage.
    series = _norm_series(body.series or body.category)
    chapter = _norm_chapter(body.chapter)
    title = _title_for(base_title, chapter)
    today = datetime.now(IST).date().isoformat()

    # A service account can neither create file content (zero storage quota) nor
    # add parents to files it does not own, so it cannot re-file the PDF into the
    # batch/group/subject Drive tree. The student app does not browse that tree:
    # it reads the Notes sheet (subject/batch/group + fileId/fileUrl). So publish
    # only needs (a) link access for the direct-download URL and (b) sheet rows.
    # Do not save/publicize a note after an unconfirmed permission operation.
    # The existing sharing policy is unchanged; this is not private-file closure.
    try:
        permission_response = requests.post(
            f"{DRIVE}/files/{body.fileId}/permissions",
            headers=_drive_headers(),
            params={"supportsAllDrives": "true"},
            json={"role": "reader", "type": "anyone"},
            timeout=30,
        )
        permission_ack = permission_response.json()
        if not (
            200 <= permission_response.status_code < 300
            and isinstance(permission_ack, dict)
            and isinstance(permission_ack.get("id"), str)
            and permission_ack["id"].strip()
            and not permission_ack.get("error")
            and permission_ack.get("ok") is not False
            and permission_ack.get("success") is not False
        ):
            raise ValueError("Unconfirmed permission")
    except Exception:
        # No retry and no provider details/credentials in a client response.
        raise HTTPException(
            status_code=502,
            detail="Could not confirm file access. Publication was not saved.",
        ) from None

    file_url = f"https://drive.google.com/uc?export=download&id={body.fileId}"

    # Primary student path: the student app reads notes from Mongo
    # (dashboard_shared["notes"]) via notes.listForStudent, NOT from the Sheet.
    # Writing here is reliable (no Google service-account quota/ownership limits).
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes_list = list(shared.get("notes") or [])
    published: List[Dict[str, str]] = []
    for batch in batches:
        note_id = f"NOTE-{secrets.token_hex(3).upper()}"
        notes_list.append(
            {
                "id": note_id,
                "title": title,
                "baseTitle": base_title,
                "description": "",
                "date": today,
                "subject": subject,
                "category": series,    # folder students see (Super 75 / teacher)
                "chapter": chapter,    # title me "Ch N ·" ke roop me
                "series": series,
                "fileId": body.fileId,
                "url": file_url,
                "fileUrl": file_url,
                "fileName": file_name,
                "fileSize": file_size,
                "audience": batch,
                "group": group,
                "uploadedBy": UPLOADED_BY,
                "source": "inbox",
            }
        )
        published.append({"batch": batch, "fileId": body.fileId, "noteId": note_id})
    notes_list = _sort_notes(notes_list)
    await db[DASHBOARD_SHARED].update_one(
        {"_id": "shared"},
        {"$set": {"notes": notes_list, "updatedAt": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    # Mentor asked for it explicitly: publishing a file must also fire the app
    # notification, otherwise the material silently appears with no ping.
    # One push per batch note, same wording as the dashboard's notes.create path.
    # Fire-and-forget: a push failure must never block or fail the publish.
    try:
        for entry in published:
            push_service.spawn(
                push_service.push_to_all(
                    f"\U0001F4DA New material: {title}",
                    "New study material is waiting in the Material tab.",
                    link="notes",
                    tag=f"note-{entry['noteId']}",
                    batch=entry["batch"],
                    group=group,
                )
            )
    except Exception:
        pass

    # Best-effort mirror into the tracker Sheet (mentor's record only). A failure
    # here must NOT block publishing, because students read Mongo, not the Sheet.
    for entry in published:
        try:
            _sheet_append_values(
                {
                    "id": entry["noteId"],
                    "title": title,
                    "description": "",
                    "subject": subject,
                    "audience": entry["batch"],
                    "fileName": file_name,
                    "fileSize": str(file_size),
                    "fileId": body.fileId,
                    "fileUrl": file_url,
                    "uploadedBy": UPLOADED_BY,
                    "date": today,
                    "group": group,
                    "category": series,
                    "chapter": chapter,
                    "series": series,
                    "source": "drive",
                }
            )
        except Exception:
            pass

    return {"ok": True, "success": True, "published": published, "title": title}


@router.post("/skip")
async def skip(body: FileIdBody, claims: dict = Depends(require_mentor)):
    _drive_patch(f"/files/{body.fileId}", {"trashed": True})
    return {"ok": True, "success": True, "skipped": body.fileId}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLISHED NOTES — Mongo hi source of truth hai (14 Oct 2026)
#
# Students notes Mongo (dashboard_shared.notes) se padhte hain, Sheet se nahi.
# Isliye mentor dashboard ki Notes page bhi ab yahi list dikhati hai — dono
# jagah ek jaisa. Sheet sirf record/r "mirror" hai (best-effort).
# ─────────────────────────────────────────────────────────────────────────────


class NoteUpdateBody(BaseModel):
    """Sirf wahi fields badlo jo mentor ne bheje hain (None = chhodo).

    Note: ``category`` (series/teacher) aur ``chapter`` me khaali string ka
    matlab hai "hata do" — baaki fields me khaali string ignore hoti hai.
    """

    id: str = Field(min_length=1, max_length=64)
    title: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None
    group: Optional[str] = None
    audience: Optional[str] = None
    category: Optional[str] = None  # folder = Super 75 / teacher (series)
    chapter: Optional[str] = None   # title me "Ch N ·" prefix
    series: Optional[str] = None    # same as category


class BulkNoteUpdateBody(BaseModel):
    """Ek saath kai notes par series + chapter lagao (purane notes divide karne ke liye)."""

    ids: List[str] = Field(min_length=1, max_length=300)
    category: Optional[str] = None  # folder = Super 75 / teacher (series)
    chapter: Optional[str] = None   # title me "Ch N ·" prefix
    series: Optional[str] = None    # same as category
    subject: Optional[str] = None


class NoteIdBody(BaseModel):
    id: str = Field(min_length=1, max_length=64)


def _sheet_row_for_note(note_id: str) -> Optional[int]:
    """Notes sheet me note id (column A) ki row number (1-based) dhundo."""
    try:
        rng = urllib.parse.quote(f"{SHEET_TAB}!A:A")
        resp = requests.get(
            f"{SHEETS}/{SHEET_ID}/values/{rng}", headers=_drive_headers(), timeout=30
        )
        if resp.status_code >= 400:
            return None
        for i, row in enumerate(resp.json().get("values") or []):
            if row and str(row[0]).strip() == note_id:
                return i + 1
        return None
    except Exception:
        return None


def _sheet_update_note_row(note_id: str, fields: Dict[str, str]) -> None:
    """Sheet mirror ko update karo (best-effort — fail ho to publish na ruke)."""
    row = _sheet_row_for_note(note_id)
    if not row:
        return
    # Header se column letters (fallback: jo pehle se verify hua mapping hai).
    cols = _sheet_columns()
    col_of = {
        "title": cols.get("title", "B"),
        "description": cols.get("description", "C"),
        "subject": cols.get("subject", "D"),
        "audience": cols.get("audience", "E"),
        "group": cols.get("group", "M"),
        "category": cols.get("category", ""),
        "chapter": cols.get("chapter", ""),
        "series": cols.get("series", ""),
    }
    try:
        for key, value in fields.items():
            col = col_of.get(key)
            if not col or value is None:
                continue
            requests.put(
                f"{SHEETS}/{SHEET_ID}/values/{SHEET_TAB}!{col}{row}",
                headers=_drive_headers(),
                params={"valueInputOption": "USER_ENTERED"},
                json={"values": [[value]]},
                timeout=30,
            )
    except Exception:
        pass


def _sheet_delete_note_row(note_id: str) -> None:
    """Sheet mirror se row hatao (best-effort). File Drive me safe rehti hai."""
    row = _sheet_row_for_note(note_id)
    if not row:
        return
    try:
        # grid ka sheetId nikaalo, phir us row ko delete karo
        meta = requests.get(
            f"{SHEETS}/{SHEET_ID}?fields=sheets.properties",
            headers=_drive_headers(),
            timeout=30,
        ).json()
        sheet_id = None
        for s in meta.get("sheets") or []:
            props = s.get("properties") or {}
            if props.get("title") == SHEET_TAB:
                sheet_id = props.get("sheetId")
                break
        if sheet_id is None:
            return
        requests.post(
            f"{SHEETS}/{SHEET_ID}:batchUpdate",
            headers=_drive_headers(),
            json={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": row - 1,
                                "endIndex": row,
                            }
                        }
                    }
                ]
            },
            timeout=30,
        )
    except Exception:
        pass


@router.get("/published")
async def list_published_notes(claims: dict = Depends(require_mentor)):
    """Wahi list jo students ko dikhti hai (Mongo) — dashboard isi ko dikhaye."""
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes = [n for n in (shared.get("notes") or []) if isinstance(n, dict)]
    return JSONResponse(
        {"ok": True, "count": len(notes), "notes": notes},
        headers={"Cache-Control": "no-store"},
    )


def _apply_note_changes(note: Dict[str, Any], **fields: Any) -> Dict[str, str]:
    """Ek note par mentor ke changes lagao; jo badla wahi return karo.

    FINAL structure (owner, 14 Oct — screenshot ke baad): app me folder =
    **series** ("Super 75" / teacher ka naam, ``category`` field), aur us folder
    ke andar notes chapter-wise naam ke saath ("Ch 2 · …") sorted. Isliye:
      * ``series`` (ya purana naam ``category``) -> folder
      * ``chapter`` -> ``chapter`` field + title me "Ch N ·" prefix (stack nahi hota)
      * ``title`` -> naya base title
    Khaali string = field saaf karo.
    """
    changed: Dict[str, str] = {}

    for field in ("subject", "group", "audience"):
        if field not in fields or fields[field] is None:
            continue
        value = str(fields[field]).strip()
        if not value or str(note.get(field) or "") == value:
            continue
        note[field] = value
        changed[field] = value

    # ── folder = series (Super 75 ya teacher ka naam) ───────────────────────
    folder_label = fields.get("series") if fields.get("series") is not None else fields.get("category")
    if folder_label is not None:
        folder = _norm_series(folder_label)
        if str(note.get("category") or "") != folder or str(note.get("series") or "") != folder:
            note["category"] = folder
            note["series"] = folder
            changed["category"] = folder
            changed["series"] = folder

    # ── chapter -> field + title prefix ────────────────────────────────────
    wants_chapter = fields.get("chapter") is not None
    wants_title = fields.get("title") is not None and str(fields["title"]).strip() != ""
    wants_desc = fields.get("description") is not None
    if wants_chapter or wants_title:
        base = str(note.get("baseTitle") or "").strip() or _title_for(note.get("title") or "", "")
        if wants_title:
            base = _title_for(str(fields["title"]).strip(), "")
        chapter = _norm_chapter(fields["chapter"]) if wants_chapter else _norm_chapter(note.get("chapter"))
        if wants_chapter and chapter != _norm_chapter(note.get("chapter")):
            note["chapter"] = chapter
            changed["chapter"] = chapter
        note["baseTitle"] = base
        new_title = _title_for(base, chapter)
        if new_title != str(note.get("title") or ""):
            note["title"] = new_title
            changed["title"] = new_title
    if wants_desc:
        desc = str(fields["description"]).strip()
        if desc != str(note.get("description") or ""):
            note["description"] = desc
            changed["description"] = desc

    return changed


async def _save_notes(db, notes: List[Dict[str, Any]]) -> None:
    await db[DASHBOARD_SHARED].update_one(
        {"_id": "shared"},
        {
            "$set": {
                "notes": _sort_notes(notes),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )


class MigrateBody(BaseModel):
    """Ek command me purane notes ko series-folder structure me le aao."""

    dryRun: bool = False


@router.post("/notes/migrate-series")
async def migrate_series_to_chapter(body: MigrateBody, claims: dict = Depends(require_mentor)):
    """Notes ko FINAL structure me le aao (idempotent, safe — kuch delete nahi hota).

    Owner ka final structure: app ka folder = **series** ("Super 75" / teacher),
    aur us folder ke andar notes chapter-wise naam ke saath ("Ch 2 · …").

    Jo notes galti se chapter-folder me chale gaye the (folder = "Ch 5 — …",
    title saaf), unhe wapas series folder me le aata hai:
        folder = series ("Super 75"/teacher), chapter wahi,
        title  = "Ch N · <base>".
    Series khaali ho to folder khaali (General) rehta hai.
    """
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes = [n for n in (shared.get("notes") or []) if isinstance(n, dict)]

    moved = 0
    for note in notes:
        folder = str(note.get("category") or "").strip()
        chapter = str(note.get("chapter") or "").strip()
        series = str(note.get("series") or "").strip()

        if not series and folder and not _looks_like_chapter(folder):
            series = folder  # purana series folder hi series hai

        # folder me chapter pada ho to use chapter field me le jao
        if _looks_like_chapter(folder):
            if not _looks_like_chapter(chapter):
                chapter = folder
            folder = series  # wapas series folder

        base = str(note.get("baseTitle") or "").strip() or _title_for(note.get("title") or "", "")

        new_state = {
            "category": folder,
            "series": series,
            "chapter": chapter,
            "baseTitle": base,
            "title": _title_for(base, chapter),
        }
        before = {
            "category": str(note.get("category") or ""),
            "series": str(note.get("series") or ""),
            "chapter": str(note.get("chapter") or ""),
            "baseTitle": str(note.get("baseTitle") or note.get("title") or ""),
            "title": str(note.get("title") or ""),
        }
        description = str(note.get("description") or "").strip()
        if description and description == series:
            # series ka naam folder me dikhta hai — note ke neeche dobara nahi chahiye
            new_state["description"] = ""
            before["description"] = description
        if before != new_state:
            moved += 1
            if not body.dryRun:
                note.update(new_state)

    if moved and not body.dryRun:
        await _save_notes(db, notes)
    return {"ok": True, "success": True, "notes": len(notes), "changed": moved, "dryRun": body.dryRun}


@router.post("/notes/bulk-update")
async def bulk_update_notes(body: BulkNoteUpdateBody, claims: dict = Depends(require_mentor)):
    """Kai notes par ek saath series + chapter lagao (ya saaf karo).

    Purane notes ko chapter-wise divide karne ka fast tarika: list me tick karo
    → chapter chuno → Save. Subject bhi saath badal sakte ho.
    """
    if body.subject is not None and body.subject.strip() and body.subject.strip() not in SUBJECTS:
        raise HTTPException(status_code=400, detail="Choose a subject from the list.")

    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes = [n for n in (shared.get("notes") or []) if isinstance(n, dict)]
    wanted = {str(i).strip() for i in body.ids if str(i).strip()}

    updated: List[Dict[str, Any]] = []
    missing: List[str] = []
    for note in notes:
        note_id = str(note.get("id") or "")
        if note_id not in wanted:
            continue
        changed = _apply_note_changes(
            note,
            category=body.category,
            chapter=body.chapter,
            series=body.series,
            subject=body.subject,
        )
        if changed:
            updated.append({"id": note_id, "changed": changed})
        wanted.discard(note_id)

    missing = sorted(wanted)
    if updated:
        await _save_notes(db, notes)
        for entry in updated:
            _sheet_update_note_row(entry["id"], entry["changed"])

    return {
        "ok": True,
        "success": True,
        "updatedCount": len(updated),
        "updated": updated,
        "missing": missing,
    }


@router.post("/notes/update")
async def update_published_note(body: NoteUpdateBody, claims: dict = Depends(require_mentor)):
    """Note ke group/subject/batch/title/description + series/chapter badlo."""
    if body.group is not None and body.group not in GROUPS:
        raise HTTPException(status_code=400, detail="Choose Group 1, Group 2 or Both.")
    if body.subject is not None and body.subject.strip() not in SUBJECTS:
        raise HTTPException(status_code=400, detail="Choose a subject from the list.")
    if body.audience is not None and body.audience.strip() not in BATCHES + ["All Batches"]:
        raise HTTPException(status_code=400, detail="Choose a valid batch.")

    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes = [n for n in (shared.get("notes") or []) if isinstance(n, dict)]
    target = None
    for n in notes:
        if str(n.get("id") or "") == body.id:
            target = n
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Note not found in the app list.")

    changed = _apply_note_changes(
        target,
        title=body.title,
        description=body.description,
        subject=body.subject,
        group=body.group,
        audience=body.audience,
        category=body.category,
        chapter=body.chapter,
        series=body.series,
    )

    if changed:
        await _save_notes(db, notes)
        _sheet_update_note_row(body.id, changed)

    return {"ok": True, "success": True, "id": body.id, "changed": changed, "note": target}


@router.post("/notes/delete")
async def delete_published_note(body: NoteIdBody, claims: dict = Depends(require_mentor)):
    """App list (Mongo) se note hatao + sheet mirror row bhi.

    Drive ki PDF delete NAHI hoti — file safe rehti hai (chaho to dobara
    publish kar sakte ho).
    """
    db = get_db()
    shared = await db[DASHBOARD_SHARED].find_one({"_id": "shared"}) or {}
    notes = [n for n in (shared.get("notes") or []) if isinstance(n, dict)]
    kept = [n for n in notes if str(n.get("id") or "") != body.id]
    removed = len(notes) - len(kept)
    if removed:
        await db[DASHBOARD_SHARED].update_one(
            {"_id": "shared"},
            {"$set": {"notes": kept, "updatedAt": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        _sheet_delete_note_row(body.id)
    return {"ok": True, "success": True, "removed": removed, "id": body.id}
