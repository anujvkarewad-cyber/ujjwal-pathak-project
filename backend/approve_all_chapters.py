"""
Bulk approve all chapters - makes all 4700 questions appear in student dashboard
Run: python -m approve_all_chapters [--chapter=advanced-accounting-1] [--all]
On Render Shell: python -m approve_all_chapters --all
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from db import CONTENT_CHAPTERS, CONTENT_QUESTIONS, CONTENT_SCENARIOS, get_db

def _now():
    return datetime.now(timezone.utc).isoformat()

async def approve_chapter(chapter_id: str):
    db = get_db()
    # Approve all questions in chapter
    q_result = await db[CONTENT_QUESTIONS].update_many(
        {"chapterId": chapter_id},
        {"$set": {"status": "approved", "approval": {"mentorId": "bulk-approve", "at": _now(), "comments": "Bulk approved for student dashboard"}}}
    )
    s_result = await db[CONTENT_SCENARIOS].update_many(
        {"chapterId": chapter_id},
        {"$set": {"status": "approved", "approval": {"mentorId": "bulk-approve", "at": _now()}}}
    )
    # Then move to release_candidate (publishable)
    await db[CONTENT_QUESTIONS].update_many(
        {"chapterId": chapter_id, "status": "approved"},
        {"$set": {"status": "release_candidate"}}
    )
    await db[CONTENT_SCENARIOS].update_many(
        {"chapterId": chapter_id, "status": "approved"},
        {"$set": {"status": "release_candidate"}}
    )
    await db[CONTENT_CHAPTERS].update_one(
        {"chapterId": chapter_id},
        {"$set": {"status": "release_candidate", "releaseCandidate": {"at": _now(), "by": "bulk-approve"}}}
    )
    print(f"✅ {chapter_id}: {q_result.modified_count} questions -> release_candidate")

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", help="Chapter ID to approve")
    parser.add_argument("--all", action="store_true", help="Approve all chapters")
    args = parser.parse_args()

    db = get_db()
    
    if args.chapter:
        await approve_chapter(args.chapter)
    elif args.all:
        chapters = []
        async for c in db[CONTENT_CHAPTERS].find({}):
            chapters.append(c["chapterId"])
        print(f"Approving {len(chapters)} chapters...")
        for cid in chapters:
            await approve_chapter(cid)
        print(f"\n✅ Done! Approved {len(chapters)} chapters")
        # Show bank count
        count = await db[CONTENT_QUESTIONS].count_documents({"status": {"$in": ["approved", "release_candidate", "published"]}})
        print(f"Student bank.json will now show: {count} questions")
    else:
        print("Usage: python -m approve_all_chapters --all  OR  --chapter=advanced-accounting-1")
        print("Available chapters:")
        async for c in db[CONTENT_CHAPTERS].find({}).sort("chapterId", 1):
            print(f"  {c['chapterId']} - {c.get('chapterTitle','')} (status: {c.get('status')})")

if __name__ == "__main__":
    asyncio.run(main())
