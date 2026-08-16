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

    if _flag("SEED_DEMO"):
        import seed_demo

        await seed_demo.seed()

    if _flag("IMPORT_GENERATED"):
        import import_original

        report = await import_original.run_import(
            os.environ.get("GENERATED_DIR"),
            purge_demo_data=not _flag("KEEP_DEMO"),
            force=_flag("IMPORT_FORCE"),
        )
        if not report.get("ok"):
            print("[dev_server] generated content not imported — the API starts with an empty content DB.")


def main():
    port = int(os.environ.get("PORT", "8010"))
    asyncio.run(bootstrap())
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
