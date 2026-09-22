"""AI Study Assistant backend — POST /api/ai/ask.

v4: Proper RAG architecture as per ChatGPT/Claude feedback
- No more dumping entire syllabus
- Chunked knowledge base (200+ chunks) + 170 anchors + 94 chapters
- Search -> Retrieve top 5 relevant chunks -> Inject into Groq with strict prompt
- Structured CA Inter answers: direct answer, steps, exam tip
- Low temperature 0.2 for accuracy, no hallucination
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
    """Ground-truth provision anchors - 100% correct, must be used verbatim"""
    try:
        from data_section_map import ANCHORS, SECNUM
    except:
        return []
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


def retrieve_knowledge_chunks(question: str, limit: int = 5) -> List[dict]:
    """RAG Step 1-2: Search in database, get top relevant chunks"""
    try:
        from data_knowledge_base import search_knowledge_base
        return search_knowledge_base(question, limit=limit)
    except Exception as e:
        print(f"KB search failed: {e}")
        return []


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
    "hi": "Hello! Ready to study? Tell me a chapter name or type your doubt.",
    "hello": "Hello! Which chapter shall we revise today?",
    "hey": "Hey! In study mode? Ask me any syllabus doubt.",
    "gm": "Good morning! Start the day with one chapter — which one?",
    "good morning": "Good morning! Start the day with one chapter — which one?",
    "thanks": "You're welcome! Keep going — consistency beats talent.",
    "thank you": "You're welcome! Keep going — consistency beats talent.",
    "ok": "Great! Ask me your next doubt whenever ready.",
    "bye": "All the best! Come back after your study session for a revision round.",
}

def _smalltalk(question: str) -> Optional[str]:
    q = question.strip().lower().rstrip("!.,")
    if q in _SMALLTALK:
        return _SMALLTALK[q]
    return None


def offline_answer(question: str, chapter: Optional[dict]) -> str:
    """Fallback when Groq fails - uses RAG chunks"""
    chunks = retrieve_knowledge_chunks(question, 3)
    anchors = retrieve_anchors(question, 3)
    
    if chunks:
        content = "\n".join([f"- {c['topic']}: {c['content'][:300]}..." for c in chunks])
        return f"Relevant CA Inter Material:\n{content}\n\nBased on above, for your question: {question}\n\nPlease refer to the material above. For detailed explanation, ask more specifically."
    
    if anchors:
        return ("ICAI Provision\n\n" + "\n".join([f"• {a}" for a in anchors]) +
                f"\n\nAsk more specifically, e.g. 'Explain {anchors[0].split('—')[0]} with example'")
    return ("I cover full CA Inter syllabus: Accounts, Law, Taxation, Costing, "
            "Audit, FM and SM (94 chapters). Ask about a specific topic.")


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


# Updated models - using current Groq lineup (llama-3.3 is current)
MODELS_PRIORITY = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile", 
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "qwen-2.5-32b",
    "gemma2-9b-it"
]

# NEW SYSTEM PROMPT - as per Claude/ChatGPT feedback - strict RAG, exam-oriented
SYSTEM_PROMPT = """You are a CA Intermediate tutor. You help students preparing for the CA Intermediate exam (ICAI syllabus) understand concepts, solve problems, and revise using the study modules, RTPs, and PYQs provided to you.

CRITICAL RULES - NEVER BREAK:

1. GROUND YOUR ANSWER ONLY in the provided reference material (Relevant CA Inter Material + Authoritative Anchors). If retrieved material doesn't cover question, say "Not found in provided material" instead of guessing — NEVER invent sections, case law, provisions.

2. NEVER fabricate section numbers, case names, or figures. If unsure, say "not found in provided material" rather than guessing — CA exams penalize wrong provisions badly.

3. Answer strictly as per ICAI exam style:
   - Start with direct 1-2 line answer
   - Then explain with steps/working (especially for numericals in Costing, Accounts, Tax, Law)
   - Then end with short "exam tip" if relevant (common mistakes, marks-weightage, how ICAI phrases this in PYQs)

4. Structure for theory: point-wise, with headings/sub-points, not one giant paragraph. Use headings and bullet points. Mention section number if present in reference material.

5. For numericals: ALWAYS show working/calculation, assumptions first, then computation, working notes, final answer. Never just final answer.

6. For questions spanning multiple provisions, cite section/standard number if present in reference material.

7. Keep tone clear and encouraging but precise — exam prep, be precise over friendly. Like ChatGPT: simple first, then exam depth.

8. If student question ambiguous (which subject, which chapter), ask ONE clarifying question before answering.

