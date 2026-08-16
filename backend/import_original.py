"""Import the ORIGINAL generated chapter content into the mentor backend DB.

Source  : ../student-dashboard-frontend/content-pipeline/generated/**/*.json
          (94 chapters, each file = plain[30] + scenarios[5].linkedMcqs[4],
           answerIndex 0-3, difficulty Easy/Medium/Hard)
Target  : the canonical backend document model (docs/integration-design.md §4 /
          content-pipeline/src/lib/schemas.mjs) —
            content_questions : questionType mcq|scenario_mcq,
                                options [{id: A-D, text}], correctOptionId,
                                difficulty easy|moderate|hard, icaiSourceRefs,
                                calibrationRefs, generationMeta, scenario link,
                                status needs_review, statusHistory, validation
            content_scenarios : passage + questionIds[4] + refs + status
            content_chapters  : catalog match + coverage counters

It also DELETES every record created by `backend/seed_demo.py` (SEED_DEMO=1),
so the mentor never sees DEMO content next to the real imported chapters.

Usage
-----
    # auto-detect the generated dir, purge demo data, import everything
    MONGO_URL=memory:// python backend/import_original.py

    # explicit dir / subset / preview only
    python backend/import_original.py --generated-dir /path/to/generated
    python backend/import_original.py --chapter advanced-accounting-1 --dry-run
    python backend/import_original.py --print-dir        # just resolve the dir

With MONGO_URL=memory:// the store lives inside the running process, so
`run-backend.sh` (dev_server.py, IMPORT_GENERATED=1) performs the same import
in-process at startup. Point MONGO_URL at a real MongoDB to persist it.

Re-running is safe: documents are upserted by id, unchanged questions are
skipped, and anything the mentor already acted on (approved / rejected /
changes_requested / release_candidate / published) is left untouched unless
--force is given.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings  # noqa: E402
from content_validation import validate_question, validate_scenario  # noqa: E402
from db import (  # noqa: E402
    ANALYTICS_AUDIT_SYNC,
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TRENDS,
    CONTENT_AUDIT,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    ensure_indexes,
    get_db,
)

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
CATALOG_PATH = REPO_ROOT / "content-pipeline" / "config" / "chapters.json"

IMPORTER = "import_original"
IMPORT_EDITION = os.environ.get("IMPORT_EDITION", "May 2026")

PLAIN_TARGET = 30
SCENARIO_TARGET = 5
MCQS_PER_SCENARIO = 4

OPTION_IDS = ["A", "B", "C", "D", "E", "F"]

# Statuses a mentor has already acted on — never overwritten by a re-import.
MENTOR_TOUCHED = {
    "changes_requested",
    "rejected",
    "approved",
    "release_candidate",
    "published",
    "superseded",
}

DIFFICULTY_MAP = {
    "easy": "easy",
    "basic": "easy",
    "beginner": "easy",
    "low": "easy",
    "medium": "moderate",
    "moderate": "moderate",
    "intermediate": "moderate",
    "average": "moderate",
    "hard": "hard",
    "difficult": "hard",
    "advanced": "hard",
    "high": "hard",
    "tough": "hard",
}

# ── field aliases (the generated files are not written by this repo) ────────
PLAIN_KEYS = ("plain", "plainMcqs", "plainMCQs", "plain_questions", "mcqs", "questions")
SCENARIO_KEYS = ("scenarios", "caseScenarios", "scenarioBlocks", "cases")
LINKED_KEYS = ("linkedMcqs", "linkedMCQs", "linked_mcqs", "questions", "mcqs", "linkedQuestions")
PROMPT_KEYS = ("prompt", "question", "questionText", "stem", "text", "title")
OPTION_KEYS = ("options", "choices", "answers", "optionList")
ANSWER_INDEX_KEYS = ("answerIndex", "correctIndex", "correctOptionIndex", "answer_index", "correctAnswerIndex")
ANSWER_KEYS = ("correctOptionId", "correctOption", "answer", "correct", "correctAnswer", "answerKey")
EXPLANATION_KEYS = ("explanation", "solution", "rationale", "reason", "answerExplanation")
TAG_KEYS = ("conceptTags", "tags", "concepts", "topics", "conceptTag")
PASSAGE_KEYS = ("passage", "scenario", "caseText", "case", "context", "situation", "text")
DIFFICULTY_KEYS = ("difficulty", "level", "difficultyLevel")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(data: dict, keys: Iterable[str], default=None):
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, "", [], {}):
            return data[key]
    return default


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


# ────────────────────────────── generated dir ──────────────────────────────
def candidate_dirs() -> list[Path]:
    """Places the sibling student-dashboard-frontend checkout usually lives in
    (local clone, Codespaces /workspaces, docker /app …)."""
    env = os.environ.get("GENERATED_DIR")
    names = ["student-dashboard-frontend", "student_dashboard_frontend"]
    parents = [
        REPO_ROOT.parent,
        REPO_ROOT.parent.parent,
        Path("/workspaces"),
        Path.home(),
        Path("/app"),
        Path.cwd().parent,
    ]
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser())
    for parent in parents:
        for name in names:
            out.append(parent / name / "content-pipeline" / "generated")
    # content generated inside THIS repo (fallback)
    out.append(REPO_ROOT / "content-pipeline" / "generated")
    seen, unique = set(), []
    for path in out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def detect_generated_dir(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_dir() else None
    for path in candidate_dirs():
        try:
            if path.is_dir() and any(path.rglob("*.json")):
                return path
        except OSError:  # unreadable candidate — keep looking
            continue
    return None


def iter_chapter_files(generated_dir: Path) -> list[Path]:
    files = [p for p in sorted(generated_dir.rglob("*.json")) if p.is_file()]
    # obvious non-chapter artifacts
    skip = {"manifest.json", "index.json", "state.json", "package.json", "summary.json", "report.json"}
    return [p for p in files if p.name not in skip]


# ─────────────────────────────── catalog ───────────────────────────────────
def load_catalog() -> dict[str, dict]:
    if not CATALOG_PATH.is_file():
        return {}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    chapters = data.get("chapters") if isinstance(data, dict) else data
    catalog: dict[str, dict] = {}
    for chapter in chapters or []:
        cid = chapter.get("chapterId")
        if cid:
            catalog[cid] = chapter
    return catalog


def catalog_revision() -> str:
    if CATALOG_PATH.is_file():
        try:
            return json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("catalogRevision", "unknown")
        except json.JSONDecodeError:
            pass
    return "unknown"


def resolve_chapter(data: dict, path: Path, catalog: dict[str, dict]) -> dict:
    """Chapter metadata for a generated file: id from the payload/filename,
    the rest enriched from the ICAI chapter catalog when it matches."""
    raw_chapter = data.get("chapter") if isinstance(data.get("chapter"), dict) else {}
    chapter_id = (
        data.get("chapterId")
        or raw_chapter.get("chapterId")
        or raw_chapter.get("id")
        or data.get("chapter_id")
        or (data.get("id") if isinstance(data.get("id"), str) else None)
        or path.stem
    )
    chapter_id = str(chapter_id).strip()

    entry = catalog.get(chapter_id)
    if entry is None:
        slug = _slugify(chapter_id)
        entry = catalog.get(slug)
        if entry is not None:
            chapter_id = slug
    if entry is None:  # last resort: match on title
        title = data.get("chapterTitle") or raw_chapter.get("chapterTitle") or raw_chapter.get("title")
        if title:
            for cid, c in catalog.items():
                if _slugify(c.get("chapterTitle")) == _slugify(title):
                    entry, chapter_id = c, cid
                    break

    merged = {
        "chapterId": chapter_id,
        "subject": _first(data, ("subject",)) or raw_chapter.get("subject") or (entry or {}).get("subject") or "",
        "paper": _first(data, ("paper",)) or raw_chapter.get("paper") or (entry or {}).get("paper") or "",
        "section": _first(data, ("section",)) or raw_chapter.get("section") or (entry or {}).get("section") or "",
        "module": _first(data, ("module",)) or raw_chapter.get("module") or (entry or {}).get("module") or "",
        "chapterNumber": data.get("chapterNumber")
        or raw_chapter.get("chapterNumber")
        or (entry or {}).get("chapterNumber")
        or 0,
        "chapterTitle": data.get("chapterTitle")
        or raw_chapter.get("chapterTitle")
        or raw_chapter.get("title")
        or (entry or {}).get("chapterTitle")
        or chapter_id,
        "group": data.get("group") or raw_chapter.get("group") or (entry or {}).get("group") or "",
        "catalogMatch": {"valid": entry is not None, "catalogRevision": catalog_revision()},
    }
    try:
        merged["chapterNumber"] = int(merged["chapterNumber"])
    except (TypeError, ValueError):
        merged["chapterNumber"] = 0
    return merged


# ─────────────────────────── field normalisation ───────────────────────────
def normalize_difficulty(value: Any) -> str:
    """Easy/Medium/Hard (source) → easy/moderate/hard (backend enum)."""
    key = str(value or "").strip().lower()
    return DIFFICULTY_MAP.get(key, "moderate")


def normalize_options(raw: Any) -> list[dict]:
    """['text', …] | [{id,text}] | {'A': 'text'} → [{'id': 'A', 'text': …}]."""
    options: list[dict] = []
    if isinstance(raw, dict):
        raw = [{"id": k, "text": v} for k, v in raw.items()]
    for i, item in enumerate(raw or []):
        if isinstance(item, dict):
            text = _first(item, ("text", "option", "label", "value", "answer")) or ""
            oid = str(item.get("id") or item.get("key") or "").strip().upper()
        else:
            text, oid = str(item), ""
        if not oid or len(oid) > 4:
            oid = OPTION_IDS[i] if i < len(OPTION_IDS) else str(i + 1)
        options.append({"id": oid, "text": str(text).strip()})
    return options


def resolve_correct_option_id(raw: dict, options: list[dict]) -> str:
    """answerIndex 0-3 (source) → correctOptionId 'A'-'D' (backend)."""
    ids = [o["id"] for o in options]

    index = None
    for key in ANSWER_INDEX_KEYS:  # note: 0 is a valid index, so no truthiness checks
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            index = value
            break
        if isinstance(value, str) and value.strip().isdigit():
            index = int(value.strip())
            break
    if isinstance(index, int) and 0 <= index < len(ids):
        return ids[index]

    answer = _first(raw, ANSWER_KEYS)
    if isinstance(answer, int) and 0 <= answer < len(ids):
        return ids[answer]
    if isinstance(answer, str):
        token = answer.strip()
        if token.upper() in ids:
            return token.upper()
        for option in options:  # answer given as the option text
            if option["text"].strip().lower() == token.lower():
                return option["id"]
        if token.isdigit() and 0 <= int(token) < len(ids):
            return ids[int(token)]
    return ids[0] if ids else ""


def normalize_tags(raw: Any, fallback: str) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    tags = [str(t).strip() for t in (raw or []) if str(t).strip()]
    return tags or [fallback]


def normalize_refs(raw: Any, kind: str) -> list[dict]:
    """Keep source-provided refs, normalising the `source` discriminator."""
    if isinstance(raw, dict):
        raw = [raw]
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"source": kind, "note": item}
        if not isinstance(item, dict):
            continue
        ref = dict(item)
        source = str(ref.get("source") or ref.get("type") or kind).strip()
        ref["source"] = "module" if source.lower() == "module" else source.upper()
        if ref["source"] not in ("module", "RTP", "MTP", "PYQ"):
            ref["source"] = kind
        out.append(ref)
    return out


def derived_icai_ref(chapter: dict, section: str = "") -> dict:
    return {
        "source": "module",
        "module": chapter.get("module") or "Module 1",
        "chapter": chapter.get("chapterNumber") or 0,
        "chapterTitle": chapter.get("chapterTitle"),
        "section": section or "",
        "edition": IMPORT_EDITION,
        "derivedAtImport": True,
    }


def derived_calibration_ref(chapter: dict) -> dict:
    return {
        "source": "RTP",
        "attempt": IMPORT_EDITION,
        "questionRef": "chapter-level",
        "calibrationNote": "Derived at import from the generated bundle — verify the RTP/MTP/PYQ benchmark before approval.",
        "derivedAtImport": True,
    }


def content_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ───────────────────────────── document builders ───────────────────────────
def build_question(
    raw: dict,
    chapter: dict,
    seq: int,
    *,
    question_type: str = "mcq",
    scenario_link: Optional[dict] = None,
    scenario_refs: Optional[dict] = None,
    generated_at: str,
    source_path: str,
    derive_refs: bool = True,
) -> dict:
    chapter_id = chapter["chapterId"]
    qid = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id", "").startswith("adp_") else None
    qid = qid or f"adp_q_{chapter_id}_{seq:03d}"

    prompt = str(_first(raw, PROMPT_KEYS) or "").strip()
    options = normalize_options(_first(raw, OPTION_KEYS))
    correct_option_id = resolve_correct_option_id(raw, options)
    explanation = str(_first(raw, EXPLANATION_KEYS) or "").strip()
    difficulty = normalize_difficulty(_first(raw, DIFFICULTY_KEYS))
    tags = normalize_tags(_first(raw, TAG_KEYS), fallback=_slugify(chapter.get("chapterTitle")) or chapter_id)

    icai_refs = normalize_refs(_first(raw, ("icaiSourceRefs", "sourceRefs", "references", "moduleRefs")), "module")
    calibration_refs = normalize_refs(_first(raw, ("calibrationRefs", "calibration", "benchmarkRefs")), "RTP")
    if not icai_refs and scenario_refs:
        icai_refs = list(scenario_refs.get("icaiSourceRefs") or [])
    if not calibration_refs and scenario_refs:
        calibration_refs = list(scenario_refs.get("calibrationRefs") or [])
    refs_derived = False
    if derive_refs and not icai_refs:
        icai_refs = [derived_icai_ref(chapter, str(raw.get("section") or ""))]
        refs_derived = True
    if derive_refs and not calibration_refs:
        calibration_refs = [derived_calibration_ref(chapter)]
        refs_derived = True

    meta_raw = raw.get("generationMeta") if isinstance(raw.get("generationMeta"), dict) else {}
    generation_meta = {
        "model": meta_raw.get("model") or raw.get("model") or "content-pipeline",
        "promptVersion": meta_raw.get("promptVersion") or raw.get("promptVersion") or "generated-bundle",
        "generatedAt": meta_raw.get("generatedAt") or raw.get("generatedAt") or generated_at,
        "importedBy": IMPORTER,
        "importedAt": _now(),
        "sourceFile": source_path,
    }

    doc = {
        "id": qid,
        "revision": 1,
        "chapterId": chapter_id,
        "subject": chapter["subject"],
        "paper": chapter["paper"],
        "section": chapter["section"],
        "module": chapter["module"],
        "chapterNumber": chapter["chapterNumber"],
        "chapterTitle": chapter["chapterTitle"],
        "questionType": question_type,
        "difficulty": difficulty,
        "conceptTags": tags,
        "prompt": prompt,
        "options": options,
        "correctOptionId": correct_option_id,
        "explanation": explanation,
        "icaiSourceRefs": icai_refs,
        "calibrationRefs": calibration_refs,
        "generationMeta": generation_meta,
        "scenario": scenario_link,
        "attemptSpecificRisk": bool(raw.get("attemptSpecificRisk")),
        "status": "needs_review",
        "similarity": raw.get("similarity") or {"verdict": "not_checked"},
        "importSource": {"file": source_path, "importedAt": generation_meta["importedAt"], "refsDerived": refs_derived},
    }

    errors, warnings = validate_question(doc)
    if refs_derived:
        warnings = warnings + ["ICAI/calibration references were derived at import — verify before approval"]
    doc["validation"] = {"errors": errors, "warnings": warnings, "validatedAt": _now(), "validatedBy": IMPORTER}
    doc["contentHash"] = content_hash(
        {
            "prompt": prompt,
            "options": options,
            "correctOptionId": correct_option_id,
            "explanation": explanation,
            "difficulty": difficulty,
            "conceptTags": tags,
            "questionType": question_type,
            "scenario": scenario_link,
        }
    )
    doc["statusHistory"] = [
        {"from": None, "to": "generated", "by": "content-pipeline", "at": generation_meta["generatedAt"]},
        {"from": "generated", "to": "auto_validated", "by": IMPORTER, "at": _now()},
        {"from": "auto_validated", "to": "needs_review", "by": IMPORTER, "at": _now()},
    ]
    return doc


def build_scenario(
    raw: dict,
    chapter: dict,
    index: int,
    question_ids: list[str],
    *,
    generated_at: str,
    source_path: str,
    derive_refs: bool = True,
) -> dict:
    chapter_id = chapter["chapterId"]
    sid = raw.get("scenarioId") if isinstance(raw.get("scenarioId"), str) and raw["scenarioId"].startswith("adp_s_") else None
    sid = sid or f"adp_s_{chapter_id}_{index:02d}"

    passage = str(_first(raw, PASSAGE_KEYS) or "").strip()
    icai_refs = normalize_refs(_first(raw, ("icaiSourceRefs", "sourceRefs", "references", "moduleRefs")), "module")
    calibration_refs = normalize_refs(_first(raw, ("calibrationRefs", "calibration", "benchmarkRefs")), "RTP")
    refs_derived = False
    if derive_refs and not icai_refs:
        icai_refs = [derived_icai_ref(chapter)]
        refs_derived = True
    if derive_refs and not calibration_refs:
        calibration_refs = [derived_calibration_ref(chapter)]
        refs_derived = True

    doc = {
        "scenarioId": sid,
        "revision": 1,
        "chapterId": chapter_id,
        "subject": chapter["subject"],
        "chapterTitle": chapter["chapterTitle"],
        "passage": passage,
        "icaiSourceRefs": icai_refs,
        "calibrationRefs": calibration_refs,
        "attemptSpecificRisk": bool(raw.get("attemptSpecificRisk")),
        "questionIds": question_ids,
        "status": "needs_review",
        "importSource": {"file": source_path, "importedAt": _now(), "refsDerived": refs_derived},
    }
    errors, warnings = validate_scenario(doc)
    if refs_derived:
        warnings = warnings + ["ICAI/calibration references were derived at import — verify before approval"]
    doc["validation"] = {"errors": errors, "warnings": warnings, "validatedAt": _now(), "validatedBy": IMPORTER}
    doc["contentHash"] = content_hash({"passage": passage, "questionIds": question_ids})
    doc["statusHistory"] = [
        {"from": None, "to": "generated", "by": "content-pipeline", "at": generated_at},
        {"from": "generated", "to": "auto_validated", "by": IMPORTER, "at": _now()},
        {"from": "auto_validated", "to": "needs_review", "by": IMPORTER, "at": _now()},
    ]
    return doc


def convert_file(path: Path, catalog: dict[str, dict], derive_refs: bool = True) -> Optional[dict]:
    """Generated chapter JSON → {chapter, questions[], scenarios[]}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"error": f"unreadable JSON ({exc})", "path": str(path)}
    if not isinstance(data, dict):
        if isinstance(data, list):  # bare array of plain MCQs
            data = {"plain": data}
        else:
            return {"error": "unsupported JSON shape (expected object)", "path": str(path)}

    plain_raw = _first(data, PLAIN_KEYS, []) or []
    scenarios_raw = _first(data, SCENARIO_KEYS, []) or []
    if not isinstance(plain_raw, list):
        plain_raw = []
    if not isinstance(scenarios_raw, list):
        scenarios_raw = []
    if not plain_raw and not scenarios_raw:
        return None  # not a chapter content file

    chapter = resolve_chapter(data, path, catalog)
    generated_at = (
        data.get("generatedAt")
        or (data.get("generationMeta") or {}).get("generatedAt")
        or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    )
    source_path = str(path)

    questions: list[dict] = []
    for i, raw in enumerate(plain_raw):
        if not isinstance(raw, dict):
            continue
        questions.append(
            build_question(
                raw,
                chapter,
                i + 1,
                question_type="mcq",
                scenario_link=None,
                generated_at=generated_at,
                source_path=source_path,
                derive_refs=derive_refs,
            )
        )

    scenarios: list[dict] = []
    seq = len(plain_raw)
    for s, raw_scenario in enumerate(scenarios_raw):
        if not isinstance(raw_scenario, dict):
            continue
        linked_raw = _first(raw_scenario, LINKED_KEYS, []) or []
        if not isinstance(linked_raw, list):
            linked_raw = []
        scenario_id = (
            raw_scenario.get("scenarioId")
            if isinstance(raw_scenario.get("scenarioId"), str) and raw_scenario["scenarioId"].startswith("adp_s_")
            else f"adp_s_{chapter['chapterId']}_{s + 1:02d}"
        )
        block_total = len(linked_raw) or MCQS_PER_SCENARIO
        scenario_refs = {
            "icaiSourceRefs": normalize_refs(_first(raw_scenario, ("icaiSourceRefs", "sourceRefs", "references")), "module"),
            "calibrationRefs": normalize_refs(_first(raw_scenario, ("calibrationRefs", "calibration")), "RTP"),
        }
        qids: list[str] = []
        for k, raw_q in enumerate(linked_raw):
            if not isinstance(raw_q, dict):
                continue
            seq += 1
            question = build_question(
                raw_q,
                chapter,
                seq,
                question_type="scenario_mcq",
                scenario_link={"scenarioId": scenario_id, "seq": k + 1, "blockTotal": block_total},
                scenario_refs=scenario_refs,
                generated_at=generated_at,
                source_path=source_path,
                derive_refs=derive_refs,
            )
            questions.append(question)
            qids.append(question["id"])
        scenarios.append(
            build_scenario(
                raw_scenario,
                chapter,
                s + 1,
                qids,
                generated_at=generated_at,
                source_path=source_path,
                derive_refs=derive_refs,
            )
        )

    return {"chapter": chapter, "questions": questions, "scenarios": scenarios, "path": source_path}


