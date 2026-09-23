"""AI Study Assistant backend — POST /api/ai/ask.

v6: ICAI ANSWER FORMAT ENGINE (on top of the v5 MongoDB RAG)
- Answers are rendered in the skeleton an ICAI examiner expects for that
  question type (theory / practical / distinguish / case-study) instead of
  generic chatbot prose.
- The old "tutor explainer" ending ("Want me to break down...?") is banned.
  ICAI answers end with a stated Conclusion.
- Tiered grounding: full / partial / general. The assistant now always
  answers - it no longer refuses when retrieval is thin - while still being
  forbidden from guessing section numbers.
- Conversation memory: follow-ups like "explain more" now work.
- Kept from v5: MongoDB Atlas RAG (4777 chunks), file fallback, subject hints.
"""

import hashlib
import json
import os
import re
import time
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


class Turn(BaseModel):
    """One earlier message in the conversation."""
    role: str = Field(default="user")      # "user" or "assistant"
    text: str = Field(default="", max_length=6000)


class Attachment(BaseModel):
    """An image of a question, or a small file, sent as base64."""
    kind: str = Field(default="image", max_length=16)        # "image" | "file"
    name: Optional[str] = Field(default=None, max_length=200)
    mime: Optional[str] = Field(default=None, max_length=100)
    data: Optional[str] = None                               # base64, no prefix


class AskBody(BaseModel):
    studentId: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    chapterId: Optional[str] = None
    # Earlier turns, oldest first. Powers follow-ups like "explain more",
    # "give an example", "what about for a private company?". Optional so old
    # app versions keep working.
    history: Optional[List[Turn]] = None
    # A photographed question, or a file the student uploaded. Optional, so
    # app builds that never send it keep working unchanged.
    attachment: Optional[Attachment] = None


_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "for", "and",
         "or", "to", "what", "which", "how", "why", "when", "explain", "define", "about",
         "tell", "me", "please", "with", "from", "this", "that", "it", "its", "at", "by",
         "does", "do", "detail", "details", "section", "sec"}


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOP and len(t) > 1}


# Words that recur across almost every CA Inter chapter. A single one of these
# matching an anchor's keywords is noise, not evidence - it is how a FEMA or
# Cost-of-capital provision ended up inside a Companies Act answer.
_GENERIC_TOKENS = {
    "capital", "account", "accounting", "accounts", "company", "companies",
    "share", "shares", "audit", "auditing", "cost", "costing", "tax", "taxation",
    "law", "laws", "value", "values", "profit", "profits", "loss", "losses",
    "income", "asset", "assets", "fund", "funds", "investment", "investments",
    "financial", "finance", "statement", "statements", "management", "managed",
    "standard", "standards", "provision", "provisions", "interest", "dividend",
    "dividends", "equity", "debt", "cash", "bank", "banks", "credit", "insure",
    "insurance", "business", "office", "section", "sections", "matters", "matter",
    "records", "report", "reports", "auditor", "auditors", "practice", "revenue",
}


def retrieve_anchors(question: str, limit: int = 5) -> List[str]:
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
        # Section numbers the student actually named, e.g. "Section 43".
        named = set()
        for m in re.finditer(r"(?:section|sec\.?)\s*([0-9]{1,3}[a-z]?)", question.lower()):
            named.add(m.group(1))

        scored = []
        for keywords, text in ANCHORS:
            kt = set()
            for k in keywords:
                kt |= _tokens(k)
            overlap = qt & kt
            if not overlap:
                continue

            # A single common word is not enough to call something GROUND TRUTH.
            # Words that appear in nearly every CA chapter carry no signal on
            # their own, so they cannot qualify an anchor by themselves.
            distinctive = [
                t for t in overlap
                if len(t) >= 7 and t not in _GENERIC_TOKENS
            ]
            if not (len(overlap) >= 2 or distinctive):
                continue

            # If the student named a section, an anchor that cites a DIFFERENT
            # section must not ride in on a weak match. This is what let a FEMA
            # provision appear inside a Companies Act answer.
            if named and len(overlap) < 3:
                cited = set(re.findall(
                    r"(?:sec\.?|sections?)\s*([0-9]{1,3}[a-z]?)", text.lower()))
                if cited and not (cited & named):
                    continue

            scored.append((len(overlap), text))

        scored.sort(key=lambda x: -x[0])
        for _, text in scored:
            if len(picked) >= limit:
                break
            if text not in picked:
                picked.append(text)
    return picked


def _detect_subject_hint(q_lower: str) -> Optional[str]:
    if any(w in q_lower for w in ["audit", "sa 500", "sa 200", "s auditing"]):
        return "Audit"
    elif any(w in q_lower for w in ["costing", "eoq", "material cost", "labour", "overhead", "abc", "budget"]):
        return "Costing"
    elif any(w in q_lower for w in ["account", "as ", "accounting standard", "amalgamation", "consolidat", "holding"]):
        return "Accounts"
    elif any(w in q_lower for w in ["law", "companies act", "llp", "section 43", "section 2", "sec 2", "sec 43", "deposits", "prospectus", "share capital"]):
        return "Law"
    elif any(w in q_lower for w in ["fm", "financial management", "cost of capital", "leverage", "capital structure", "dividend", "ratio", "working capital"]):
        return "FM"
    elif any(w in q_lower for w in ["sm", "strategic", "swot", "porter", "bcg", "strategic management"]):
        return "SM"
    elif any(w in q_lower for w in ["tax", "dt", "gst", "income tax", "residential status", "supply"]):
        return "Taxation"
    return None


def _score_chunks(all_chunks: List[dict], question: str, subject_hint: Optional[str], q_tokens: set, q_lower: str, limit: int = 5) -> List[dict]:
    scored = []
    for chunk in all_chunks:
        content_lower = chunk.get("content","").lower()
        topic_lower = chunk.get("topic","").lower()
        chapter_lower = chunk.get("chapter","").lower()
        subject = chunk.get("subject","")
        score = 0
        if subject_hint and subject.lower() == subject_hint.lower():
            score += 25
        elif subject_hint and subject_hint.lower() in subject.lower():
            score += 15
        if q_lower in topic_lower:
            score += 30
        if q_lower in chapter_lower:
            score += 20
        if q_lower in content_lower:
            score += 15
        content_tokens = set(re.findall(r"[a-z0-9]+", content_lower))
        topic_tokens = set(re.findall(r"[a-z0-9]+", topic_lower))
        topic_overlap = len(q_tokens & topic_tokens)
        content_overlap = len(q_tokens & content_tokens)
        score += topic_overlap * 8
        score += content_overlap * 1
        sec_match = re.search(r'section\s*(\d+[a-z]?)|sec\s*(\d+[a-z]?)', q_lower)
        if sec_match:
            sec_num = sec_match.group(1) or sec_match.group(2)
            if sec_num and sec_num in content_lower:
                score += 30
            if sec_num and sec_num in topic_lower:
                score += 25
        if "eoq" in q_lower and "eoq" in content_lower:
            score += 40
        if "swot" in q_lower and "swot" in content_lower:
            score += 40
        if "audit evidence" in q_lower and "audit evidence" in content_lower:
            score += 40
        if "share capital" in q_lower and "share capital" in content_lower:
            score += 35
        if len(content_lower) < 400:
            score -= 10
        if "learning outcomes" in content_lower:
            score -= 15
        if score > 5:
            scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    result = []
    seen_content = set()
    for score, chunk in scored:
        content_hash = chunk.get("content","")[:100]
        if content_hash in seen_content:
            continue
        seen_content.add(content_hash)
        result.append(chunk)
        if len(result) >= limit:
            break
    return result


