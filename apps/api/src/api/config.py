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

PROMPT_VERSION = "persona-v1"

CONTESTED_YEARS: set[int] = {2003, 2017}