# ───────────────────────────────── demo purge ──────────────────────────────
def _demo_students() -> list[str]:
    try:
        from seed_demo import DEMO_STUDENTS  # noqa: WPS433 — module-level constants only

        return list(DEMO_STUDENTS)
    except Exception:  # pragma: no cover
        return ["S-1001", "S-1002", "S-1003", "S-1004", "S-1005", "S-1006"]


def _demo_chapter_ids() -> list[str]:
    try:
        from seed_demo import CHAPTERS as DEMO_CHAPTERS

        return [c["chapterId"] for c in DEMO_CHAPTERS]
    except Exception:  # pragma: no cover
        return ["ch-acc-01", "ch-law-03"]


async def purge_demo(db) -> dict[str, int]:
    """Delete everything `SEED_DEMO=1` / seed_demo.py created."""
    students = _demo_students()
    chapters = _demo_chapter_ids()
    deleted: dict[str, int] = {}

    async def _delete(collection: str, query: dict):
        result = await db[collection].delete_many(query)
        deleted[collection] = deleted.get(collection, 0) + int(getattr(result, "deleted_count", 0) or 0)

    await _delete(
        CONTENT_QUESTIONS,
        {
            "$or": [
                {"generationMeta.model": "demo-seed"},
                {"chapterId": {"$in": chapters}},
                {"id": {"$regex": "^adp_q_ch-"}},
                {"prompt": {"$regex": "^DEMO "}},
            ]
        },
    )
    await _delete(
        CONTENT_SCENARIOS,
        {
            "$or": [
                {"chapterId": {"$in": chapters}},
                {"scenarioId": {"$regex": "^adp_s_ch-"}},
                {"passage": {"$regex": "^DEMO "}},
            ]
        },
    )
    await _delete(CONTENT_CHAPTERS, {"chapterId": {"$in": chapters}})
    await _delete(CONTENT_AUDIT, {"by": "demo-seed"})
    await _delete(ANALYTICS_CONSENTS, {"studentId": {"$in": students}})
    await _delete(ANALYTICS_SUMMARIES, {"studentId": {"$in": students}})
    await _delete(ANALYTICS_TRENDS, {"studentId": {"$in": students}})
    await _delete(ANALYTICS_AUDIT_SYNC, {"studentId": {"$in": students}})
    await _delete(
        ANALYTICS_FOLLOWUPS,
        {"$or": [{"followupId": {"$regex": "^demo-"}}, {"createdBy": "demo-seed"}, {"title": {"$regex": "^DEMO"}}]},
    )
    return deleted


