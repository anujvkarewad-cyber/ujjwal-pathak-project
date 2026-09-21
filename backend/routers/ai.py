"""AI Study Assistant backend — POST /api/ai/ask.

Live mode  : Groq RAG over 94-chapter catalog + 170 curated provision anchors.
             (GROQ_API_KEY env - free tier)
Offline    : structured syllabus-brain answer from catalog, so ALWAYS answers.

v3: ChatGPT-style mentoring — simple first, exam-insight, brutal truth, CTA.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    import httpx
except Exception:
    httpx = None

router = APIRouter(prefix="/api/ai", tags=["ai"])

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "chapters.json"
_CHAPTERS: list = []


def _load_catalog() -> list:
    global _CHAPTERS
    if _CHAPTERS:
        return _CHAPTERS
    try:
        from data_chapters import CATALOG
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
         "tell", "me", "please", "with", "from", "this", "that", "it", "its", "at", "by",
         "does", "do", "detail", "details", "section", "sec"}

def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOP and len(t) > 1}


def retrieve_anchors(question: str, limit: int = 5) -> List[str]:
    from data_section_map import ANCHORS, SECNUM
    picked: List[str] = []
    for m in re.finditer(r"(?:section|sec\.?)\s*([0-9]{1,3}[a-z]?(?:\([0-9]+\))?)", question.lower()):
        raw_num = m.group(1)
        base = re.match(r"([0-9]+[a-z]?)", raw_num)
        num = base.group(1) if base else raw_num
        if num in SECNUM and SECNUM[num] not in picked:
            picked.append(SECNUM[num])
        elif raw_num in SECNUM and SECNUM[raw_num] not in picked:
            picked.append(SECNUM[raw_num])
    qt = _tokens(question)
    if qt and len(picked) < limit:
        scored = []
        for keywords, text in ANCHORS:
            kt = set()
            for k in keywords:
                kt |= _tokens(k)
            overlap = qt & kt
            if overlap:
                scored.append((len(overlap), text))
        scored.sort(key=lambda x: -x[0])
        for _, text in scored:
            if len(picked) >= limit:
                break
            if text not in picked:
                picked.append(text)
    return picked


def match_chapter(question: str, chapter_id: Optional[str] = None):
    chapters = _load_catalog()
    if chapter_id:
        for c in chapters:
            if c.get("chapterId") == chapter_id:
                return c
    has_secnum = bool(re.search(r"(?:section|sec\.?)\s*[0-9]{1,3}", question.lower()))
    qt = _tokens(question)
    if not qt:
        return None
    best, best_score = None, 0.0
    for c in chapters:
        ct = _tokens(f"{c.get('chapterTitle','')} {c.get('subject','')}")
        if not ct:
            continue
        overlap = len(qt & ct)
        score = overlap / max(1, min(len(qt), len(ct)))
        subj = c.get('subject','')
        if has_secnum and ('companies act' in question.lower() or 'section' in question.lower()):
            if subj == 'Law' and overlap >= 1:
                score += 0.15
            if 'amalgamation' in c.get('chapterTitle','').lower() and '43' in question.lower():
                score -= 0.5
        if overlap and score > best_score:
            best, best_score = c, score
    threshold = 0.40
    return best if best_score >= threshold else None


_SUBJECT_GUIDE = {
    "Accounts": "structure: applicable AS/Ind AS, recognition, measurement, presentation & disclosure.",
    "Law": "answer with exact section number, conditions/thresholds, consequence.",
    "Taxation": "step by step: head/supply type, applicability, computation sequence.",
    "Costing": "lead with method purpose, core formulas, statement format.",
    "Audit": "cite SA number, objective, documentation, reporting impact.",
    "FM": "state concept, formula, assumption, decision rule, then compute.",
    "SM": "apply framework explicitly (SWOT/PESTEL/Porter/value chain).",
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
        anchors = retrieve_anchors(question, 3)
        if anchors:
            return ("📘 ICAI Provision\n\n" + "\n".join([f"• {a}" for a in anchors]) +
                    f"\n\nAsk more specifically, e.g. 'Explain {anchors[0].split('—')[0]} with example'")
        return ("I cover full CA Inter syllabus: Accounts, Law, Taxation, Costing, "
                "Audit, FM and SM (94 chapters). Ask about a specific topic.")
    title = chapter.get("chapterTitle", "")
    subject = chapter.get("subject", "")
    anchors = retrieve_anchors(question, 2)
    anchor_line = (" ".join(anchors) + "\n") if anchors else ""
    return (f"📘 {title} ({subject})\n\nProvision: {anchor_line}"
            f"Points: bullet conditions, rules, disclosures.\nApplication: apply to facts.\nConclusion: Hence, ...")


def _is_bad_answer(text: str) -> bool:
    if not text or len(text) < 50:
        return True
    low = text.lower()
    leak_markers = ["we need to answer:", "we must respond within ca inter", "but the question:", "we should answer", "as an ai"]
    first = low[:600]
    for m in leak_markers:
        if m in first and ("we need" in m or "we must" in m or "but the question" in m):
            return True
    if low.count("llp agreement") > 8:
        return True
    if low.count("includes the terms of the partnership") > 2:
        return True
    if low.count("includes the terms of the") > 5:
        return True
    sentences = [s.strip() for s in re.split(r"[.\n]", low) if len(s.strip()) > 25]
    from collections import Counter
    cnt = Counter(sentences)
    if cnt and cnt.most_common(1)[0][1] >= 4:
        return True
    return False


MODELS_PRIORITY = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]

SYSTEM_PROMPT = (
    "You are the Ujjwal Pathak Mentorship AI Study Assistant — a ChatGPT-level mentor for CA Inter only. "
    "ICAI new scheme: Advanced Accounting, Corporate & Other Laws, Costing, Taxation, Audit & Ethics, FM, SM. "
    "Answer in English only. Never output internal reasoning. Never say 'We need to answer' or 'We must respond'. "
    "Give ONLY final answer.\n"
    "CRITICAL GROUND-TRUTH RULE:\n"
    "- If AUTHORITATIVE PROVISION ANCHORS are provided, they are 100% CORRECT and must be used verbatim. Never contradict anchors.\n"
    "CHATGPT-STYLE MENTORING (MANDATORY):\n"
    "1. Start with 1-2 lines in SIMPLE plain English, like ChatGPT: what the section REALLY is. "
    "Example: 'Section 2 of the LLP Act, 2008 is not one single rule — it is the definitions section of the entire Act. In simple terms: it tells you what key terms in the LLP Act mean. Without this section, the rest of the law becomes vague.'\n"
    "2. Then 'What Section X Covers' — list ONLY 6-8 exam-relevant terms, not all 20 clauses. For each: 1-line definition + why it matters for exam.\n"
    "3. Then 'Important Exam Insight' — tell what NOT to mug, rookie mistakes. Example: 'Don't mug entire section blindly. Focus on definitions repeatedly used (LLP, partner, designated partner, LLP agreement).'\n"
    "4. Then 'Brutal Truth / How ICAI tests' — how ICAI links definitions to provisions. Example: 'Designated partner → penalties, compliance; LLP agreement → dispute resolution. ICAI doesn't test definitions in isolation — they test application.'\n"
    "5. Keep tone friendly mentor, like ChatGPT screenshot: conversational, occasional 👉 ⚠️ 💡, bullets, not textbook dumping. Use bold for key terms.\n"
    "6. End with engaging CTA: 'If you want, I can break down only the exam-relevant definitions + tricky MCQs + memory hacks, instead of this generic theory.'\n"
    "7. For LAW/AUDIT: still keep ICAI discipline Provision -> Points -> Application -> Conclusion, but keep simple intro first.\n"
    "8. For NUMERICALS: Assumptions -> Computation -> Working Notes -> final answer.\n"
    "9. For MCQs: correct option + 2-3 line reason.\n"
    "10. Keep 400-600 words, not 100, not 2000. ChatGPT depth but CA Inter only.\n"
)

async def groq_answer(question: str, chapter: Optional[dict]) -> Optional[str]:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    ctx_parts = []
    if chapter:
        ctx_parts.append(f"Current chapter: {chapter.get('chapterTitle')} ({chapter.get('subject')}).")
    anchors = retrieve_anchors(question, limit=5)
    if anchors:
        ctx_parts.append("AUTHORITATIVE PROVISION ANCHORS (GROUND TRUTH - MUST use verbatim, do not invent): " + " | ".join(anchors) + ".")
    ctx = " ".join(ctx_parts) + " " if ctx_parts else ""

    for model in MODELS_PRIORITY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.35,
                        "max_tokens": 1800,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": ctx + "Student question: " + question},
                        ],
                    },
                )
            if r.status_code != 200:
                continue
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            content = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning") or "").strip()
            final = content if len(content) > 20 else reasoning
            if not final or len(final) < 80:
                continue
            if _is_bad_answer(final):
                continue
            return final
        except Exception:
            continue
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
        mode = "syllabus-brain"
    else:
        mode = "live"
    return {
        "answer": answer,
        "mode": mode,
        "chapter": {"id": chapter.get("chapterId"), "title": chapter.get("chapterTitle"),
                    "subject": chapter.get("subject")} if chapter else None,
    }
