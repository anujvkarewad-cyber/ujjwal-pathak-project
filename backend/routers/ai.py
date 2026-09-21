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
        from data_chapters import CATALOG  # bundled with the serverless fn
        _CHAPTERS = list(CATALOG)
        return _CHAPTERS
    except Exception:
        pass
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


_SMALLTALK = {
    "hi": "Hello! 👋 Ready to study? Tell me a chapter name or type your doubt.",
    "hello": "Hello! 👋 Which chapter shall we revise today?",
    "hey": "Hey! 💪 In study mode? Ask me any syllabus doubt.",
    "gm": "Good morning! ☀️ Start the day with one chapter — which one?",
    "good morning": "Good morning! ☀️ Start the day with one chapter — which one?",
    "thanks": "You're welcome! Keep going — consistency beats talent. 📚",
    "thank you": "You're welcome! Keep going — consistency beats talent. 📚",
    "ok": "Great! Ask me your next doubt whenever ready.",
    "bye": "All the best! 🍀 Come back after your study session for a revision round.",
}


def _smalltalk(question: str) -> Optional[str]:
    q = question.strip().lower().rstrip("!.,")
    if q in _SMALLTALK:
        return _SMALLTALK[q]
    return None


def offline_answer(question: str, chapter: Optional[dict]) -> str:
    if not chapter:
        return ("I cover the full CA Inter syllabus: Accounts, Law, Taxation, Costing, "
                "Audit, FM and SM (94 chapters). Ask me about a specific chapter, e.g. "
                '"Input Tax Credit" or "Audit Report", or type "quiz me on <chapter>".')
    title = chapter.get("chapterTitle", "")
    subject = chapter.get("subject", "")
    guide = _SUBJECT_GUIDE.get(subject, _SUBJECT_GUIDE["Accounts"])
    return (f"📘 {title} ({subject}) — ICAI answer format\n\n"
            f"Provision: identify and cite the exact section/standard/formula governing "
            f"\"{question}\".\n"
            f"Points: bullet the conditions, recognition/measurement rules and disclosures.\n"
            f"Application: apply each point to the case facts given in the question.\n"
            f"Conclusion: close with one decisive 'Hence, ...' sentence.\n\n"
            f"Chapter exam strategy: {guide}\n\n"
            f"Study loop: ICAI module paragraph → memorise section/standard/formula list → "
            f"10 module MCQs → RTP & MTP questions of this chapter → re-attempt wrong ones "
            f"after 3 days.\n\n"
            f"(Deep model answers in exact ICAI wording activate automatically once the mentor "
            f"connects the free AI key — until then I coach you with this syllabus brain.)")


async def groq_answer(question: str, chapter: Optional[dict]) -> Optional[str]:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    ctx = ""
    if chapter:
        ctx = (f"Current chapter context: {chapter.get('chapterTitle')} "
               f"(subject {chapter.get('subject')}, {chapter.get('module','')}). ")
    system = (
        "You are the Ujjwal Pathak Mentorship AI Study Assistant for CA Inter students "
        "(ICAI new scheme). Trained on ICAI study modules, RTPs (Dec 21 to May 26) and PYQs. "
        "Answer ONLY in English, in ICAI model-answer style.\n"
        "STRICT ANSWER FORMAT RULES:\n"
        "1. THEORY / LAW / AUDIT questions: use headed bullet points exactly like ICAI model "
        "answers: 'Provision:' (cite exact section/rule/SA/Ind AS number) -> bullet the "
        "conditions/requirements -> 'Application:' apply to the case facts -> 'Conclusion:' "
        "one decisive sentence ('Hence, ...'). Define terms first when asked 'what is/define'.\n"
        "2. NUMERICAL questions (FM / Costing / Tax): ONLY if you are confident, start with an "
        "'Assumptions:' block listing every assumption ICAI would state (e.g. dates, rates, "
        "sections applied, treatment chosen when law allows alternatives), then 'Computation:' "
        "as a step-by-step table-like list with figures, then 'Working Notes:' and a bold final "
        "answer line. If not confident, say so and give the method + formula instead.\n"
        "3. SMALL TALK: if the student says hi/hello/gm/thanks or casual chat, reply warmly and "
        "briefly like a friendly mentor, then gently offer a study action (e.g. ask which "
        "chapter to revise). Never be rude.\n"
        "4. MCQ help: give the correct option AND a 2-3 line ICAI-style reason citing the "
        "provision.\n"
        "5. Keep answers under 300 words, plain-text bullet points (no markdown headers), "
        "exam-focused, mention one RTP/MTP practice pointer when relevant."
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "openai/gpt-oss-120b",
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
    chit = _smalltalk(body.question)
    if chit:
        return {"answer": chit, "mode": "chitchat", "chapter": None}
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