# ───────────────────────────────── upserts ─────────────────────────────────
async def _upsert_question(db, doc: dict, force: bool, stats: dict):
    existing = await db[CONTENT_QUESTIONS].find_one({"id": doc["id"]}, sort=[("revision", -1)])
    if existing:
        if existing.get("status") in MENTOR_TOUCHED and not force:
            stats["questions_protected"] += 1
            return
        if existing.get("contentHash") == doc.get("contentHash") and not force:
            stats["questions_unchanged"] += 1
            return
        doc["revision"] = int(existing.get("revision", 1))
        history = list(existing.get("statusHistory") or [])
        history.append(
            {
                "from": existing.get("status"),
                "to": "needs_review",
                "by": IMPORTER,
                "at": _now(),
                "note": "re-imported from generated bundle",
            }
        )
        doc["statusHistory"] = history
        await db[CONTENT_QUESTIONS].replace_one({"id": doc["id"]}, doc)
        stats["questions_updated"] += 1
    else:
        await db[CONTENT_QUESTIONS].insert_one(dict(doc))
        stats["questions_inserted"] += 1


async def _upsert_scenario(db, doc: dict, force: bool, stats: dict):
    existing = await db[CONTENT_SCENARIOS].find_one({"scenarioId": doc["scenarioId"]})
    if existing:
        if existing.get("status") in MENTOR_TOUCHED and not force:
            stats["scenarios_protected"] += 1
            return
        if existing.get("contentHash") == doc.get("contentHash") and not force:
            stats["scenarios_unchanged"] += 1
            return
        doc["revision"] = int(existing.get("revision", 1))
        history = list(existing.get("statusHistory") or [])
        history.append(
            {
                "from": existing.get("status"),
                "to": "needs_review",
                "by": IMPORTER,
                "at": _now(),
                "note": "re-imported from generated bundle",
            }
        )
        doc["statusHistory"] = history
        await db[CONTENT_SCENARIOS].replace_one({"scenarioId": doc["scenarioId"]}, doc)
        stats["scenarios_updated"] += 1
    else:
        await db[CONTENT_SCENARIOS].insert_one(dict(doc))
        stats["scenarios_inserted"] += 1