9. If AUTHORITATIVE PROVISION ANCHORS are provided, they are 100% CORRECT and must be used verbatim. Never contradict anchors.

10. Keep 400-600 words, not 100, not 2000. ChatGPT depth but CA Inter only. No ** stars in output? Actually use bold via ** but UI will strip stars - so you CAN use **bold** for key terms.

11. Never output internal reasoning, never say "We need to answer" or "We must respond".

FINAL OUTPUT FORMAT (MANDATORY):
- Simple intro 1-2 lines in plain English (what this section really is)
- What Section X Covers / Key Concepts (bullets with bold terms)
- Important Exam Insight / How ICAI Tests (what NOT to mug, traps)
- If numerical: Assumptions -> Computation -> Working Notes -> Answer
- End with CTA: "Want me to break down exam-relevant points + MCQs + memory hacks?"

Language: English only.
"""

async def groq_answer(question: str, chapter: Optional[dict]) -> Optional[str]:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    
    # RAG STEP 1-2: Search database, get top relevant chunks
    knowledge_chunks = retrieve_knowledge_chunks(question, limit=5)
    anchors = retrieve_anchors(question, limit=3)
    
    ctx_parts = []
    if chapter:
        ctx_parts.append(f"Current chapter context: {chapter.get('chapterTitle')} ({chapter.get('subject')}).")
    
    # RAG STEP 3: Inject into prompt - Relevant Material
    if knowledge_chunks:
        material_text = "\n".join([
            f"[{c['id']}] {c['subject']} - {c['chapter']} - {c['topic']}: {c['content']}"
            for c in knowledge_chunks
        ])
        ctx_parts.append(f"Relevant CA Inter Material (use ONLY this, top 5 retrieved):\n{material_text}")
    
    if anchors:
        ctx_parts.append(f"AUTHORITATIVE PROVISION ANCHORS (GROUND TRUTH - MUST use verbatim, 100% correct): {' | '.join(anchors)}.")
    
    # Add subject guide if chapter matched
    if chapter and chapter.get('subject') in _SUBJECT_GUIDE:
        ctx_parts.append(f"Answer guide for {chapter.get('subject')}: {_SUBJECT_GUIDE[chapter.get('subject')]}")
    
    ctx = "\n\n".join(ctx_parts) + "\n\n" if ctx_parts else ""

    for model in MODELS_PRIORITY:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.2,  # Low temp for accuracy - as per Claude feedback
                        "max_tokens": 1500,
                        "top_p": 0.9,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": ctx + f"User Question: {question}\n\nInstructions: Answer ONLY using the above material. Keep exam-oriented. Use headings and bullet points. Mention section number. If not found, say 'Not available in provided material'."},
                        ],
                    },
                )
            if r.status_code != 200:
                print(f"Groq {model} failed {r.status_code}: {r.text[:200]}")
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
                print(f"Bad answer filtered from {model}")
                continue
            print(f"Groq {model} success: {len(final)} chars")
            return final
        except Exception as e:
            print(f"Groq {model} exception: {e}")
            continue
    return None


@router.post("/ask")
async def ask(body: AskBody):
    # Chit-chat
    chit = _smalltalk(body.question)
    if chit:
        return {"answer": chit, "mode": "chitchat", "chapter": None, "rag_chunks": 0}
    
    # RAG retrieval
    chapter = match_chapter(body.question, body.chapterId)
    knowledge_chunks = retrieve_knowledge_chunks(body.question, 5)
    anchors = retrieve_anchors(body.question, 3)
    
    # Groq with RAG
    answer = await groq_answer(body.question, chapter)
    if not answer:
        answer = offline_answer(body.question, chapter)
        mode = "syllabus-brain-rag"
    else:
        mode = "live-rag"
    
    return {
        "answer": answer,
        "mode": mode,
        "chapter": {"id": chapter.get("chapterId"), "title": chapter.get("chapterTitle"),
                    "subject": chapter.get("subject")} if chapter else None,
        "rag_chunks_used": len(knowledge_chunks),
        "anchors_used": len(anchors),
        "retrieved_topics": [c["topic"] for c in knowledge_chunks[:3]]
    }


@router.get("/kb-search")
async def kb_search(q: str, limit: int = 5):
    """Debug endpoint to test RAG search"""
    chunks = retrieve_knowledge_chunks(q, limit)
    anchors = retrieve_anchors(q, 3)
    return {
        "query": q,
        "chunks": chunks,
        "anchors": anchors,
        "count": len(chunks)
    }
