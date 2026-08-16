"""Public, read-only content for students.

- /manifest.json and /chunks/{platform}/{file} serve the contents of
  CONTENT_DIR (published bundles written by the pipeline's gated stage-11).
- /bank.json serves the LIVE practice bank — every mentor-approved /
  release_candidate / published question from the content store, mapped into
  the student-app question shape.

No draft content can be exposed by construction: the bundle routes only read
gated stage-11 output, and bank.json filters strictly on approved statuses.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from config import settings
from db import CONTENT_QUESTIONS, CONTENT_SCENARIOS, get_db

router = APIRouter(prefix="/api/content/student", tags=["student-content"])

MANIFEST_NAME = "published-manifest.json"
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_MANIFEST = "public, max-age=300"

# Live practice bank: only questions a mentor has actually acted on.
APPROVED_STATUSES = {"approved", "release_candidate", "published"}

_DIFFICULTY_MAP = {"easy": "Easy", "moderate": "Medium", "hard": "Hard"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _student_question(doc: dict, scenarios: dict) -> dict:
    """Mentor canonical question → student-app question shape.

    The student web/APK consume `{id, subject, kind, prompt, options[], answer,
    explanation, chapterId, chapter, chapterTitle, chapterNumber, chapterModule,
    chapterOrder, officialChapter, difficulty, caseStudy?}`.
    """
    options = [o for o in (doc.get("options") or []) if isinstance(o, dict)]
    texts = [o.get("text", "") for o in options]
    correct = doc.get("correctOptionId")
    answer = 0
    for i, o in enumerate(options):
        if o.get("id") == correct:
            answer = i
            break

    question_type = doc.get("questionType")
    kind = "case-study" if question_type == "scenario_mcq" else "normal"
    chapter_number = int(doc.get("chapterNumber") or 0)
    module = doc.get("module") or "Module 1"
    chapter_title = doc.get("chapterTitle") or doc.get("chapterId") or ""
    chapter = f"{module} · Chapter {chapter_number}: {chapter_title}"

    q = {
        "id": doc.get("id"),
        "subject": doc.get("subject"),
        "kind": kind,
        "prompt": doc.get("prompt"),
        "options": texts,
        "answer": answer,
        "explanation": doc.get("explanation"),
        "chapterId": doc.get("chapterId"),
        "chapter": chapter,
        "chapterTitle": chapter_title,
        "chapterNumber": chapter_number,
        "chapterModule": module,
        "chapterOrder": max(0, chapter_number - 1),
        "officialChapter": {
            "id": doc.get("chapterId"),
            "subject": doc.get("subject"),
            "paper": doc.get("paper") or "Paper 1",
            "module": module,
            "chapterNumber": chapter_number,
            "title": chapter_title,
            "officialTitle": chapter_title,
            "displayTitle": chapter,
            "catalogOrder": max(0, chapter_number - 1),
        },
        "difficulty": _DIFFICULTY_MAP.get(doc.get("difficulty"), "Medium"),
    }

    scenario_link = doc.get("scenario") or {}
    scenario_id = scenario_link.get("scenarioId")
    if kind == "case-study" and scenario_id and scenario_id in scenarios:
        sc = scenarios[scenario_id]
        q["caseStudy"] = {
            "title": f"Case: {chapter_title}",
            "passage": sc.get("passage") or "",
        }

    refs = doc.get("icaiSourceRefs") or []
    if refs:
        ref = refs[0]
        q["sourceRef"] = f"{ref.get('source', 'module')} · {ref.get('module', module)} · Chapter {chapter_number}"
    return q


@router.get("/bank.json")
async def live_bank():
    """Live practice bank: every mentor-approved / release-candidate / published
    question, in the student-app question shape. Public (student-facing)."""
    db = get_db()
    scenarios: dict = {}
    # Load the passage text for every scenario (not just approved ones): the
    # question itself is gated by its own approval status, while the passage is
    # static text needed to render an approved case-study MCQ meaningfully.
    async for s in db[CONTENT_SCENARIOS].find({}):
        scenarios[s["scenarioId"]] = s

    questions: list = []
    async for doc in db[CONTENT_QUESTIONS].find({"status": {"$in": list(APPROVED_STATUSES)}}).sort(
        [("chapterId", 1), ("id", 1)]
    ):
        questions.append(_student_question(doc, scenarios))

    return {
        "revision": "live-approved-v2",
        "generatedAt": _now(),
        "count": len(questions),
        "questions": questions,
    }


def _safe_path(relative: str) -> Path:
    root = settings.content_dir.resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root) + "/") and target != root:
        raise HTTPException(status_code=404, detail="Not found")
    return target


@router.get("/manifest.json")
async def manifest():
    target = _safe_path(MANIFEST_NAME)
    if not target.exists():
        return JSONResponse({"error": "No published content available"}, status_code=404)
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": CACHE_MANIFEST})


@router.get("/chunks/{platform}/{file_path:path}")
async def chunk(platform: str, file_path: str):
    if platform not in ("web", "mobile"):
        raise HTTPException(status_code=404, detail="Not found")
    if not file_path.endswith(".json"):
        raise HTTPException(status_code=404, detail="Not found")
    target = _safe_path(f"{platform}/{file_path}")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": CACHE_IMMUTABLE})