def retrieve_knowledge_chunks_sync(question: str, limit: int = 5) -> List[dict]:
    try:
        from data_knowledge_base import KNOWLEDGE_BASE as MANUAL_KB
        try:
            from data_knowledge_base_auto import KNOWLEDGE_BASE_AUTO
        except:
            KNOWLEDGE_BASE_AUTO = []
        q_lower = question.lower()
        q_tokens = set(re.findall(r"[a-z0-9]+", q_lower))
        subject_hint = _detect_subject_hint(q_lower)
        all_chunks = []
        all_chunks.extend(MANUAL_KB)
        for c in KNOWLEDGE_BASE_AUTO:
            content = c.get("content","")
            if len(content) < 300:
                continue
            if "learning outcomes" in content.lower() and len(content) < 800:
                continue
            if "institute of chartered accountants" in content.lower() and len(content.split()) < 100:
                if content.lower().count("the institute") > 3:
                    continue
            topic = c.get("topic","")
            if len(topic) < 5 or re.match(r'^[A-Za-z0-9_-]{20,}$', topic):
                continue
            all_chunks.append(c)
        result = _score_chunks(all_chunks, question, subject_hint, q_tokens, q_lower, limit)
        print(f"RAG FILE search for '{question[:50]}' -> subject_hint={subject_hint}, found {len(result)} chunks")
        return result[:limit]
    except Exception as e:
        print(f"KB sync search failed: {e}")
        return []


async def retrieve_knowledge_chunks(question: str, limit: int = 5) -> List[dict]:
    q_lower = question.lower()
    q_tokens = set(re.findall(r"[a-z0-9]+", q_lower))
    subject_hint = _detect_subject_hint(q_lower)
    try:
        from db import get_db, KNOWLEDGE_CHUNKS
        db = get_db()
        count = await db[KNOWLEDGE_CHUNKS].count_documents({})
        if count > 100:
            mongo_filter = {}
            if subject_hint:
                mongo_filter["subject"] = {"$regex": f"^{subject_hint}$", "$options": "i"}
            try:
                search_terms = " ".join([t for t in q_tokens if len(t) > 2][:5])
                if search_terms:
                    cursor = db[KNOWLEDGE_CHUNKS].find(
                        {"$text": {"$search": search_terms}, **mongo_filter},
                        {"score": {"$meta": "textScore"}}
                    ).sort([("score", {"$meta": "textScore"})]).limit(limit * 3)
                    docs = []
                    async for d in cursor:
                        d.pop("_id", None)
                        docs.append(d)
                    if docs:
                        scored = _score_chunks(docs, question, subject_hint, q_tokens, q_lower, limit)
                        print(f"RAG MONGO TEXT search '{question[:50]}' -> {len(scored)} chunks from {count} total")
                        return scored[:limit]
            except Exception as e:
                print(f"Mongo text search failed, trying regex: {e}")
            try:
                important_tokens = [t for t in q_tokens if len(t) > 2][:4]
                if important_tokens:
                    regex_pattern = "|".join(re.escape(t) for t in important_tokens)
                    regex_filter = {
                        "$or": [
                            {"topic": {"$regex": regex_pattern, "$options": "i"}},
                            {"chapter": {"$regex": regex_pattern, "$options": "i"}},
                            {"content": {"$regex": regex_pattern, "$options": "i"}},
                        ]
                    }
                    if subject_hint:
                        regex_filter = {"$and": [mongo_filter, regex_filter]}
                    cursor = db[KNOWLEDGE_CHUNKS].find(regex_filter).limit(limit * 4)
                    docs = []
                    async for d in cursor:
                        d.pop("_id", None)
                        docs.append(d)
                    if docs:
                        scored = _score_chunks(docs, question, subject_hint, q_tokens, q_lower, limit)
                        print(f"RAG MONGO REGEX search '{question[:50]}' -> {len(scored)} chunks")
                        return scored[:limit]
            except Exception as e:
                print(f"Mongo regex search failed: {e}")
            if subject_hint:
                cursor = db[KNOWLEDGE_CHUNKS].find({"subject": {"$regex": f"^{subject_hint}$", "$options": "i"}}).limit(limit * 2)
                docs = []
                async for d in cursor:
                    d.pop("_id", None)
                    docs.append(d)
                if docs:
                    scored = _score_chunks(docs, question, subject_hint, q_tokens, q_lower, limit)
                    if scored:
                        print(f"RAG MONGO SUBJECT search '{question[:50]}' -> {len(scored)} chunks")
                        return scored[:limit]
    except Exception as e:
        print(f"Mongo RAG failed, falling back to file: {e}")
    return retrieve_knowledge_chunks_sync(question, limit)


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


# =====================================================================
# ICAI ANSWER FORMAT ENGINE (v6)
# ---------------------------------------------------------------------
# Student complaint: "answers are not as per ICAI format".
# Root cause: the prompt asked for a friendly tutor explanation that ended
# with a sales CTA. ICAI answers have a fixed presentation per question type:
#
#   Theory        -> Provision -> Explanation -> Conclusion
#   Practical     -> Assumptions -> Working Notes -> Statement -> Final Answer
#   Distinguish   -> two-column table on exam-relevant bases
#   Case study    -> Provisions Applicable -> Application to facts -> Conclusion
#
# Every answer is now rendered in one of those four skeletons.
# =====================================================================

MODE_THEORY = "theory"
MODE_PRACTICAL = "practical"
MODE_DISTINGUISH = "distinguish"
MODE_CASE_STUDY = "case_study"

_PRACTICAL_CUES = (
    "compute", "calculate", "solve", "prepare", "find the", "amount of",
    "value of", "working note", "cost sheet", "valuation", "depreciat",
    "closing stock", "trial balance", "gross profit", "net profit",
    "reconciliation", "statement of profit", "statement of cost",
    "apportion", "reapportion", "marginal cost", "break even", "breakeven",
    "npv", "irr", "payback", "wacc", "eps", "how much", "what is the cost",
)
_DISTINGUISH_CUES = (
    "distinguish", "differentiate", "difference between", "compare",
    "versus", "v/s", " vs ", "tabulate",
)
_CASESTUDY_CUES = (
    "in the given case", "advise", "comment whether", "is he liable",
    "are they liable", "is the company liable", "whether the company",
    "state with reasons", "examine whether", "discuss the validity",
    "case study", "ltd.", "limited,", "pvt", "given the following facts",
)


