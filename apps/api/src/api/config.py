"""apps/api's own `.env` loader and small config surface (issue #4).

Deliberately not a reuse of `cfb_strength.config`'s private `_load_dotenv`.
`cfb_strength.config` itself is on this app's permitted-import list (see
docs/ARCHITECTURE.md §2; `api.deps` imports `DB_PATH` from it), so this is a
privacy boundary rather than a layering one: `_load_dotenv` is the engine's
own internal helper for the engine's own `.env`, not part of the surface
this app is scoped to. This module loads `apps/api/.env` (via
`python-dotenv`, gitignored, present locally for dev) and exposes:

- `DATABASE_URL` / `ANTHROPIC_API_KEY`: `None` when unset (e.g. in CI, which
  intentionally has neither -- see CLAUDE.md/issue #4's negative scope).
- `PROMPT_VERSION`: bumped whenever the persona system prompt's wording in
  `api.persona.prompt` changes, so the Postgres response cache
  (`api.persona.cache`) auto-busts instead of serving narration written
  under an old voice. It means prompt wording only, since issue #145: the
  cache key also hashes the exact fact block (the evidence JSON) a narration
  was generated from and carries `api.persona.grounding.GROUNDING_VERSION`,
  so a change to the block's shape or content, or to the grounding rules, is
  a miss on its own and needs no bump here. Before #145 the key covered
  neither, which is why v2, v3, v8 and v9 below were bumped for fact-block
  changes.
- `CONTESTED_YEARS`: the seasons whose champion is disputed (the human polls
  and the computed ratings disagreed), keyed by league (issue #151). It was
  a bare CFB year set, so NFL 2003/2017 verdicts were flagged contested too.
  Every `Sport` needs an entry, possibly empty, so a new league must state
  its own contested years instead of inheriting another league's
  (`tests/test_verdict_contested_by_sport.py` checks this). The first place
  this constant is defined anywhere in the project (checked -- no equivalent
  exists in `packages/cfb-engine`); scoped to `apps/api` only, per issue
  #4's brief. Narrations cached under an old list heal themselves: see
  `api.persona.service`.
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

from cfb_strength.contracts import Sport
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

# persona-v2 (issue #83): the prompt text is unchanged, but the fact block
# is not -- it now carries `ties`, and a tied game appears as `result: "T"`
# instead of being dropped. v1 narrations were written from tie-less facts.
# persona-v3 (issue #152): prompt unchanged; compare fact blocks now carry `method`.
# persona-v4 (issue #162): the prompt changed -- rule 1 now lets the narrator
# round a `rating` or `opponent_rating` (and nothing else), matching the
# grounding check.
# persona-v5 (issue #165): the prompt changed -- rule 1 now says a Keener
# rating may be quoted the way the site displays it (scaled and rounded, per
# `api.rating_display.RATING_DISPLAY`), matching the grounding check.
# persona-v6 (issue #180): the prompt changed -- rule 1 no longer describes how
# the site displays a Keener rating. Asked to compute that value, the narrator
# invented wrong ones and fell back, and #65 cached those fallbacks under v5.
# persona-v7 (issue #231): the prompt changed -- the persona's attitude is now
# "the numbers are the numbers": rule 2, both allegiance clauses and rule 4 no
# longer let a grounded narration argue against the ranking.
# persona-v8 (issue #122): prompt unchanged; the compare fact block's verdict
# put the home score first after "X beat Y", so every away-team head-to-head
# win read backwards ("Seattle Seahawks beat Denver Broncos head-to-head
# 8-43"). v7 narrations were written, and grounded, against those scores.
# persona-v9 (issue #130): prompt unchanged; the compare fact block's
# `common_opponents` now carry every meeting per side (`team_a_meetings` /
# `team_b_meetings`) and the engine's verdict prose lists them, so v8
# comparison narrations were grounded against facts that hid earlier meetings.
# Issue #145 (no bump): the cache key gained the fact block's sha256 and
# `GROUNDING_VERSION`, which missed every pre-#145 row on its own. From here
# on this moves for prompt wording only; see the module docstring.
# persona-v10 (issue #228): the prompt changed -- rule 5 no longer demands
# `team_score` first for every score (which made a loss read losing-score-first,
# "Florida got them 7-19"); a score is said winner-first, and a loss in a
# sentence that says it was lost ("lost 19-7 to Florida"). v9 narrations were
# written under the old order.
PROMPT_VERSION = "persona-v10"

CONTESTED_YEARS: dict[Sport, frozenset[int]] = {
    "cfb": frozenset({2003, 2017}),
    "nfl": frozenset(),
}

APP_TEST_MODE: bool = os.environ.get("APP_TEST_MODE") == "1"
