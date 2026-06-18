"""Vercel Python entrypoint.

Vercel loads the top-level `app` (an ASGI FastAPI instance) from this file and
serves it as a single serverless function handling /api/* requests. The static
UI in /public is served separately by Vercel's CDN.
"""

from app.scoring.app import app  # noqa: F401  (Vercel looks for `app`)