def detect_answer_mode(question: str) -> str:
    """Classify the question so the answer gets the right ICAI skeleton."""
    q = " " + (question or "").lower() + " "
    if any(c in q for c in _DISTINGUISH_CUES):
        return MODE_DISTINGUISH
    if any(c in q for c in _PRACTICAL_CUES):
        return MODE_PRACTICAL
    if any(c in q for c in _CASESTUDY_CUES):
        return MODE_CASE_STUDY
    return MODE_THEORY


# -------- per-paper presentation rules (how ICAI wants this paper written) --
ICAI_PAPER_FORMAT = {
    "Accounts": (
        "Applicable AS / Ind AS / Schedule III. For every adjustment show the "
        "effect on Profit and on Balance Sheet. Numericals need numbered Working "
        "Notes. Journal entries in the standard Dr/Cr format with narration."
    ),
    "Law": (
        "State the exact section number and Act first, then the conditions or "
        "thresholds, then the consequence/penalty. For case studies finish with "
        "an explicit Conclusion naming the person/company and liability. "
        "Never paraphrase a section number from memory."
    ),
    "Taxation": (
        "Name the head of income / nature of supply first, then the computation "
        "in a statement, then the tax effect. State Previous Year and Assessment "
        "Year. Quote the exact section or GST section/rule."
    ),
    "Costing": (
        "Lead with the method and its purpose, then a clearly titled statement "
        "(e.g. 'Statement of Cost and Profit'), then numbered Working Notes for "
        "every apportionment. Show the basis of apportionment explicitly."
    ),
    "Audit": (
        "Cite the SA number and the section (e.g. Section 143(3)). Structure as "
        "Requirement of SA -> Audit procedure to be performed -> Reporting impact. "
        "Use the words ICAI expects: 'the auditor should', 'shall report'."
    ),
    "FM": (
        "State the concept and the formula, then the assumption, then the "
        "decision rule (accept/reject, higher/lower is better), then compute in "
        "a statement with Working Notes."
    ),
    "SM": (
        "Name the framework explicitly (SWOT / PESTEL / Porter / value chain), "
        "apply each element to the given organisation, then give a recommendation."
    ),
}


_MODE_SKELETON = {
    MODE_THEORY: """Provision
State the exact section / SA / AS / Ind AS and what it provides. If the
material does not give the section number, write the principle without a
number - NEVER guess one.

Explanation
Point-wise explanation with sub-points and bolded key terms. One idea per
line. No long unbroken paragraphs.

Conclusion
Apply the provision to what the student asked and state the conclusion in
one or two clear lines, starting with the word "Conclusion:".""",

    MODE_PRACTICAL: """Assumptions
Only if the question is silent on something you must assume. If nothing is
assumed, skip this block entirely.

Working Notes
Numbered: Working Note 1, Working Note 2 ... Every figure used in the final
statement must be traceable to a working note. Show the basis of every
apportionment.

Statement
A properly titled statement, e.g. "Statement showing Computation of
<what> as on <date>", in Particulars / Amount (Rs) form. Amounts aligned.

Final Answer
The answer in bold with the unit stated (Rs / Rs lakhs / %). A reader must
be able to find the answer without re-reading the workings.""",

    MODE_DISTINGUISH: """Open with one line naming both items being distinguished.

Then a single table only, no prose paragraphs:

| Basis of Difference | <First item> | <Second item> |
|---|---|---|
| ... | ... | ... |

Use 4 to 6 rows, and only bases that ICAI actually tests. Each cell is a
short phrase, not a sentence. No conclusion line is needed for a pure
"distinguish between" answer.""",

    MODE_CASE_STUDY: """Provisions Applicable
State the exact section / SA / AS and its requirement.

Application to the Given Facts
Apply it to the facts of the question, point by point. Name the parties.

Conclusion
Start with "Conclusion:" and answer the specific question asked (liable /
not liable, valid / void, allowed / disallowed). Two sentences maximum.""",
}

_BANNED = [
    "Want me to", "want me to break down", "Brutal Truth", "Let me know if",
    "Shall I", "Would you like me to", "I can also", "Here is your answer",
    "I hope this helps", "Feel free to ask", "Great question",
    "As an AI", "I think", "In my opinion",
]


# =====================================================================
# TIERED GROUNDING
# ---------------------------------------------------------------------
# The old rule was "answer ONLY from the provided material, else say Not
# found". Where retrieval is thin that silently produces refusals - which is
# why answers felt unlike ChatGPT. But simply dropping the rule would let the
# model invent section numbers, which is worse for a CA student.
#
# So: grade the retrieved context, then set the rules to match.
#
#   full     >= 3 solid chunks  -> answer strictly from material, cite it
#   partial  1-2 chunks         -> material is the backbone, may add standard
#                                  syllabus knowledge, marked as unsourced
#   general  no usable chunks   -> answer from CA Inter knowledge, opened with
#                                  a clear "not module-verified" note, and
#                                  forbidden from guessing section numbers
# =====================================================================

TIER_FULL = "full"
TIER_PARTIAL = "partial"
TIER_GENERAL = "general"


def assess_grounding(chunks: list, anchors: list) -> str:
    """Grade how well the retrieved material covers the question."""
    solid = 0
    for c in chunks or []:
        if len(((c or {}).get("content") or "").strip()) >= 200:
            solid += 1
    if anchors:
        solid += len(anchors)
    if solid >= 3:
        return TIER_FULL
    if solid >= 1:
        return TIER_PARTIAL
    return TIER_GENERAL


_TIER_RULES = {
    TIER_FULL: """HOW MUCH YOU MAY RELY ON THE MATERIAL: FULL
The reference material below is sufficient. Answer from it. Cite the section,
SA, AS or Ind AS number when it appears in the material. Do not add outside
provisions - there is no need, the material covers this.""",

    TIER_PARTIAL: """HOW MUCH YOU MAY RELY ON THE MATERIAL: PARTIAL
The material below covers the question only partly. Use it as the backbone and
cite whatever it gives you. Where it runs out, complete the answer from
standard CA Intermediate syllabus knowledge. End the affected part with
"(standard syllabus point - verify with your module)" so the student knows
which lines are not sourced from the extract. Never leave the answer
half-finished just because the extract ran out.""",

    TIER_GENERAL: """HOW MUCH YOU MAY RELY ON THE MATERIAL: NONE
The material below does not cover this question. Do NOT refuse and do NOT say
"not found in provided material" - that is unhelpful for a student who needs to
understand the topic today.

Instead: open with exactly this line on its own -
"Note: not verified against your module extract - this is standard CA
Intermediate knowledge. Cross-check the provision number in your study
material."

Then answer the question fully, in the ICAI format required below, from your CA
Intermediate knowledge. You MUST obey these two safety rules:
  - Do not state a specific section / SA / AS / Ind AS NUMBER unless you are
    certain of it. If unsure of the number, describe the provision and say
    "see the relevant chapter in your module for the exact section number".
  - Do not invent case names, dates, rates or amendment years.
Getting the concept right is what matters; a wrong section number is what
costs marks.""",
}


def _tier_rule(tier: str) -> str:
    return _TIER_RULES.get(tier, _TIER_RULES[TIER_PARTIAL])


