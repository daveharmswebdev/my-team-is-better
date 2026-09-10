"""FastAPI application entrypoint for apps/api.

Per docs/ARCHITECTURE.md §2, this app is a top-layer consumer of the
cfb-engine, exactly like cli.py and mcp_server/ -- it may only import
cfb_strength.evidence and cfb_strength.db.connection, never
cfb_strength.ratings or cfb_strength.ingest directly.

`/api/verdict/*` implements PRD §5.1's three structured question types as
evidence JSON (issue #3) wrapped in a persona narration envelope (issue
#4). This module wires up the app, the liveness check, the verdict router,
the engine-exception -> HTTP mapping, CORS (issue #13, so the browser-based
`apps/web` frontend on a separate origin can call `/api/verdict/*`), and
(via `lifespan`) the one-time `ensure_schema` call for issue #4's Postgres
response cache -- a `lifespan` context manager rather than the deprecated
`@app.on_event("startup")`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import CORS_ALLOWED_ORIGINS, DATABASE_URL
from api.errors import register_exception_handlers
from api.persona.cache import ensure_schema
from api.verdict import router as verdict_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # `DATABASE_URL` is intentionally unset in CI (see CLAUDE.md/issue #4's
    # negative scope) -- skip schema setup rather than failing startup.
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL) as conn:
            ensure_schema(conn)
    yield


app = FastAPI(title="My Team Is Better API", lifespan=lifespan)
# Guest-first per PRD §5.3 -- no cookies/auth on this path, so an explicit
# origin allowlist with `allow_credentials=False` (never `allow_origins=["*"]`
# with credentials, and never credentialed CORS this app doesn't need).
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(verdict_router)
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
