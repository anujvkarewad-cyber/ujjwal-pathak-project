"""Seed demo data for the mentor AI Content + Analytics screens.

Creates SYNTHETIC demo records only (clearly-marked demo content, no real ICAI
material): one chapter with 30 plain + 5 scenario blocks in `needs_review`,
one approved chapter, consent records and summaries for a few demo students,
and follow-ups. Run:  MONGO_URL=memory:// python -m backend.seed_demo
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from db import (
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    ensure_indexes,
    get_db,
)

CHAPTERS = [
    {
        "chapterId": "ch-acc-01", "subject": "Accounting", "paper": "Paper 1", "section": "Accounting Standards",
        "module": "Module 1", "chapterNumber": 1, "chapterTitle": "Introduction to Accounting Standards", "group": "Group 1",
    },
    {
        "chapterId": "ch-law-03", "subject": "Law", "paper": "Paper 2", "section": "Business Laws",
        "module": "Module 2", "chapterNumber": 3, "chapterTitle": "Companies Act, 2013 — Incorporation", "group": "Group 1",
    },
]

DEMO_STUDENTS = ["S-1001", "S-1002", "S-1003", "S-1004", "S-1005", "S-1006"]
BANDS = ["Not assessed", "Weak", "Medium", "Strong", "Mastered"]


def _q(chapter, i, question_type="mcq", scenario=None):
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
        "conceptTags": ["demo-concept-a", "demo-concept-b"],
        "prompt": f"DEMO question {n} for {chapter['chapterTitle']}: which of the following statements is correct?",
        "options": [
            {"id": "A", "text": f"Statement A is correct for demo {n}"},
            {"id": "B", "text": f"Statement B is correct for demo {n}"},
            {"id": "C", "text": f"Statement C is correct for demo {n}"},
            {"id": "D", "text": f"Statement D is correct for demo {n}"},
        ],
        "correctOptionId": "A",
        "explanation": f"DEMO explanation for question {n}: option A reflects the correct treatment.",
        "icaiSourceRefs": [{"source": "module", "module": chapter["module"], "chapter": chapter["chapterNumber"], "section": f"1.{i % 7 + 1}", "edition": "May 2026"}],
        "calibrationRefs": [{"source": "MTP", "attempt": "May 2026", "questionRef": f"Q{(i % 10) + 1}", "calibrationNote": "DEMO calibration"}],
        "generationMeta": {"model": "demo-seed", "promptVersion": "demo", "generatedAt": datetime.now(timezone.utc).isoformat()},
        "scenario": scenario,
        "attemptSpecificRisk": False,
        "status": "needs_review",
        "statusHistory": [{"from": "generated", "to": "needs_review", "by": "demo-seed", "at": datetime.now(timezone.utc).isoformat()}],
        "validation": {"errors": [], "warnings": []},
        "similarity": {"verdict": "clean", "maxSourceSimilarity": 0.1, "maxBankSimilarity": 0.1},
    }


async def seed():
    db = get_db()
    await ensure_indexes()
    now = datetime.now(timezone.utc).isoformat()

    for chapter in CHAPTERS:
        plain = [_q(chapter, i + 1) for i in range(30)]
        scenario_questions = []
        scenarios = []
        for s in range(5):
            scenario_id = f"adp_s_{chapter['chapterId']}_{s + 1:02d}"
            qids = []
            for k in range(4):
                seq = 31 + s * 4 + k
                link = {"scenarioId": scenario_id, "seq": k + 1, "blockTotal": 4}
                q = _q(chapter, seq, "scenario_mcq", link)
                scenario_questions.append(q)
                qids.append(q["id"])
            scenarios.append({
                "scenarioId": scenario_id,
                "revision": 1,
                "chapterId": chapter["chapterId"],
                "passage": f"DEMO case study {s + 1} for {chapter['chapterTitle']}. A hypothetical company faces a practical situation involving the concepts of this chapter. The facts are presented for practice only.",
                "icaiSourceRefs": [{"source": "module", "module": chapter["module"], "chapter": chapter["chapterNumber"], "section": f"2.{s + 1}", "edition": "May 2026"}],
                "calibrationRefs": [{"source": "RTP", "attempt": "May 2026", "questionRef": f"Case {s + 1}", "calibrationNote": "DEMO calibration"}],
                "attemptSpecificRisk": False,
                "questionIds": qids,
                "status": "needs_review",
                "statusHistory": [{"from": "generated", "to": "needs_review", "by": "demo-seed", "at": now}],
                "validation": {"errors": [], "warnings": []},
            })

        for q in plain + scenario_questions:
            await db[CONTENT_QUESTIONS].update_one({"id": q["id"]}, {"$setOnInsert": q}, upsert=True)
        for s in scenarios:
            await db[CONTENT_SCENARIOS].update_one({"scenarioId": s["scenarioId"]}, {"$setOnInsert": s}, upsert=True)

        # ch-acc-01: everything needs_review. ch-law-03: pre-approve to demo coverage.
        status = "needs_review" if chapter["chapterId"] == "ch-acc-01" else "approved"
        await db[CONTENT_QUESTIONS].update_many({"chapterId": chapter["chapterId"]}, {"$set": {"status": status}})
        await db[CONTENT_SCENARIOS].update_many({"chapterId": chapter["chapterId"]}, {"$set": {"status": status}})
        await db[CONTENT_CHAPTERS].update_one(
            {"chapterId": chapter["chapterId"]},
            {"$set": {
                "chapterId": chapter["chapterId"],
                "chapterTitle": chapter["chapterTitle"],
                "subject": chapter["subject"],
                "group": chapter["group"],
                "catalogMatch": {"valid": True, "catalogRevision": "may-2026"},
                "coverage": {
                    "plainApproved": 30 if status == "approved" else 0, "plainTarget": 30,
                    "scenariosApproved": 5 if status == "approved" else 0, "scenariosTarget": 5,
                    "scenarioMcqsApproved": 20 if status == "approved" else 0, "scenarioMcqsTarget": 20,
                },
                "status": status,
                "updatedAt": now,
            }},
            upsert=True,
        )

    # Consent + summaries for demo students
    for idx, sid in enumerate(DEMO_STUDENTS):
        sharing = idx != 3  # S-1004 has sharing off
        await db[ANALYTICS_CONSENTS].update_one(
            {"studentId": sid}, {"$set": {"studentId": sid, "sharing": sharing, "updatedAt": now}}, upsert=True
        )
        if not sharing:
            continue
        for j, chapter in enumerate(CHAPTERS):
            band = BANDS[(idx + j) % len(BANDS)]
            await db[ANALYTICS_SUMMARIES].update_one(
                {"studentId": sid, "chapterId": chapter["chapterId"]},
                {"$set": {
                    "studentId": sid,
                    "chapterId": chapter["chapterId"],
                    "subject": chapter["subject"],
                    "group": chapter["group"],
                    "masteryBand": band,
                    "attemptCount": (idx + 1) * 12 + j,
                    "accuracyRange": {"Not assessed": "0-49", "Weak": "0-49", "Medium": "50-69", "Strong": "70-84", "Mastered": "85-100"}[band],
                    "lastActivityDate": (date.today() - timedelta(days=(idx * 5) % 20)).isoformat(),
                    "weakConceptTags": ["demo-concept-a"] if band in ("Weak", "Not assessed") else [],
                    "syncedAt": now,
                }},
                upsert=True,
            )

    await db[ANALYTICS_FOLLOWUPS].update_one(
        {"followupId": "demo-fu-1"},
        {"$setOnInsert": {
            "followupId": "demo-fu-1", "studentId": "S-1002", "title": "DEMO follow-up: review weak chapter",
            "priority": "medium", "rule": "weak_chapter", "status": "open", "createdAt": now, "createdBy": "demo-seed", "notes": [],
        }},
        upsert=True,
    )

    print("Demo data seeded (synthetic content only).")
    print("  - ch-acc-01: 50 questions in review queue (needs_review)")
    print("  - ch-law-03: pre-approved (30/5/20) to demo the coverage matrix")
    print("  - students:", DEMO_STUDENTS)
    print("Login credentials come from backend/.env (MENTOR_EMAIL / MENTOR_PASSWORD_HASH).")


if __name__ == "__main__":
    asyncio.run(seed())