def build_system_prompt(mode: str, subject: str = "", tier: str = TIER_PARTIAL,
                        marks: int = 0) -> str:
    """Compose the ICAI answer-writer prompt for this question type + tier."""
    skeleton = _MODE_SKELETON.get(mode, _MODE_SKELETON[MODE_THEORY])

    paper = ""
    if subject and subject in ICAI_PAPER_FORMAT:
        paper = (
            "\nPRESENTATION RULES FOR THIS PAPER (%s):\n%s\n"
            % (subject, ICAI_PAPER_FORMAT[subject])
        )

    if marks:
        depth = (
            "This is worth about %d marks. Write roughly %d lines of substance. "
            "Do not pad to reach it and do not write a paragraph where a line "
            "will do." % (marks, max(6, marks * 2))
        )
    else:
        depth = (
            "Length follows the marks weightage: a short question gets 4-6 tight "
            "lines per heading, a long one gets the full treatment. Never pad, "
            "never truncate a working."
        )

    if mode in (MODE_THEORY, MODE_CASE_STUDY):
        example_rule = (
            "\n9. Where a one-line illustration makes the provision land, add it "
            "as a short \"Illustration:\" line. One line only."
        )
    elif mode == MODE_PRACTICAL:
        example_rule = (
            "\n9. Show every figure. A reader must be able to reproduce your "
            "number without asking a question."
        )
    else:
        example_rule = ""

    return """You are writing a CA Intermediate exam answer for a student who will
be graded on it. Write the way a rank-holder writes in the answer-sheet:
precise, complete, and laid out so an examiner can award marks by scanning the
headings.

There is no conversation here. No greeting, no sign-off, no chit-chat.

%s

HARD RULES - breaking any of these makes the answer unusable:
1. Never invent a section number, SA number, AS/Ind AS number, case name, date
   or rate. A wrong provision costs more marks than a missing one.
1a. SUB-SECTION DISCIPLINE. Cite a sub-section - "92(5)", "43(a)" - only when
   that exact sub-section appears in the material provided below. If the
   material gives the section but not the carve-up, cite the bare section
   ("Section 92") and nothing finer. Getting "correct section, wrong
   sub-section" is the single most common way this answer loses marks, so it
   is better to write one fewer digit than one wrong digit.
1b. ATTRIBUTION DISCIPLINE. Attach a consequence to the section that actually
   creates it. A penalty, a disqualification, a strike-off power and a filing
   duty usually live in different sections - do not bundle them under whichever
   number happens to be under discussion, and do not present a consequence as
   coming from the same sub-section merely because the facts mention it.
2. Authoritative provision anchors below are ground truth. Use them verbatim
   and never contradict them.
3. NEVER end with a question, an offer, or an upsell. Banned: "Want me to",
   "Shall I", "Let me know", "Would you like". An ICAI answer ends with the
   conclusion or the final answer.
4. No emojis, no "Brutal Truth", no "Great question", no motivational filler.
5. No "I think", "in my opinion", "as an AI". Write objectively, third person.
6. Keep every mark-relevant heading. An examiner must be able to award marks
   from the headings alone.
7. Explain WHY the provision exists or HOW it is applied - not just what it
   says. A student who understands the reason can answer the twisted version
   ICAI actually sets.
8. Where ICAI commonly traps students on this topic, add one line starting
   "Examiner's angle:" stating the trap. One line, only if genuinely relevant.
9. NO LaTeX AND NO MATH MARKUP. The app prints your reply as plain text, so
   "$$", "\sqrt", "\frac{2}{3}", "\text" and "\times" reach the student as
   literal backslashes and braces - the formula becomes unreadable. Write every
   formula in plain characters instead:
     right:  EOQ = sqrt(2 x A x O / C)
     right:  EOQ = square root of (2 x Annual demand x Ordering cost / Carrying cost)
     right:  P/V ratio = Contribution / Sales x 100
     wrong:  $$EOQ = \sqrt{\frac{2AO}{C}}$$
   Show the substitution line by line, then the result. Use x for multiply, /
   for divide, and write "sqrt(...)" or the words "square root of" rather than
   a radical sign. Never wrap a formula in $ signs.
10. Plain markdown only: **bold** and simple "-" or "1." lists and "|" tables.
   No HTML, no <br>, no \n escapes, no code fences.
%s

DEPTH
%s

%s
REQUIRED SKELETON FOR THIS QUESTION TYPE:
%s

Language: English only. Use Rs for currency. Bold key terms with **double
stars**, never inside a heading.""" % (
        _tier_rule(tier), example_rule, depth, paper, skeleton,
    )


