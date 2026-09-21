"""AI Study Assistant backend — POST /api/ai/ask.

Live mode  : Groq RAG over 94-chapter catalog + 170 curated provision anchors.
             (GROQ_API_KEY env - free tier)
Offline    : structured syllabus-brain answer from catalog, so ALWAYS answers.

v2: ChatGPT-depth answers for ANY CA Inter question type, fast, accurate anchors.
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

# Tokens for matching (keep numbers for section detection separate)
def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOP and len(t) > 1}


def retrieve_anchors(question: str, limit: int = 5) -> List[str]:
    """Authoritative anchors: direct Section-N hits first, then keyword overlap."""
    from data_section_map import ANCHORS, SECNUM
    picked: List[str] = []
    # Direct section number detection - supports "Section 43", "Sec 43", "Sec 43(1)", "Sec 103"
    for m in re.finditer(r"(?:section|sec\.?)\s*([0-9]{1,3}[a-z]?(?:\([0-9]+\))?)", question.lower()):
        raw_num = m.group(1)
        # strip sub-clause e.g. 43(1) -> 43 for lookup, but keep original
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
    # If explicit section number is present, avoid false positive chapter match
    # unless the chapter title is strongly relevant to anchor keywords.
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
        # Jaccard-ish but penalize generic words
        score = overlap / max(1, min(len(qt), len(ct)))
        # If question is "Section 43 of Companies Act" -> we want Law chapter, not Accounts amalgamation
        # Boost Law chapters when question mentions Companies Act / law terms
        subj = c.get('subject','')
        if has_secnum and ('companies act' in question.lower() or 'section' in question.lower()):
            if subj == 'Law' and overlap >= 1:
                score += 0.15
            if 'amalgamation' in c.get('chapterTitle','').lower() and '43' in question.lower():
                score -= 0.5  # penalize wrong amalgamation match
        if overlap and score > best_score:
            best, best_score = c, score
    threshold = 0.40
    return best if best_score >= threshold else None


_SUBJECT_GUIDE = {
    "Accounts": "structure: applicable AS/Ind AS, recognition, measurement, presentation & disclosure. Practice ICAI module illustrations and RTP/MTP.",
    "Law": "answer with exact section number, conditions/thresholds, consequence. Compare similar provisions in table. Solve ICAI MCQs + RTP/MTP case scenarios.",
    "Taxation": "step by step: head/supply type, applicability, computation sequence, rates/due dates. For GST cover charge/place/time/value/ITC. Practice ICAI illustrations and RTP/MTP.",
    "Costing": "lead with method purpose, core formulas, statement/cost-sheet format. Show workings. Practise ICAI module + RTP/MTP.",
    "Audit": "cite SA number, objective, documentation, reporting impact. Link assertions to evidence. Revise ICAI Q&As and RTP/MTP cases.",
    "FM": "state concept, formula, assumption, decision rule, then compute. Cover ratios, cost of capital, capital structure, WC cycle. Practise RTP/MTP.",
    "SM": "apply framework explicitly (SWOT/PESTEL/Porter/value chain), analyse, choose, justify. Use ICAI module cases and RTP/MTP scenarios.",
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
            return (f"📘 ICAI Provision\n\n" + "\n".join([f"• {a}" for a in anchors]) +
                    f"\n\nAsk more specifically, e.g. 'Explain {anchors[0].split('—')[0]} with example' for full ICAI-format answer.")
        return ("I cover full CA Inter syllabus: Accounts, Law, Taxation, Costing, "
                "Audit, FM and SM (94 chapters). Ask about a specific topic, e.g. "
                "'Input Tax Credit' or 'Sec 43 Companies Act', or 'quiz me on <chapter>'.")
    title = chapter.get("chapterTitle", "")
    subject = chapter.get("subject", "")
    guide = _SUBJECT_GUIDE.get(subject, _SUBJECT_GUIDE["Accounts"])
    anchors = retrieve_anchors(question, 2)
    anchor_line = (" ".join(anchors) + "\n") if anchors else "identify exact section/standard/formula.\n"
    return (f"📘 {title} ({subject}) — ICAI answer format\n\n"
            f"Provision: {anchor_line}"
            f"Points: bullet conditions, recognition/measurement rules, disclosures.\n"
            f"Application: apply each point to case facts.\n"
            f"Conclusion: one decisive 'Hence, ...' sentence.\n\n"
            f"Exam strategy: {guide}\n\n"
            f"Study loop: ICAI module → memorise section/formula list → 10 MCQs → RTP & MTP → re-attempt after 3 days.\n\n"
            f"(Deep model answers activate once free AI key connected — until then syllabus brain.)")


# --- GROQ ---
MODELS_PRIORITY = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

SYSTEM_PROMPT = (
    "You are the Ujjwal Pathak Mentorship AI Study Assistant — a ChatGPT-level mentor "
    "restricted STRICTLY to CA Inter syllabus (ICAI new scheme: Advanced Accounting, "
    "Corporate & Other Laws, Costing, Taxation (DT+GST), Audit & Ethics, FM, SM). "
    "Trained on ICAI study modules, RTPs Dec-21 to May-26 and PYQs. Answer in English only.\n"
    "CRITICAL GROUND-TRUTH RULE:\n"
    "- If AUTHORITATIVE PROVISION ANCHORS are provided, they are 100% CORRECT and must be used verbatim. "
    "  Example: if anchor says 'Sec 43 = KINDS OF SHARE CAPITAL', you MUST answer that Sec 43 is Kinds of share capital, "
    "  NEVER say amalgamation/debentures/merger. Never contradict anchors. Never invent section numbers beyond anchors unless absolutely certain.\n"
    "BEHAVE LIKE CHATGPT WITHIN CA INTER SCOPE:\n"
    "- Answer EVERY type of student question fully and richly: definitions, section explanations with sub-clauses, "
    "  theory essays, comparisons/differences in tables, case-study applications, MCQs with reasons, numericals, "
    "  'explain simply', exam strategy, mnemonics, memory tricks.\n"
    "- Give COMPLETE detailed answers (ChatGPT style): Definition -> Exact provision (section/rule/AS/Ind AS/SA) -> "
    "  Point-wise conditions with thresholds/limits/exceptions -> Simple example -> Penalty/consequence -> Exam pointer "
    "  (how ICAI asks, common traps, one RTP/MTP pointer). Use headings, bullets, tables where helpful. "
    "  A 6-mark question deserves 400-600 words, not 100.\n"
    "- LAW/AUDIT: ICAI model-answer discipline: Provision -> Points -> Application to facts -> Conclusion ('Hence, ...').\n"
    "- NUMERICALS (FM/Costing/Tax): start with 'Assumptions:' (list every ICAI-style assumption, including chosen alternative), "
    "  then step-by-step 'Computation:' with figures, 'Working Notes:', final answer line. If unsure, teach method + formula.\n"
    "- MCQs: correct option + 2-3 line ICAI-style reason citing provision.\n"
    "- SMALL TALK (hi/hello/gm/thanks/bye): warm brief mentor reply, then steer to study.\n"
    "- OUT-OF-SCOPE (general knowledge, coding, personal advice etc.): one friendly line: you only mentor CA Inter, offer to link to syllabus if possible.\n"
    "Formatting: plain text with simple bullets; avoid code fences; you may use markdown tables for comparisons."
)

async def groq_answer(question: str, chapter: Optional[dict]) -> Optional[str]:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    ctx_parts = []
    if chapter:
        ctx_parts.append(f"Current chapter context: {chapter.get('chapterTitle')} (subject {chapter.get('subject')}, {chapter.get('module','')}).")
    anchors = retrieve_anchors(question, limit=5)
    if anchors:
        ctx_parts.append(
            "AUTHORITATIVE PROVISION ANCHORS (GROUND TRUTH - you MUST use these exact citations, do not invent or contradict): "
            + " | ".join(anchors) + "."
        )
    ctx = " ".join(ctx_parts) + " " if ctx_parts else ""

    for model in MODELS_PRIORITY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.2,
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
            # gpt-oss models sometimes put answer in reasoning
            content = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning") or "").strip()
            final = content if len(content) > 20 else reasoning
            if final and len(final) > 30:
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
