"""Local development server: optionally seeds demo data, then serves the API.

    MONGO_URL=memory:// DEV_AUTH_BYPASS=1 SEED_DEMO=1 \
        python -m dev_server --port 8010

DEV_AUTH_BYPASS=1 is local-development only (documented in .env.example);
production always requires JWT (mentor login).
"""
import asyncio
import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(__file__))

from db import ensure_indexes  # noqa: E402


async def maybe_seed():
    if os.environ.get("SEED_DEMO") == "1":
        import seed_demo

        await seed_demo.seed()
    else:
        await ensure_indexes()


def main():
    port = int(os.environ.get("PORT", "8010"))
    asyncio.run(maybe_seed())
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