# kept for older call sites
_ORIG_SUBJECT_GUIDE = {
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


async def offline_answer(question: str, chapter: Optional[dict],
                         mode: Optional[str] = None,
                         tier: Optional[str] = None) -> str:
    """Fallback when Groq is unavailable.

    v6: renders the SAME ICAI skeleton as the live path, built from the
    retrieved module chunks. The old version returned hardcoded paragraphs for
    two topics and generic filler ("Brutal Truth / How ICAI Tests") for
    everything else, and always ended with an offer. That filler is gone.
    """
    if mode is None:
        mode = detect_answer_mode(question)

    chunks = await retrieve_knowledge_chunks(question, 5)
    anchors = retrieve_anchors(question, 5)
    if tier is None:
        tier = assess_grounding(chunks, anchors)

    topic = ""
    if chapter:
        topic = chapter.get("chapterTitle") or ""
    if chunks:
        topic = chunks[0].get("topic") or topic

    if not chunks and not anchors:
        return _no_material_answer(question, topic)

    best = chunks[0] if chunks else None
    chapter_name = (best.get("chapter") if best else "") or ""
    subject = ""
    if chapter:
        subject = chapter.get("subject") or ""
    if not subject and best:
        subject = best.get("subject") or ""

    provision = "\n".join("- " + a.strip() for a in anchors[:3]) if anchors else ""

    points: list = []
    for c in chunks[:3]:
        points.extend(_chunk_points(c, limit=4))
    seen = set()
    deduped = []
    for p in points:
        key = p[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    points = deduped[:7]

    source_line = ""
    if best:
        bits = [b for b in (best.get("topic"), chapter_name) if b]
        if bits:
            source_line = "\n\n[Source: ICAI module extract \u2014 " + " / ".join(bits) + "]"

    # ---------------- DISTINGUISH ----------------
    if mode == MODE_DISTINGUISH:
        if not points:
            return (
                "The module extract does not contain the two items this comparison "
                "needs. Name both items exactly as they appear in your module "
                "(for example \"equity share capital vs preference share capital\") "
                "and ask again." + source_line
            )
        listed = "\n".join(
            "%d. %s" % (i + 1, p.rstrip(".")) for i, p in enumerate(points[:6])
        )
        return (
            "ICAI expects this answered as a two-column table. These are the bases "
            "from the module extract to compare on:\n\n"
            + listed
            + "\n\nAnswer format for this question:\n"
            "| Basis of Difference | <first item> | <second item> |\n"
            "|---|---|---|\n"
            "| ... | ... | ... |\n\n"
            "The side-by-side comparison needs the live AI service, which is "
            "currently unavailable. Arrange the module points above against each "
            "of the two items in your answer sheet."
            + source_line
        )

    # ---------------- PRACTICAL ----------------
    if mode == MODE_PRACTICAL:
        method_pts = "\n".join("- " + p for p in points[:5])
        return (
            "Assumptions\nNone stated in the question.\n\n"
            "Working Notes\n"
            "The offline module extract does not hold the figures for this "
            "question, so the computation cannot be completed here. The method "
            "and treatment to apply are:\n"
            + (method_pts if method_pts else "- Not found in the provided material.") + "\n\n"
            "Statement\nSet out your statement with the title the question asks for "
            "(for example \"Statement showing Computation of <what>\"), in "
            "Particulars / Amount (Rs) form, using the method above.\n\n"
            "Final Answer\nState the figure with its unit once the statement is complete."
            + source_line
        )

    # ---------------- CASE STUDY ----------------
    if mode == MODE_CASE_STUDY:
        prov_block = provision if provision else "Not found in the provided material."
        expl = "\n".join("- " + p for p in points[:5])
        return (
            "Provisions Applicable\n" + prov_block + "\n\n"
            "Application to the Given Facts\n" + expl + "\n\n"
            "Conclusion\nApply the provisions above to the facts of your question "
            "and state the outcome (liable / not liable, valid / void, allowed / "
            "disallowed). A case-study conclusion needs the specific facts of your "
            "question."
            + source_line
        )

    # ---------------- THEORY (default) ----------------
    prov_block = provision if provision else (
        "The retrieved module extract for %s provides as follows:" % (topic or "this topic")
    )
    expl = "\n".join("- " + p for p in points[:6])

    # Pick a conclusion that reads as a complete statement, not a list fragment.
    # Bad candidates look like "(b) Preference share capital - ..." or "Sec 43 - ...".
    concl = ""
    anchor_blob = " ".join(anchors).lower()
    for p in reversed(points):
        key = p[:45].lower()
        if not key or key in anchor_blob:
            continue
        stripped = p.strip()
        if re.match(r"^\(?[a-z0-9]\)?[\.)]\s", stripped.lower()):
            continue          # lettered/numbered list fragment
        if re.match(r"^(sec\.?|section|as |sa |ind as|clause)\b", stripped.lower()):
            continue          # bare citation, not a conclusion
        if len(stripped) < 60:
            continue          # too short to be a conclusion
        concl = stripped
        break
    if not concl and points:
        concl = max(points, key=len)

    return (
        "Provision\n" + prov_block + "\n\n"
        "Explanation\n" + expl + "\n\n"
        "Conclusion\n" + (concl if concl else "Not found in the provided material.")
        + source_line
    )


def _chunk_points(chunk: dict, limit: int = 6) -> list:
    """Pull clean exam-usable points out of a retrieved module chunk."""
    text = _clean_page_text(chunk.get("content") or "")
    if not text:
        return []
    raw = re.split(r"(?<=[.;])\s+|\n+|\u2022", text)
    out = []
    for s in raw:
        s = s.strip(" -\t")
        if len(s) < 25:
            continue
        out.append(s if s.endswith(".") else s + ".")
        if len(out) >= limit:
            break
    return out


def _no_material_answer(question: str, topic: str) -> str:
    """Last resort: nothing retrieved AND the live model is unavailable."""
    where = " on %s" % topic if topic else ""
    return (
        "Note: not verified against your module extract - this is standard CA "
        "Intermediate knowledge. Cross-check the provision number in your study "
        "material.\n\n"
        "Provision\nThe offline notes did not retrieve a module extract" + where +
        ", so the exact section / SA number could not be confirmed.\n\n"
        "Explanation\nThe assistant is currently running without the live AI "
        "service, which is what produces full worked answers. What can be "
        "confirmed offline is the approach: identify the chapter, state the "
        "governing provision, apply each condition to the facts, then conclude.\n\n"
        "Conclusion\nThis question needs the live AI service for a complete "
        "answer. If it stays unavailable, work through the chapter in your module "
        "using the approach above, or rephrase using the exact chapter or "
        "provision name (\"Section 43\", \"AS 10\", \"SA 700\")."
    )


# Emoji that must never appear in an ICAI answer.
#
# Deliberately NARROW. An earlier version flagged the whole 0x2600-0x27BF and
# 0x2190-0x21FF blocks, which wrongly rejected perfectly good costing answers
# that used "->" arrows or a tick mark in a working-notes table. Arrows,
# tick/cross marks, rupee signs and mathematical operators are all legitimate
# in an exam answer and are explicitly allowed below.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),   # pictographs, emoticons, transport, symbols
    (0x1F000, 0x1F0FF),   # playing cards, mahjong
    (0x1F900, 0x1F9FF),   # supplemental symbols
)
_EMOJI_EXACT = {
    0x2705,  # white heavy check mark (green box)
    0x274C,  # cross mark
    0x274E,  # cross mark (negative squared)
    0x2B50,  # white medium star
    0x1F4D8,  # blue book
    0x1F4DA,  # books
    0x1F4A1,  # light bulb
    0x1F680,  # rocket
    0x1F389,  # party popper
    0x1F44D,  # thumbs up
    0x1F44F,  # clapping hands
}


def _is_emoji_char(ch: str) -> bool:
    o = ord(ch)
    if o in _EMOJI_EXACT:
        return True
    for lo, hi in _EMOJI_RANGES:
        if lo <= o <= hi:
            return True
    return False


def _has_emoji(text: str) -> bool:
    return any(_is_emoji_char(ch) for ch in text)


def _sanitize_answer(text: str) -> str:
    """Repair small format violations instead of discarding a good answer.

    Rejecting an otherwise excellent answer because it ended with "Let me know
    if you need more examples" threw away the whole thing and served a much
    worse offline answer. Trimming the offending line is strictly better.

    Removes, from the END only, up to 4 trailing lines that are:
      - a question back to the student
      - a call to action / upsell
      - a sign-off pleasantry
    and strips emoji characters anywhere in the text.
    """
    if not text:
        return text

    # 1. strip emoji (narrow set - arrows and tick marks are legitimate)
    text = "".join(ch for ch in text if not _is_emoji_char(ch))
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 2. drop trailing CTA / question / sign-off lines
    _CTA = (
        "want me to", "shall i ", "let me know", "would you like",
        "do you want", "if you want", "feel free to ask", "i can also",
        "i hope this helps", "hope this helps", "here is your answer",
        "happy to help", "let me know if", "give it a try",
        "brutal truth", "great question", "all the best",
    )
    lines = text.rstrip().split("\n")
    removed = 0
    while lines and removed < 4:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        low = last.lower()
        is_question = last.endswith("?")
        is_cta = any(c in low for c in _CTA)
        # A line ending in "?" at the very end is a question back to the
        # student, whatever its length - trim it. A CTA is only trimmed when
        # the line is short, so a real paragraph is never lost.
        if is_question or (is_cta and len(last) < 220):
            lines.pop()
            removed += 1
            continue
        break

    return "\n".join(lines).rstrip()


def _clean_page_text(text: str) -> str:
    """Strip ICAI page furniture out of a retrieved module extract.

    Every page of the module PDFs repeats a running head, a footer line and a
    page number, and retrieval returns them verbatim. Left in, they land in the
    middle of the student's answer - stray text such as
    "ACCOUNTS OF COMPANIES 9.77 ... The Institute of Chartered Accountants of
    India" between two paragraphs. Offline answers showed exactly that.
    """
    out = []
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"[\d\s.\-]+", s):                 # bare page number
            continue
        if "The Institute of Chartered Accountants of India" in s:
            continue
        if re.fullmatch(r"[A-Z][A-Z &,\-]{8,}", s) and len(s) < 60:
            continue                                          # running head
        out.append(s)
    return " ".join(out)


