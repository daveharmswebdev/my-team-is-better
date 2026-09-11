"""apps/api's own `.env` loader and small config surface (issue #4).

Deliberately not a reuse of `cfb_strength.config`'s private `_load_dotenv` --
that's the engine's own internal helper for its own `.env`, not part of the
public evidence/db.connection surface this app is scoped to (per this app's
Architecture Brief layering rule). This module loads `apps/api/.env` (via
`python-dotenv`, gitignored, present locally for dev) and exposes:

- `DATABASE_URL` / `ANTHROPIC_API_KEY`: `None` when unset (e.g. in CI, which
  intentionally has neither -- see CLAUDE.md/issue #4's negative scope).
- `PROMPT_VERSION`: bumped whenever the persona system prompt text in
  `api.persona.prompt` changes, so the Postgres response cache
  (`api.persona.cache`) auto-busts on a prompt edit instead of serving
  stale narration under a new voice.
- `CONTESTED_YEARS`: the first place this constant is defined anywhere in
  the project (checked -- no equivalent exists in `packages/cfb-engine`);
  scoped to `apps/api` only, per issue #4's brief.
- `CORS_ALLOWED_ORIGINS`: comma-separated allowlist of browser origins
  permitted to call this API (issue #13). Defaults to
  `["http://localhost:5173"]` (the Vite dev server's default port) when
  unset, so local dev works out of the box with no `.env` change required --
  unlike `DATABASE_URL`/`ANTHROPIC_API_KEY`, this one intentionally never
  falls back to `None`, since an empty allowlist would make `apps/web` fail
  silently at the browser rather than at startup.
- `APP_TEST_MODE`: `True` only when the env var is set to the exact string
  `"1"` (issue #39's groundwork). Lets a real `uvicorn` process boot with no
  live Postgres instance and no real `ANTHROPIC_API_KEY` -- e.g. for the
  Playwright e2e job, which runs this API over real HTTP rather than
  FastAPI's in-process `TestClient` (see `api.deps`'s `get_narration_cache`/
  `get_narrator`, which branch on this flag). Distinct from `DATABASE_URL`
  being merely unset: this is an explicit "run in test mode" signal, not an
  absence of config.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parents[2]  # apps/api/
_ENV_FILE = Path(os.environ.get("MY_TEAM_IS_BETTER_API_ENV_FILE", APP_ROOT / ".env"))

# `override=False` (the default) -- never stomps on a variable already set
# in the real environment (e.g. by Render, or by a test's monkeypatch run
# before this module is (re-)imported).
load_dotenv(_ENV_FILE, override=False)

DATABASE_URL: str | None = os.environ.get("DATABASE_URL")
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")

_CORS_ALLOWED_ORIGINS_RAW: str | None = os.environ.get("CORS_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGINS: list[str] = (
    [origin.strip() for origin in _CORS_ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]
    if _CORS_ALLOWED_ORIGINS_RAW
    else ["http://localhost:5173"]
)

PROMPT_VERSION = "persona-v1"

CONTESTED_YEARS: set[int] = {2003, 2017}

APP_TEST_MODE: bool = os.environ.get("APP_TEST_MODE") == "1"
