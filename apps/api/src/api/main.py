"""FastAPI application entrypoint for apps/api.

Per docs/ARCHITECTURE.md §2, this app is a top-layer consumer of the
cfb-engine, exactly like cfb_strength.cli and cfb_strength.mcp_server are --
it may import cfb_strength.evidence, cfb_strength.db, cfb_strength.contracts
and cfb_strength.config, and no other top-level engine module. That rule is
checked rather than merely documented (issue #54): `apps/api/.importlinter`
fails on a violating import, and tests/test_import_layering_classification.py
fails on any engine module left unclassified.

`/api/verdict/*` implements PRD §5.1's three structured question types as
evidence JSON (issue #3) wrapped in a persona narration envelope (issue
#4). `/api/years` and `/api/teams` (issue #13) are plain evidence-catalog
reads backing `apps/web`'s year/team picker fields. This module wires up the
app, the liveness check, both routers, the engine-exception -> HTTP mapping,
CORS (issue #14, so the browser-based `apps/web` frontend on a separate
origin can call these routes), and (via `lifespan`) the one-time
`ensure_schema` call for issue #4's Postgres response cache -- a `lifespan`
context manager rather than the deprecated `@app.on_event("startup")`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.catalog import router as catalog_router
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
app.include_router(catalog_router)
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