def _clip_chunk(text: str, limit: int = 1100) -> str:
    """Trim a retrieved chunk to a token-cheap extract.

    Keeps the head (which states the provision) plus the tail (which usually
    carries the penalty or conclusion) when the text is long.
    """
    body = _clean_page_text(text)
    if len(body) <= limit:
        return body
    head = body[: int(limit * 0.7)].rstrip()
    tail = body[-int(limit * 0.25):].lstrip()
    return f"{head} ... {tail}"


def _is_table_markup(line: str) -> bool:
    """True for markdown table rules and separator rows - they carry no prose."""
    s = line.strip()
    if not s:
        return False
    if set(s) <= set("-:|+ \t"):          # |---|---|  or  ----------
        return True
    if s.count("|") >= 2 and sum(c.isalnum() for c in s) == 0:
        return True
    return False


def _is_bad_answer(text: str) -> bool:
    """Reject answers that break ICAI presentation rules."""
    if not text or len(text) < 50:
        return True

    low = text.lower()

    # model leaked its own reasoning
    for m in ("we need to answer:", "we must respond within ca inter",
              "but the question:", "we should answer", "as an ai"):
        if m in low[:600]:
            return True

    # ICAI answers never end with an offer or a question back to the student
    tail = low[-300:]
    for banned in ("want me to", "shall i ", "let me know", "would you like",
                   "brutal truth", "i can also", "feel free to ask",
                   "here is your answer", "i hope this helps"):
        if banned in tail:
            return True
    if text.rstrip().endswith("?"):
        return True

    # no emojis in an exam answer
    if _has_emoji(text):
        return True

    # repetition guards
    if low.count("llp agreement") > 8:
        return True
    if low.count("includes the terms of the partnership") > 2:
        return True
    if low.count("includes the terms of the") > 5:
        return True
    # Repetition guard. Markdown table markup must be stripped first: a row
    # separator such as "|-------------|----------|" is 27 characters long, so
    # any answer containing a few tables used to look like a model stuck in a
    # loop and the entire answer was discarded in favour of the offline one.
    prose = "\n".join(ln for ln in text.split("\n") if not _is_table_markup(ln))
    from collections import Counter
    sentences = [
        s.strip() for s in re.split(r"[.\n]", prose.lower())
        if len(s.strip()) > 25 and sum(c.isalpha() for c in s) >= 20
    ]
    # A genuine loop repeats one sentence over and over. A table header or a
    # recurring phrase legitimately reappears a few times in a long answer, so
    # require both a hard floor and a large share of the answer to call it a loop.
    if len(sentences) >= 8:
        cnt = Counter(sentences)
        repeated = cnt.most_common(1)[0][1]
        if repeated >= 4 and repeated >= 0.4 * len(sentences):
            return True
    return False


# Groq lineup, strongest first. Falls through on failure or a rejected answer.
# Groq model IDs, strongest first. Falls through to the next on failure or a
# rejected answer.
#
# UPDATED 23 Sep 2026 - the previous list was ENTIRELY decommissioned, which is
# why every answer fell back to offline mode and nothing ever reached Groq:
#   llama-3.3-70b-versatile  shut down 16 Aug 2026 -> openai/gpt-oss-120b
#   llama-3.1-8b-instant     shut down 16 Aug 2026 -> openai/gpt-oss-20b
#   qwen-2.5-32b / qwen 3 32B shut down 17 Jul 2026 -> openai/gpt-oss-120b
#   llama-3.1-70b-versatile  shut down 24 Jan 2025 -> llama-3.3 (itself gone)
#   mixtral-8x7b-32768       shut down 20 Mar 2025
#   gemma2-9b-it             removed
# See https://console.groq.com/docs/deprecations and re-check this list when
# answers start looking thin again - Groq has retired 7 models since Mar 2026.
MODELS_PRIORITY = [
    "openai/gpt-oss-120b",   # Groq's recommended flagship (500 tok/s)
    "qwen/qwen3.8-27b",      # separate rate-limit bucket, so a 429 on 120b
                             #   still gets a real answer (500 -> 450 tok/s)
    "openai/gpt-oss-20b",    # fastest + cheapest fallback (1000 tok/s)
]
# NOTE on 429s. The free tier gives 8,000 tokens per minute PER MODEL, and the
# requested max_tokens counts against that budget. Several students asking at
# the same moment therefore used to exhaust it and drop to the offline answer.
# Three models in the list means three separate buckets, the context is clipped
# and max_tokens is kept small - together that roughly triples the questions
# this key can serve per minute.

# ---------------------------------------------------------------------------
# Answer cache
# ---------------------------------------------------------------------------
# Every student in a batch asks the same textbook questions. Groq's free tier
# allows 8,000 tokens per minute per model, shared across the whole
# organisation, so without a cache a busy evening of study exhausts the quota
# and answers start falling back to the offline text. Caching a good answer the
# first time it is produced is the single cheapest way to raise capacity: the
# second and every later student asking the same question costs zero tokens.
ANSWER_CACHE = "ai_answer_cache"
_CACHE_TTL_DAYS = 45


def _cache_key(question: str, mode: str) -> str:
    """Stable key for a question, ignoring case, punctuation and spacing."""
    norm = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower()).split())
    return hashlib.sha1(f"{mode}|{norm}".encode("utf-8")).hexdigest()


async def _cache_get(key: str) -> Optional[dict]:
    try:
        from db import get_db
        col = get_db()[ANSWER_CACHE]
        cutoff = time.time() - _CACHE_TTL_DAYS * 86400
        doc = await col.find_one({"_id": key, "created_ts": {"$gt": cutoff}})
        if not doc:
            return None
        await col.update_one({"_id": key}, {"$inc": {"hits": 1}})
        return doc
    except Exception as e:
        print(f"answer cache read unavailable (non-fatal): {e}")
        return None


