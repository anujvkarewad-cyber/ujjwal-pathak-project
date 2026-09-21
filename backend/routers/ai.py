"""AI Study Assistant backend — POST /api/ai/ask.

Live mode  : Groq RAG over the bundled 94-chapter CA Inter catalog
             (set GROQ_API_KEY env — free tier, no card required).
Offline    : structured syllabus-brain answer built from the catalog,
             so the assistant ALWAYS answers even without a key.

English only. The app enforces the "finished chapters only" unlock
policy (Learn tab); this endpoint serves the app's requests.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

router = APIRouter(prefix="/api/ai", tags=["ai"])

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "chapters.json"

_CHAPTERS: list = []


def _load_catalog() -> list:
    global _CHAPTERS
    if _CHAPTERS:
        return _CHAPTERS
    try:
        raw = json.loads(CATALOG_PATH.read_text())
        _CHAPTERS = raw["chapters"] if isinstance(raw, dict) else raw
    except Exception:
        _CHAPTERS = []
    return _CHAPTERS


class AskBody(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    chapterId: Optional[str] = None


_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "for", "and",
         "or", "to", "what", "which", "how", "why", "when", "explain", "define", "about",
         "tell", "me", "please", "with", "from", "this", "that", "it", "its", "at", "by"}


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z']+", text.lower()) if t not in _STOP and len(t) > 2}


def match_chapter(question: str, chapter_id: Optional[str] = None):
    chapters = _load_catalog()
    if chapter_id:
        for c in chapters:
            if c.get("chapterId") == chapter_id:
                return c
    qt = _tokens(question)
    if not qt:
        return None
    best, best_score = None, 0.0
    for c in chapters:
        ct = _tokens(f"{c.get('chapterTitle','')} {c.get('subject','')}")
        if not ct:
            continue
        overlap = len(qt & ct)
        score = overlap / min(len(qt), len(ct))
        if overlap and score > best_score:
            best, best_score = c, score
    return best if best_score >= 0.25 else None


_SUBJECT_GUIDE = {
    "Accounts": "structure your answer as: (1) applicable Accounting Standard / Ind AS, (2) recognition principle, (3) measurement basis, (4) presentation & disclosure. Practice the ICAI module illustrations and the chapter's RTP/MTP questions.",
    "Law": "answer with the exact section number, the conditions/thresholds, and the consequence (penalty/void/voidable). Compare similar provisions in a table. Solve ICAI module MCQs plus RTP/MTP case scenarios.",
    "Taxation": "answer step by step: head of income / supply type, applicability conditions, computation sequence, rates and due dates. For GST cover charge, place/time/value of supply and ITC restrictions. Practice ICAI illustrations and RTP/MTP computations.",
    "Costing": "lead with the method's purpose, the core formula sheet lines, and the statement/cost-sheet format. Always show workings. Practise ICAI module questions and RTP/MTP numericals.",
    "Audit": "cite the Standard on Auditing number, the objective, the required documentation and the reporting impact. Link assertions to evidence. Revise ICAI module Q&As and RTP/MTP exam cases.",
    "FM": "state the concept, the formula, the assumption and the decision rule, then compute. Cover ratio analysis, cost of capital, capital structure theories and working capital cycle. Practise RTP/MTP sums.",
    "SM": "apply a framework explicitly (SWOT / PESTEL / Porter's forces / value chain), then analyse, choose and justify the strategy. Use ICAI module cases and RTP/MTP scenario questions.",
}


def offline_answer(question: str, chapter: Optional[dict]) -> str:
    if not chapter:
        return ("I cover the full CA Inter syllabus: Accounts, Law, Taxation, Costing, "
                "Audit, FM and SM (94 chapters). Ask me about a specific chapter, e.g. "
                '"Input Tax Credit" or "Audit Report", or type "quiz me on <chapter>".')
    title = chapter.get("chapterTitle", "")
    subject = chapter.get("subject", "")
    guide = _SUBJECT_GUIDE.get(subject, _SUBJECT_GUIDE["Accounts"])
    return (f"📘 {title} ({subject})\n\n"
            f"Your question: \"{question}\"\n\n"
            f"How to approach this chapter in exams: {guide}\n\n"
            f"Study loop for this chapter: read the ICAI module paragraph → memorise the "
            f"section/standard/formula list → solve 10 module MCQs → attempt the chapter's "
            f"RTP and MTP questions → re-attempt wrong ones after 3 days.\n\n"
            f"(Full AI explanations activate automatically once the mentor connects the AI key — "
            f"until then I answer with this syllabus brain.)")


async def groq_answer(question: str, chapter: Optional[dict]) -> Optional[str]:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    ctx = ""
    if chapter:
        ctx = (f"Current chapter context: {chapter.get('chapterTitle')} "
               f"(subject {chapter.get('subject')}, {chapter.get('module','')}). ")
    system = (
        "You are the Ujjwal Pathak Mentorship AI Study Assistant for CA Inter students. "
        "Answer ONLY in English. Be a strict but encouraging mentor. Use the ICAI study-module "
        "perspective; where relevant mention the applicable section/standard/formula, a short "
        "worked example, common exam traps, and one RTP/MTP practice pointer. Keep answers under "
        "250 words, use short bullet points, no markdown headers."
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "temperature": 0.4,
                    "max_tokens": 700,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": ctx + "Student question: " + question},
                    ],
                },
            )
        if r.status_code != 200:
            return None
        return (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or None
    except Exception:
        return None


@router.post("/ask")
async def ask(body: AskBody):
    chapter = match_chapter(body.question, body.chapterId)
    answer = await groq_answer(body.question, chapter)
    if not answer:
        answer = offline_answer(body.question, chapter)
    return {
        "answer": answer,
        "mode": "live" if (os.environ.get("GROQ_API_KEY") or "").strip() else "syllabus-brain",
        "chapter": {"id": chapter.get("chapterId"), "title": chapter.get("chapterTitle"),
                    "subject": chapter.get("subject")} if chapter else None,
    }
