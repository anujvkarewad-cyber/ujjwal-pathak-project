# Vercel serverless entry point (Python runtime, ASGI).
# Vercel looks for an `app` object in api/*.py — we expose the same FastAPI
# app the uvicorn server uses, so the whole mentor API runs serverless:
# no sleeping, no monthly hour limits, free on the Hobby plan.
import sys
from pathlib import Path

# Make the backend package (parent of api/) importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app  # noqa: E402,F401
