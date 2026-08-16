"""Synthetic content fixtures for backend tests (mirrors the pipeline's
canonical model; demo content only)."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db import (  # noqa: E402
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    ensure_indexes,
    get_db,
)

CHAPTER = {
    "chapterId": "ch-acc-01",
    "subject": "Accounting",
    "paper": "Paper 1",
    "section": "Accounting Standards",
    "module": "Module 1",
    "chapterNumber": 1,
    "chapterTitle": "Introduction to Accounting Standards",
    "group": "Group 1",
}


def make_question(chapter, i, question_type="mcq", scenario=None):
    n = f"{i:02d}"
    return {
        "id": f"adp_q_{chapter['chapterId']}_{n}",
        "revision": 1,
        "chapterId": chapter["chapterId"],
        "subject": chapter["subject"],
        "paper": chapter["paper"],
        "section": chapter["section"],
        "module": chapter["module"],
        "chapterNumber": chapter["chapterNumber"],
        "chapterTitle": chapter["chapterTitle"],
        "questionType": question_type,
        "difficulty": ["easy", "moderate", "hard"][i % 3],
        "conceptTags": ["accounting-standards-framework", "applicability"],
        "prompt": f"Question {n}: which statement about accounting standards is correct in point {n}?",
        "options": [
            {"id": "A", "text": f"Statement A for point {n}"},
            {"id": "B", "text": f"Statement B for point {n}"},
            {"id": "C", "text": f"Statement C for point {n}"},
            {"id": "D", "text": f"Statement D for point {n}"},
        ],
        "correctOptionId": "A",
        "explanation": f"Explanation {n}: standards bring comparability and consistency; the other options misstate the requirement.",
        "icaiSourceRefs": [{"source": "module", "module": "Module 1", "chapter": 1, "section": f"1.{i % 7 + 1}", "edition": "May 2026"}],
        "calibrationRefs": [{"source": "MTP", "attempt": "May 2026", "questionRef": f"Q{i % 10 + 1}"}],
        "generationMeta": {"model": "fixture", "promptVersion": "1.0.0", "generatedAt": datetime.now(timezone.utc).isoformat()},
        "scenario": scenario,
        "attemptSpecificRisk": False,
        "status": "needs_review",
        "statusHistory": [{"from": "generated", "to": "needs_review", "by": "fixture", "at": datetime.now(timezone.utc).isoformat()}],
        "validation": {"errors": [], "warnings": []},
        "similarity": {"verdict": "clean"},
    }


def make_scenario(chapter, s):
    scenario_id = f"adp_s_{chapter['chapterId']}_{s:02d}"
    qids = []
    questions = []
    for k in range(4):
        seq = 31 + (s - 1) * 4 + k
        link = {"scenarioId": scenario_id, "seq": k + 1, "blockTotal": 4}
        q = make_question(chapter, seq, "scenario_mcq", link)
        questions.append(q)
        qids.append(q["id"])
    return {
        "scenarioId": scenario_id,
        "revision": 1,
        "chapterId": chapter["chapterId"],
        "passage": f"Case study {s}: a hypothetical entity applies accounting standards to a practical situation involving points {s}1 through {s}4.",
        "icaiSourceRefs": [{"source": "module", "module": "Module 1", "chapter": 1, "section": f"2.{s}", "edition": "May 2026"}],
        "calibrationRefs": [{"source": "RTP", "attempt": "May 2026", "questionRef": f"Case {s}"}],
        "attemptSpecificRisk": False,
        "questionIds": qids,
        "status": "needs_review",
        "statusHistory": [{"from": "generated", "to": "needs_review", "by": "fixture", "at": datetime.now(timezone.utc).isoformat()}],
        "validation": {"errors": [], "warnings": []},
    }, questions


async def seed_full_chapter(chapter=None, status="needs_review"):
    chapter = chapter or CHAPTER
    db = get_db()
    plain = [make_question(chapter, i + 1) for i in range(30)]
    scenarios, scenario_questions = [], []
    for s in range(1, 6):
        sc, qs = make_scenario(chapter, s)
        scenarios.append(sc)
        scenario_questions.extend(qs)
    for q in plain + scenario_questions:
        q["status"] = status
        await db[CONTENT_QUESTIONS].insert_one(q)
    for s in scenarios:
        s["status"] = status
        await db[CONTENT_SCENARIOS].insert_one(s)
    await db[CONTENT_CHAPTERS].insert_one({
        "chapterId": chapter["chapterId"],
        "chapterTitle": chapter["chapterTitle"],
        "subject": chapter["subject"],
        "group": chapter["group"],
        "catalogMatch": {"valid": True, "catalogRevision": "may-2026"},
        "coverage": {"plainApproved": 0, "plainTarget": 30, "scenariosApproved": 0, "scenariosTarget": 5, "scenarioMcqsApproved": 0, "scenarioMcqsTarget": 20},
        "status": status,
    })
    return {"plain": plain, "scenarios": scenarios, "scenarioQuestions": scenario_questions}


def seed_sync(fn):
    """Run an async seeding function inside asyncio (separate loop per test)."""
    asyncio.run(fn())
