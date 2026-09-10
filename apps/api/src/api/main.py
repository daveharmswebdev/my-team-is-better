"""FastAPI application entrypoint for apps/api.

Per docs/ARCHITECTURE.md §2, this app is a top-layer consumer of the
cfb-engine, exactly like cli.py and mcp_server/ -- it may only import
cfb_strength.evidence and cfb_strength.db.connection, never
cfb_strength.ratings or cfb_strength.ingest directly.

`/api/verdict/*` (issue #3) implements PRD §5.1's three structured question
types as raw-evidence JSON, no persona/narration. No Claude API integration
yet (see issue #4). This module wires up the app, the liveness check, the
verdict router, and the engine-exception -> HTTP mapping.
"""

from fastapi import FastAPI

from api.errors import register_exception_handlers
from api.verdict import router as verdict_router

app = FastAPI(title="My Team Is Better API")
app.include_router(verdict_router)
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