async def _cache_put(key: str, question: str, mode: str, answer: str,
                     tier: str, chunks: int) -> None:
    try:
        from db import get_db
        await get_db()[ANSWER_CACHE].update_one(
            {"_id": key},
            {"$set": {"question": (question or "")[:300], "answer_format": mode,
                      "answer": answer, "grounding": tier, "chunks": chunks,
                      "created_ts": time.time()},
             "$setOnInsert": {"hits": 0}},
            upsert=True,
        )
    except Exception as e:
        print(f"answer cache write unavailable (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Attachments: a photographed question, or a PDF the student uploaded
# ---------------------------------------------------------------------------
# Groq's chat API takes images as a data: URL inside the message content, so
# this endpoint accepts base64. Only qwen is multimodal in the current line-up,
# which is why an image pins the model instead of walking MODELS_PRIORITY.
VISION_MODEL = "qwen/qwen3.8-27b"
MAX_ATTACHMENT_B64 = 5_000_000      # ~3.7 MB of original bytes


def _pdf_text_from_b64(data: str, limit: int = 8000) -> str:
    """Best-effort text of an uploaded PDF. Returns '' when unreadable.

    pypdf is not a dependency of the API, so this degrades quietly: the caller
    falls back to asking the student for a photo instead.
    """
    try:
        import base64 as _b64
        import io
        from pypdf import PdfReader
        raw = _b64.b64decode(data, validate=False)
        reader = PdfReader(io.BytesIO(raw))
        out = []
        for page in reader.pages[:12]:
            out.append(page.extract_text() or "")
            if sum(len(x) for x in out) > limit:
                break
        return "\n".join(out)[:limit].strip()
    except Exception as e:
        print(f"PDF extract unavailable (non-fatal): {e}")
        return ""


def _build_attachment(body) -> tuple:
    """Turn the request attachment into (image_data_url, pdf_text, error)."""
    att = getattr(body, "attachment", None)
    if not att:
        return None, "", ""
    # getattr everywhere: an older app build may send a partial attachment.
    data = (getattr(att, "data", None) or "").strip()
    name = getattr(att, "name", None) or ""
    if not data:
        return None, "", ""
    name = name.lower()
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    if len(data) > MAX_ATTACHMENT_B64:
        return None, "", (
            "That image is too large for me to read. Please retake the photo "
            "at a lower resolution, or crop it to just the question."
        )
    mime = (getattr(att, "mime", None) or "").lower()
    if mime == "application/pdf" or name.endswith(".pdf"):
        text = _pdf_text_from_b64(data)
        if not text:
            return None, "", (
                "I could not read the text out of that PDF. Please send a "
                "photo or a screenshot of the question instead - I can read "
                "pictures of questions directly."
            )
        return None, text, ""
    if mime.startswith("text/") or name.endswith((".txt", ".md", ".csv")):
        try:
            import base64 as _b64
            text = _b64.b64decode(data, validate=False).decode("utf-8", "ignore")
            return None, text[:8000], ""
        except Exception:
            return None, "", "I could not read that file. Please try a photo of the question."
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return f"data:{mime};base64,{data}", "", ""


async def groq_answer(question: str, chapter: Optional[dict],
                      mode: str = MODE_THEORY,
                      history: Optional[list] = None,
                      diag: Optional[list] = None,
                      image_data_url: Optional[str] = None,
                      pdf_text: str = "") -> Optional[str]:
    """Ask Groq. Returns None when every model failed or was rejected.

    `diag`, if given, collects one entry per rejection so the API response can
    explain a fallback instead of leaving it a mystery.
    """
    _diag = diag if diag is not None else []
    _diag.append({"key_present": bool((os.environ.get("GROQ_API_KEY") or "").strip()),
                  "httpx": httpx is not None})
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key or httpx is None:
        return None
    # For a follow-up, search with the follow-up text AND the previous user
    # turn, so "explain more" still retrieves the right chapter.
    search_text = question
    if history:
        prev_user = ""
        for t in reversed(history):
            role = t.get("role") if isinstance(t, dict) else getattr(t, "role", "")
            text = t.get("text") if isinstance(t, dict) else getattr(t, "text", "")
            if role == "user" and text:
                prev_user = text
                break
        if prev_user and len(question.split()) <= 8:
            search_text = prev_user + " " + question

    knowledge_chunks = await retrieve_knowledge_chunks(search_text, limit=5)
    anchors = retrieve_anchors(search_text, limit=3)
    tier = assess_grounding(knowledge_chunks, anchors)
    ctx_parts = []
    if chapter:
        ctx_parts.append(f"Current chapter context: {chapter.get('chapterTitle')} ({chapter.get('subject')}).")
    if knowledge_chunks:
        # Token budget. Groq's free tier allows only 8,000 tokens per minute and
        # the requested max_tokens is reserved against it too, so pushing five
        # full PDF pages into the prompt left room for about one question a
        # minute. Each chunk is clipped; the model needs the provision and the
        # working, not a whole scanned page.
        material_text = "\n".join([
            f"[{c['id']}] {c['subject']} - {c['chapter']} - {c['topic']}: "
            f"{_clip_chunk(c.get('content') or '')}"
            for c in knowledge_chunks
        ])
        ctx_parts.append(f"Relevant CA Inter Material (use ONLY this, top 5 retrieved):\n{material_text}")
    if anchors:
        ctx_parts.append(f"AUTHORITATIVE PROVISION ANCHORS (GROUND TRUTH - MUST use verbatim, 100% correct): {' | '.join(anchors)}.")
    subject = (chapter or {}).get('subject') or ''
    if subject:
        ctx_parts.append(
            f"Paper: {subject}. Presentation rules for this paper: "
            f"{ICAI_PAPER_FORMAT.get(subject, '')}"
        )
    ctx = "\n\n".join(ctx_parts) + "\n\n" if ctx_parts else ""

    system_prompt = build_system_prompt(mode, subject, tier)

    # ---- conversation memory: replay the last few turns (ChatGPT-style) ----
    messages = [{"role": "system", "content": system_prompt}]
    replayed = 0
    if history:
        for t in history[-8:]:
            role = t.get("role") if isinstance(t, dict) else getattr(t, "role", "")
            text = t.get("text") if isinstance(t, dict) else getattr(t, "text", "")
            if role not in ("user", "assistant") or not (text or "").strip():
                continue
            messages.append({"role": role, "content": text.strip()[:6000]})
            replayed += 1

    user_text = ctx + (
        f"Question type detected: {mode}.\n"
        f"Grounding tier: {tier}.\n"
        + ("This is a follow-up in an ongoing conversation - continue from the "
           "previous turns, do not repeat what you already said.\n" if replayed else "")
        + (f"Uploaded document text (read it, it holds the question):\n{pdf_text[:6000]}\n\n"
           if pdf_text else "")
        + f"Question: {question}\n\n"
        "Write the answer in the required ICAI skeleton for this question type, "
        "following the grounding rules given in your instructions. End with the "
        "conclusion or final answer - never with an offer or a question back to "
        "the student."
    )
    if image_data_url:
        # The question is in the picture, not in the text, so ask the model to
        # read it back first. That lets the student check the transcription and
        # spot a misread figure before trusting the working.
        user_text += (
            "\n\nAn image of the question is attached. Begin your reply with a "
            "single line in exactly this form:\n"
            "**Question read from the image:** <the full question as you see it>\n"
            "Then answer it in the ICAI skeleton. If the picture is too blurred "
            "or does not contain a question, say so in one short line and stop."
        )
        messages.append({"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]})
    else:
        messages.append({"role": "user", "content": user_text})
    groq_errors = []
    # Only qwen reads images. A text model would silently ignore the picture.
    models_to_try = [VISION_MODEL] if image_data_url else MODELS_PRIORITY
    for model in models_to_try:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "max_tokens": 1500,
                        "top_p": 0.9,
                        "messages": messages,
                    },
                )
            if r.status_code != 200:
                groq_errors.append(f"{model}={r.status_code}")
                _diag.append({"model": model, "http": r.status_code,
                              "body": r.text[:200]})
                print(f"Groq {model} failed {r.status_code}: {r.text[:200]}")
                continue
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            content = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning") or "").strip()
            final = content if len(content) > 20 else reasoning
            # repair small violations before judging the answer
            final = _sanitize_answer(final)
            if not final or len(final) < 80:
                continue
            if image_data_url:
                # A short "the photo is unreadable, please retake it" reply is a
                # correct answer for an image request, and trimming a trailing
                # question would destroy it. Emoji are still stripped.
                print(f"Groq {model} vision answer: {len(final)} chars")
                return final
            if _is_bad_answer(final):
                reason = "emoji" if _has_emoji(final) else (
                    "ends-with-question" if final.rstrip().endswith("?") else (
                        "cta-in-tail" if any(
                            b in final.lower()[-300:] for b in
                            ("want me to", "shall i ", "let me know", "would you like",
                             "brutal truth", "i can also", "feel free to ask",
                             "here is your answer", "i hope this helps")
                        ) else "short-or-repetitive"
                    )
                )
                print(f"Bad answer filtered from {model} (reason: {reason}): {final[:180]!r}")
                groq_errors.append(f"{model}=rejected:{reason}")
                _diag.append({"model": model, "reason": reason, "head": final[:120]})
                continue
            print(f"Groq {model} success: {len(final)} chars")
            return final
        except Exception as e:
            groq_errors.append(f"{model}=exc")
            _diag.append({"model": model, "exception": str(e)[:200]})
            print(f"Groq {model} exception: {e}")
            continue

    if groq_errors:
        print(
            "!! ALL GROQ MODELS FAILED: " + ", ".join(groq_errors) +
            " - falling back to offline answers. 404/model_not_found means the "
            "model list is out of date (see console.groq.com/docs/deprecations); "
            "401 means GROQ_API_KEY is invalid.",
            flush=True,
        )
    return None


@router.post("/ask")
async def ask(body: AskBody):
    chit = _smalltalk(body.question)
    if chit:
        return {"answer": chit, "mode": "chitchat", "chapter": None, "rag_chunks": 0}
    image_data_url, pdf_text, att_error = _build_attachment(body)
    if att_error:
        return {
            "answer": att_error,
            "mode": "attachment",
            "cached": False,
            "answerFormat": "notice",
            "grounding": "none",
            "chapter": None,
            "rag_chunks_used": 0,
            "anchors_used": 0,
            "retrieved_topics": [],
        }

    chapter = match_chapter(body.question, body.chapterId)

    # ICAI answer mode for this question type (cheap, regex only)
    ans_mode = detect_answer_mode(body.question)

    # A follow-up depends on the conversation, so it can never be served from
    # the cache - only standalone questions can. An uploaded image is unique to
    # the student who sent it, so it is never cached either.
    cache_key = None if (body.history or image_data_url or pdf_text) else _cache_key(body.question, ans_mode)
    if cache_key:
        hit = await _cache_get(cache_key)
        if hit:
            print(f"answer cache HIT: {(body.question or '')[:60]}")
            return {
                "answer": hit["answer"],
                "mode": "live-rag",
                "cached": True,
                "groq_diag": [{"cache": "hit"}],
                "answerFormat": hit.get("answer_format") or ans_mode,
                "grounding": hit.get("grounding") or "full",
                "chapter": {"id": chapter.get("chapterId"), "title": chapter.get("chapterTitle"),
                            "subject": chapter.get("subject")} if chapter else None,
                "rag_chunks_used": hit.get("chunks") or 0,
                "anchors_used": 0,
                "retrieved_topics": [],
            }

    # When the question is only in the picture there is no text to search on,
    # so retrieval is skipped rather than run against a placeholder.
    if image_data_url and len((body.question or "").split()) < 6:
        knowledge_chunks, anchors, tier = [], [], "image"
    else:
        knowledge_chunks = await retrieve_knowledge_chunks(body.question, 5)
        anchors = retrieve_anchors(body.question, 3)
        tier = assess_grounding(knowledge_chunks, anchors)

    _diag = []
    answer = await groq_answer(body.question, chapter, ans_mode, body.history, _diag,
                               image_data_url=image_data_url, pdf_text=pdf_text)
    if not answer and image_data_url:
        # The offline notes cannot see a photograph, so never dress up a text
        # fallback as an answer to a picture.
        answer = ("I could not read that question right now - the AI service is "
                  "busy. Please send it again in a moment, or type the question "
                  "out and I will answer from the module.")
        mode = "image-busy"
    elif not answer:
        answer = await offline_answer(body.question, chapter, ans_mode, tier)
        mode = "syllabus-brain-rag"
    else:
        mode = "live-rag"
        # only a real Groq answer is worth remembering
        if cache_key:
            await _cache_put(cache_key, body.question, ans_mode, answer, tier,
                             len(knowledge_chunks))
    return {
        "answer": answer,
        "mode": mode,
        "cached": False,
        "groq_diag": _diag,
        "answerFormat": ans_mode,
        "grounding": tier,
        "chapter": {"id": chapter.get("chapterId"), "title": chapter.get("chapterTitle"),
                    "subject": chapter.get("subject")} if chapter else None,
        "rag_chunks_used": len(knowledge_chunks),
        "anchors_used": len(anchors),
        "retrieved_topics": [c["topic"] for c in knowledge_chunks[:3]]
    }


@router.get("/format-preview")
async def format_preview(q: str):
    """Debug: which ICAI skeleton will this question get?"""
    mode = detect_answer_mode(q)
    chapter = match_chapter(q, None)
    subject = (chapter or {}).get("subject") or ""
    return {
        "question": q,
        "answerFormat": mode,
        "subject": subject,
        "skeleton": _MODE_SKELETON.get(mode, ""),
        "paperRules": ICAI_PAPER_FORMAT.get(subject, ""),
    }


@router.get("/kb-search")
async def kb_search(q: str, limit: int = 5):
    chunks = await retrieve_knowledge_chunks(q, limit)
    anchors = retrieve_anchors(q, 3)
    return {
        "query": q,
        "chunks": chunks,
        "anchors": anchors,
        "count": len(chunks)
    }


@router.get("/kb-stats")
async def kb_stats_public():
    try:
        from db import get_db, KNOWLEDGE_CHUNKS
        db = get_db()
        mongo_count = await db[KNOWLEDGE_CHUNKS].count_documents({})
        by_subject = {}
        pipeline = [{"$group": {"_id": "$subject", "count": {"$sum": 1}}}]
        async for doc in db[KNOWLEDGE_CHUNKS].aggregate(pipeline):
            by_subject[doc["_id"]] = doc["count"]
        return {
            "mongo_chunks": mongo_count,
            "by_subject": by_subject,
            "status": "MongoDB RAG live" if mongo_count > 100 else "MongoDB empty, using file fallback"
        }
    except Exception as e:
        return {"mongo_chunks": 0, "error": str(e), "status": "MongoDB not available, file fallback"}
