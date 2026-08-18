"""Local development / Render bootstrap."""
import asyncio
import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(__file__))

from db import ensure_indexes  # noqa: E402


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def bootstrap():
    await ensure_indexes()

    from persist import dump_store_sync, restore_store, should_persist, uses_real_mongo

    restored = False
    if uses_real_mongo():
        print("[dev_server] MONGO_URL is a real database — skipping JSON restore")
    elif should_persist():
        restored = await restore_store()
        if restored:
            print("[dev_server] restored previous mentor approvals from disk")

    if _flag("SEED_ALL") and not restored:
        import seed_all_94
        await seed_all_94.seed_all()
        await dump_store_sync()
        print("[dev_server] SEED_ALL complete - 4700 questions ready")
        return

    if _flag("SEED_DEMO") and not restored:
        import seed_demo
        await seed_demo.seed()

    import_success = False
    if _flag("IMPORT_GENERATED"):
        from db import CONTENT_QUESTIONS, get_db

        existing = 0
        try:
            existing = await get_db()[CONTENT_QUESTIONS].count_documents({})
        except Exception as exc:
            print(f"[dev_server] could not count existing questions: {exc}")

        if existing and not _flag("IMPORT_FORCE"):
            print(
                f"[dev_server] store already has {existing} questions — "
                "skipping generated import (set IMPORT_FORCE=1 to re-import)"
            )
            import_success = True
        else:
            import import_original

            report = await import_original.run_import(
                os.environ.get("GENERATED_DIR"),
                purge_demo_data=not _flag("KEEP_DEMO"),
                force=_flag("IMPORT_FORCE"),
            )
            if not report.get("ok"):
                print("[dev_server] generated content not imported — will fallback to demo seed if available.")
            else:
                print(
                    f"[dev_server] imported {report.get('chapters', 0)} chapters, "
                    f"{report.get('questions', 0)} questions"
                )
                await dump_store_sync()
                import_success = True

    if not import_success and not restored:
        try:
            from db import get_db, CONTENT_QUESTIONS
            db = get_db()
            count = await db[CONTENT_QUESTIONS].count_documents({})
            if count == 0:
                print("[dev_server] DB empty and no generated content — seeding demo data for dev...")
                import seed_demo
                await seed_demo.seed()
                await dump_store_sync()
                print("[dev_server] demo seed complete")
        except Exception as e:
            print(f"[dev_server] fallback seed check failed: {e}")
            if not _flag("SEED_DEMO"):
                try:
                    import seed_demo
                    await seed_demo.seed()
                    print("[dev_server] emergency demo seed done")
                except Exception as se:
                    print(f"[dev_server] seed failed: {se}")


def main():
    port = int(os.environ.get("PORT", "8010"))
    asyncio.run(bootstrap())