async def _upsert_chapter(db, chapter: dict, questions: list[dict], scenarios: list[dict], source_path: str):
    plain = len([q for q in questions if q["questionType"] == "mcq"])
    scenario_mcqs = len([q for q in questions if q["questionType"] == "scenario_mcq"])
    await db[CONTENT_CHAPTERS].update_one(
        {"chapterId": chapter["chapterId"]},
        {
            "$set": {
                **chapter,
                "status": "needs_review",
                "coverage": {
                    "plainApproved": 0,
                    "plainTarget": PLAIN_TARGET,
                    "scenariosApproved": 0,
                    "scenariosTarget": SCENARIO_TARGET,
                    "scenarioMcqsApproved": 0,
                    "scenarioMcqsTarget": SCENARIO_TARGET * MCQS_PER_SCENARIO,
                },
                "imported": {
                    "plain": plain,
                    "scenarios": len(scenarios),
                    "scenarioMcqs": scenario_mcqs,
                    "sourceFile": source_path,
                    "importedAt": _now(),
                    "importedBy": IMPORTER,
                },
                "updatedAt": _now(),
            }
        },
        upsert=True,
    )


# ─────────────────────────────── orchestration ─────────────────────────────
def new_stats() -> dict:
    return {
        "files": 0,
        "chapters": 0,
        "questions_inserted": 0,
        "questions_updated": 0,
        "questions_unchanged": 0,
        "questions_protected": 0,
        "scenarios_inserted": 0,
        "scenarios_updated": 0,
        "scenarios_unchanged": 0,
        "scenarios_protected": 0,
        "questions_with_errors": 0,
        "skipped_files": 0,
    }


