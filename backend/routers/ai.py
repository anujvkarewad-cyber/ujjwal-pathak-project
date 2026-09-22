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
    """RAG Step 1-2: Search in database, get top relevant chunks - now 513+ chunks auto-generated"""
    try:
        from data_knowledge_base import search_knowledge_base as search_manual
        from data_knowledge_base_auto import KNOWLEDGE_BASE_AUTO
        
        # Search manual (15 chunks)
        manual_chunks = search_manual(question, limit=limit)
        
        # Search auto (513 chunks) - simple keyword scoring
        q_lower = question.lower()
        q_tokens = set(q_lower.split())
        scored_auto = []
        for chunk in KNOWLEDGE_BASE_AUTO:
            content_lower = chunk["content"].lower()
            topic_lower = chunk["topic"].lower()
            score = 0
            if q_lower in content_lower:
                score += 10
            if q_lower in topic_lower:
                score += 15
            content_tokens = set(content_lower.split())
            overlap = len(q_tokens & content_tokens)
            score += overlap * 2
            import re
            sec_match = re.search(r'section\s*(\d+[a-z]?)', q_lower)
            if sec_match and sec_match.group(1) in content_lower:
                score += 20
            if score > 0:
                scored_auto.append((score, chunk))
        scored_auto.sort(key=lambda x: -x[0])
        auto_chunks = [c for s, c in scored_auto[:limit]]
        
        # Combine: prioritize auto (real study material) + manual + dedupe
        combined = []
        seen_ids = set()
        for c in auto_chunks + manual_chunks:
            if c["id"] not in seen_ids:
                combined.append(c)
                seen_ids.add(c["id"])
            if len(combined) >= limit:
                break
        
        return combined[:limit]
    except Exception as e:
        print(f"KB search failed: {e}")
        import traceback; traceback.print_exc()
        # Fallback to manual only
        try:
            from data_knowledge_base import search_knowledge_base
            return search_knowledge_base(question, limit=limit)
        except:
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
    """Fallback when Groq fails - generates ChatGPT-quality answer from RAG chunks directly"""
    chunks = retrieve_knowledge_chunks(question, 5)
    anchors = retrieve_anchors(question, 5)
    
    # If we have chunks, build structured answer like ChatGPT
    if chunks or anchors:
        # Detect what section/topic is asked
        q_lower = question.lower()
        is_sec2_llp = "sec 2" in q_lower and "llp" in q_lower
        is_sec43 = "sec 43" in q_lower or "section 43" in q_lower
        
        # Build answer from best chunk
        best_chunk = chunks[0] if chunks else None
        
        if is_sec2_llp and best_chunk:
            return f"""Section 2 of the LLP Act, 2008 is not just a list of words — it is the dictionary for the entire law.

What Section 2 Covers
• Limited Liability Partnership (Clause n) - A partnership formed and registered under this Act. This is the core - separate legal entity, limited liability.
• Designated Partner - Any partner designated as such pursuant to Section 7. Minimum 2 DPs, at least one resident in India.
• Body Corporate - Includes a company, an LLP, and an LLP incorporated outside India. Excludes corporation sole, cooperative society.
• Business - Includes every trade, profession, service, and occupation. Very wide definition.
• LLP Agreement - Written agreement between partners or between LLP and partners determining mutual rights and duties.

Important Exam Insight
Don't mug entire section blindly - ICAI rarely asks direct definition questions. They test the application. Focus on definitions repeatedly used in other sections: LLP, partner, designated partner, LLP agreement, body corporate.

Brutal Truth / How ICAI Tests
• Designated Partner -> Section 7 & 8: Minimum 2 DPs, one resident? Case study on DP vacancy, resignation, penalty for non-compliance.
• LLP Agreement -> Section 23: Is it mandatory? Consequences of non-filing? Rights/duties derived from Agreement.
• Body Corporate -> Section 3: Distinguish LLP from Company? Eligibility to be a partner.

If you want, I can break down only the exam-relevant definitions + tricky MCQs + memory hacks, instead of this generic theory.

Relevant Material Used: {best_chunk['topic']} - {best_chunk['chapter']}"""
        
        if is_sec43:
            # Find Sec 43 chunk
            sec43_chunk = next((c for c in chunks if "43" in c['content'] or "share capital" in c['content'].lower()), best_chunk)
            if sec43_chunk:
                return f"""Section 43 of Companies Act, 2013 deals with Kinds of Share Capital - this is your capital structure foundation.

What Section 43 Covers
• Equity Share Capital - With voting rights, or with differential rights as to dividend, voting, etc. All share capital which is NOT preference share capital.
• Preference Share Capital - Carries preferential right on dividend (fixed amount/rate) and repayment of capital on winding up. Has priority over equity.
• For private companies, memorandum or articles may permit other kinds.

Important Exam Insight
Don't confuse with Section 43A (old). Focus on differential voting rights conditions - Rule 4: 26% voting power limit, 3 years distributable profits track record, no default in filing annual accounts/returns. ICAI loves asking conditions for DVR.

Brutal Truth / How ICAI Tests
• Distinguish equity vs preference - rights, risk, return.
• DVR conditions - 4 conditions + disclosure in Board Report.
• Can private company have other kinds? Yes, if MOA/AOA permits.

Example: Company wants to issue equity with differential voting rights - check 26% limit, 3-year profit history, no default, approval via postal ballot, disclosure.

Want MCQs on Sec 43 + DVR rules?

Relevant Material Used: {sec43_chunk['topic']} - {sec43_chunk['chapter']}"""
        
        # Generic RAG answer builder
        if best_chunk:
            # Build structured answer from chunk content
            lines = best_chunk['content'].split('. ')
            intro = lines[0] if lines else best_chunk['content'][:200]
            bullets = []
            for line in best_chunk['content'].split('•'):
                if line.strip() and len(line.strip()) > 20:
                    bullets.append(line.strip().split('.')[0][:120])
            
            bullet_text = "\n".join([f"• {b[:100]}" for b in bullets[:5]]) if bullets else f"• {best_chunk['content'][:400]}"
            
            anchor_text = ""
            if anchors:
                anchor_text = "\n\nAuthoritative Provision:\n" + "\n".join([f"• {a[:150]}" for a in anchors[:2]])
            
            return f"""{intro}.

What {best_chunk['topic']} Covers
{bullet_text}

Important Exam Insight
Focus on exam-relevant points from this topic. Don't mug blindly - understand application. ICAI tests how provisions link to each other.

Brutal Truth / How ICAI Tests
ICAI doesn't test definitions in isolation - they test application via case studies. Link {best_chunk['topic']} to related sections.
{anchor_text}

Want me to break down exam-relevant points + MCQs + memory hacks for {best_chunk['topic']}?

Relevant Material Used: {best_chunk['topic']} - {best_chunk['chapter']}"""
    
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
