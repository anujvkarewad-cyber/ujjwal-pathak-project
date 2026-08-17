"""Local development server: optionally seeds demo data or imports the real
generated content, then serves the API.

    # demo data (synthetic)
    MONGO_URL=memory:// DEV_AUTH_BYPASS=1 SEED_DEMO=1 python -m dev_server --port 8010

    # the REAL generated chapters (what ./run-backend.sh does)
    MONGO_URL=memory:// DEV_AUTH_BYPASS=1 IMPORT_GENERATED=1 \
        GENERATED_DIR=../student-dashboard-frontend/content-pipeline/generated \
        python -m dev_server

MONGO_URL=memory:// keeps the store inside THIS process, so the import has to
run here (in-process) rather than as a separate command.

DEV_AUTH_BYPASS=1 is local-development only (documented in .env.example);
production always requires JWT (mentor login).
"""
import asyncio
import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(__file__))

from db import ensure_indexes  # noqa: E402


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def bootstrap():
    """Prepare the DB before uvicorn starts serving."""
    await ensure_indexes()

    from persist import dump_store_sync, restore_store

    restored = await restore_store()
    if restored:
        print("[dev_server] restored previous mentor approvals from disk")

    # NEW: SEED_ALL=1 seeds 94 chapters x 50 = 4700 questions (real count)
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
        import import_original

        report = await import_original.run_import(
            os.environ.get("GENERATED_DIR"),
            purge_demo_data=not _flag("KEEP_DEMO"),
            force=_flag("IMPORT_FORCE"),
        )
        if not report.get("ok"):
            print("[dev_server] generated content not imported — will fallback to demo seed if available.")
        else:
            print(f"[dev_server] imported {report.get('chapters',0)} chapters, {report.get('questions',0)} questions")
            await dump_store_sync()
            import_success = True

    # FIX: If no generated content and no restore, auto-seed demo data so Review Queue doesn't show 0 questions
    # This prevents empty DB state that confuses users in envs without content-pipeline/generated
    if not import_success and not restored:
        # Check if DB is empty
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
            # Still try to seed if flag not set — better than empty DB
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
    # server.py's startup hook also bootstraps when IMPORT_GENERATED/SEED_* are
    # set (for `uvicorn server:app` deployments); we already did it here.
    os.environ["BOOTSTRAP_DONE"] = "1"
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