async def run_import(
    generated_dir: Optional[str] = None,
    *,
    purge_demo_data: bool = True,
    force: bool = False,
    dry_run: bool = False,
    only_chapters: Optional[list[str]] = None,
    limit: Optional[int] = None,
    derive_refs: bool = True,
    quiet: bool = False,
) -> dict:
    """Import every generated chapter into the backend DB. Returns a report."""
    resolved = detect_generated_dir(generated_dir)
    log = (lambda *a: None) if quiet else print

    if resolved is None:
        log("[import] no generated content directory found. Looked in:")
        for candidate in candidate_dirs()[:8]:
            log(f"          - {candidate}")
        log("[import] set GENERATED_DIR=/path/to/content-pipeline/generated and re-run.")
        return {"ok": False, "reason": "generated_dir_not_found", "generatedDir": None, "stats": new_stats()}

    catalog = load_catalog()
    files = iter_chapter_files(resolved)
    log(f"[import] generated dir : {resolved}")
    log(f"[import] json files     : {len(files)} (catalog: {len(catalog)} chapters, revision {catalog_revision()})")

    db = None if dry_run else get_db()
    if db is not None:
        await ensure_indexes()

    demo_deleted: dict[str, int] = {}
    if purge_demo_data and not dry_run:
        demo_deleted = await purge_demo(db)
        total_demo = sum(demo_deleted.values())
        log(f"[import] demo records deleted: {total_demo} {demo_deleted if total_demo else ''}")

    stats = new_stats()
    problems: list[dict] = []
    chapters_seen: list[str] = []

    for path in files:
        converted = convert_file(path, catalog, derive_refs=derive_refs)
        if converted is None:
            stats["skipped_files"] += 1
            continue
        if converted.get("error"):
            stats["skipped_files"] += 1
            problems.append({"file": str(path), "error": converted["error"]})
            continue

        chapter = converted["chapter"]
        if only_chapters and chapter["chapterId"] not in only_chapters:
            continue
        if limit is not None and stats["chapters"] >= limit:
            break

        stats["files"] += 1
        stats["chapters"] += 1
        chapters_seen.append(chapter["chapterId"])

        questions, scenarios = converted["questions"], converted["scenarios"]
        stats["questions_with_errors"] += len([q for q in questions if q["validation"]["errors"]])

        plain_count = len([q for q in questions if q["questionType"] == "mcq"])
        scenario_mcq_count = len([q for q in questions if q["questionType"] == "scenario_mcq"])
        if plain_count != PLAIN_TARGET or len(scenarios) != SCENARIO_TARGET or scenario_mcq_count != SCENARIO_TARGET * MCQS_PER_SCENARIO:
            problems.append(
                {
                    "file": str(path),
                    "chapterId": chapter["chapterId"],
                    "warning": f"coverage {plain_count}/{PLAIN_TARGET} plain, {len(scenarios)}/{SCENARIO_TARGET} scenarios, "
                    f"{scenario_mcq_count}/{SCENARIO_TARGET * MCQS_PER_SCENARIO} scenario MCQs",
                }
            )

        if dry_run:
            stats["questions_inserted"] += len(questions)
            stats["scenarios_inserted"] += len(scenarios)
            continue

        for question in questions:
            await _upsert_question(db, question, force, stats)
        for scenario in scenarios:
            await _upsert_scenario(db, scenario, force, stats)
        await _upsert_chapter(db, chapter, questions, scenarios, str(path))

    report = {
        "ok": True,
        "dryRun": dry_run,
        "generatedDir": str(resolved),
        "stats": stats,
        "demoDeleted": demo_deleted,
        "problems": problems[:50],
        "chapters": chapters_seen,
    }

    log(
        "[import] chapters: {chapters} | questions +{questions_inserted} ~{questions_updated} "
        "={questions_unchanged} (mentor-locked {questions_protected}) | scenarios +{scenarios_inserted} "
        "~{scenarios_updated} ={scenarios_unchanged}".format(**stats)
    )
    if stats["questions_with_errors"]:
        log(f"[import] questions carrying validation errors (visible to the mentor): {stats['questions_with_errors']}")
    if problems:
        log(f"[import] {len(problems)} file-level warning(s); first few:")
        for item in problems[:5]:
            log(f"          - {item}")
    if dry_run:
        log("[import] DRY RUN — nothing was written.")
    return report


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Import generated chapter JSON into the mentor backend DB.")
    parser.add_argument("--generated-dir", default=os.environ.get("GENERATED_DIR"), help="path to content-pipeline/generated")
    parser.add_argument("--chapter", action="append", dest="chapters", help="import only this chapterId (repeatable)")
    parser.add_argument("--limit", type=int, default=None, help="import at most N chapters")
    parser.add_argument("--dry-run", action="store_true", help="convert + validate only, write nothing")
    parser.add_argument("--force", action="store_true", help="overwrite mentor-touched documents too")
    parser.add_argument("--keep-demo", action="store_true", help="do NOT delete the SEED_DEMO demo records")
    parser.add_argument("--no-derive-refs", action="store_true", help="do not synthesise missing ICAI/calibration refs")
    parser.add_argument("--print-dir", action="store_true", help="print the detected generated dir and exit")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.print_dir:
        resolved = detect_generated_dir(args.generated_dir)
        print(resolved or "")
        return 0 if resolved else 1

    report = asyncio.run(
        run_import(
            args.generated_dir,
            purge_demo_data=not args.keep_demo,
            force=args.force,
            dry_run=args.dry_run,
            only_chapters=args.chapters,
            limit=args.limit,
            derive_refs=not args.no_derive_refs,
            quiet=args.json,
        )
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    if not report.get("ok"):
        return 2
    if settings.mongo_url == "memory://" and not args.dry_run:
        print(
            "[import] NOTE: MONGO_URL=memory:// — this store is per-process. "
            "run-backend.sh imports in-process at startup (IMPORT_GENERATED=1); "
            "set MONGO_URL to a real MongoDB to persist."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
