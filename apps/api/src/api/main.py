"""FastAPI application entrypoint for apps/api.

Per docs/ARCHITECTURE.md §2, this app is a top-layer consumer of the
cfb-engine, exactly like cli.py and mcp_server/ -- it may only import
cfb_strength.evidence and cfb_strength.db.connection, never
cfb_strength.ratings or cfb_strength.ingest directly.

No verdict/question logic here yet (see GitHub issue #3) and no Claude API
integration yet (see issue #4). This module currently only wires up the app
and a liveness check.
"""

from fastapi import FastAPI

app = FastAPI(title="My Team Is Better API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
