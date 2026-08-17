"""
Seed ALL 94 chapters with 50 questions each (30 plain + 20 scenario-linked) = 4700 questions
This gives you the 4700 count you wanted, using synthetic demo content (like seed_demo but for all chapters).
Real ICAI content requires running the AI pipeline (content-pipeline) with OpenAI key + Drive.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from db import (
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    ensure_indexes,
    get_db,
)

CATALOG_PATH = Path(__file__).parent.parent / "content-pipeline" / "config" / "chapters.json"

def _q(chapter, i, question_type="mcq", scenario=None):
    n = f"{i:03d}"
    return {
        "id": f"adp_q_{chapter['chapterId']}_{n}",
        "revision": 1,
        "chapterId": chapter["chapterId"],
        "subject": chapter["subject"],
        "paper": chapter["paper"],
        "section": chapter.get("section", ""),
        "module": chapter["module"],
        "chapterNumber": chapter["chapterNumber"],
        "chapterTitle": chapter["chapterTitle"],
        "questionType": question_type,
        "difficulty": ["easy", "moderate", "hard"][i % 3],
        "conceptTags": [f"{chapter['chapterId']}-concept-a", f"{chapter['chapterId']}-concept-b"],
        "prompt": f"[{chapter['chapterTitle']}] Q{n}: Which statement is correct regarding {chapter['chapterTitle']}?",
        "options": [
            {"id": "A", "text": f"Statement A is correct for {chapter['chapterId']} Q{n}"},
            {"id": "B", "text": f"Statement B is correct for {chapter['chapterId']} Q{n}"},
            {"id": "C", "text": f"Statement C is correct for {chapter['chapterId']} Q{n}"},
            {"id": "D", "text": f"Statement D is correct for {chapter['chapterId']} Q{n}"},
        ],
        "correctOptionId": ["A", "B", "C", "D"][i % 4],
        "explanation": f"Explanation for {chapter['chapterId']} Q{n}: Option {['A','B','C','D'][i%4]} reflects correct treatment as per ICAI {chapter['module']}.",
        "icaiSourceRefs": [{"source": "module", "module": chapter["module"], "chapter": chapter["chapterNumber"], "section": f"1.{i % 7 + 1}", "edition": "May 2026"}],
        "calibrationRefs": [{"source": "MTP", "attempt": "May 2026", "questionRef": f"Q{(i % 10) + 1}", "calibrationNote": "Synthetic 94-chapter seed"}],
        "generationMeta": {"model": "synthetic-94-seed", "promptVersion": "94x50", "generatedAt": datetime.now(timezone.utc).isoformat()},
        "scenario": scenario,
        "attemptSpecificRisk": False,
        "status": "needs_review",
        "statusHistory": [{"from": "generated", "to": "needs_review", "by": "seed-all-94", "at": datetime.now(timezone.utc).isoformat()}],
        "validation": {"errors": [], "warnings": []},
        "similarity": {"verdict": "clean", "maxSourceSimilarity": 0.1, "maxBankSimilarity": 0.1},
    }


async def seed_all():
    db = get_db()
    await ensure_indexes()
    
    if not CATALOG_PATH.is_file():
        print(f"Catalog not found at {CATALOG_PATH}")
        return
    
    catalog_data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    chapters = catalog_data.get("chapters", []) if isinstance(catalog_data, dict) else catalog_data
    
    print(f"Seeding {len(chapters)} chapters with 50 questions each = {len(chapters)*50} total...")
    
    total_questions = 0
    total_scenarios = 0
    
    for chapter_idx, chapter in enumerate(chapters):
        # Ensure chapter dict has required fields
        chapter.setdefault("section", "")
        chapter.setdefault("paper", f"Paper {chapter_idx//15 + 1}")
        chapter.setdefault("module", f"Module {(chapter_idx%5)+1}")
        chapter.setdefault("group", f"Group {(chapter_idx%2)+1}")
        
        plain = []
        scenario_questions = []
        scenarios = []
        
        # 30 plain MCQs
        for i in range(30):
            q = _q(chapter, i+1, "mcq", None)
            plain.append(q)
        
        # 5 scenarios x 4 linked = 20 scenario_mcqs
        for s in range(5):
            scenario_id = f"adp_s_{chapter['chapterId']}_{s+1:02d}"
            qids = []
            for k in range(4):
                seq = 31 + s*4 + k
                link = {"scenarioId": scenario_id, "seq": k+1, "blockTotal": 4}
                q = _q(chapter, seq, "scenario_mcq", link)
                scenario_questions.append(q)
                qids.append(q["id"])
            
            scenarios.append({
                "scenarioId": scenario_id,
                "revision": 1,
                "chapterId": chapter["chapterId"],
                "passage": f"Case study {s+1} for {chapter['chapterTitle']}. A company faces a situation involving {chapter['chapterTitle']}. Facts: Company XYZ has transactions related to this chapter. Analyze and answer the linked questions.",
                "icaiSourceRefs": [{"source": "module", "module": chapter["module"], "chapter": chapter["chapterNumber"], "section": f"2.{s+1}", "edition": "May 2026"}],
                "calibrationRefs": [{"source": "RTP", "attempt": "May 2026", "questionRef": f"Case {s+1}", "calibrationNote": "Synthetic"}],
                "attemptSpecificRisk": False,
                "questionIds": qids,
                "status": "needs_review",
                "statusHistory": [{"from": "generated", "to": "needs_review", "by": "seed-all-94", "at": datetime.now(timezone.utc).isoformat()}],
                "validation": {"errors": [], "warnings": []},
            })
        
        # Upsert questions and scenarios
        for q in plain + scenario_questions:
            await db[CONTENT_QUESTIONS].update_one({"id": q["id"]}, {"$set": q}, upsert=True)
            total_questions += 1
        
        for s in scenarios:
            await db[CONTENT_SCENARIOS].update_one({"scenarioId": s["scenarioId"]}, {"$set": s}, upsert=True)
            total_scenarios += 1
        
        # Chapter record
        await db[CONTENT_CHAPTERS].update_one(
            {"chapterId": chapter["chapterId"]},
            {"$set": {
                "chapterId": chapter["chapterId"],
                "chapterTitle": chapter["chapterTitle"],
                "subject": chapter["subject"],
                "paper": chapter.get("paper", ""),
                "section": chapter.get("section", ""),
                "module": chapter["module"],
                "chapterNumber": chapter["chapterNumber"],
                "group": chapter.get("group", "Group 1"),
                "catalogMatch": {"valid": True, "catalogRevision": "94-seed"},
                "coverage": {
                    "plainApproved": 0, "plainTarget": 30,
                    "scenariosApproved": 0, "scenariosTarget": 5,
                    "scenarioMcqsApproved": 0, "scenarioMcqsTarget": 20,
                },
                "status": "needs_review",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True
        )
        
        if (chapter_idx + 1) % 10 == 0:
            print(f"  Seeded {chapter_idx+1}/{len(chapters)} chapters...")
    
    print(f"\n✅ Done! Seeded {len(chapters)} chapters")
    print(f"   Questions: {total_questions} (should be {len(chapters)*50})")
    print(f"   Scenarios: {total_scenarios} (should be {len(chapters)*5})")
    print(f"   Review Queue will now show {total_questions} questions")

    # Dump to content-store.json so dev_server can restore quickly on Render (fast restore vs slow seed)
    try:
        from persist import dump_store
        await dump_store()
        from persist import store_path
        p = store_path()
        if p.is_file():
            size_kb = p.stat().st_size / 1024
            print(f"   Dumped to {p} ({size_kb:.1f} KB) for fast restore on Render")
    except Exception as e:
        print(f"   Dump failed: {e}")
    
    # Also delete old demo 2-chapter records if they exist? Keep them, they will be overwritten by upsert if same id, but our ids are adp_q_advanced-accounting-1_001 etc, different from ch-acc-01
    # So count will be 100 + 4700 = 4800. Let's clean old ch-acc-* if we want exact 4700
    # For now keep both, or optionally delete demo:
    # await db[CONTENT_QUESTIONS].delete_many({"chapterId": {"$in": ["ch-acc-01", "ch-law-03"]}})
    # await db[CONTENT_SCENARIOS].delete_many({"chapterId": {"$in": ["ch-acc-01", "ch-law-03"]}})
    # await db[CONTENT_CHAPTERS].delete_many({"chapterId": {"$in": ["ch-acc-01", "ch-law-03"]}})


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_all())
