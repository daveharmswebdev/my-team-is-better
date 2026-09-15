"""issue #4's per-route orchestration: cache lookup, fact-block
construction from issue #3's own evidence models (never a second
hand-written representation), the "known team names" universe for the
grounding check, and writing the result back to the cache.

`api.verdict`'s routes call `narrate_team_case`/`narrate_comparison` after
building the same `TeamCaseOut`/`ComparisonResultOut` issue #3 already
returns -- this module never recomputes evidence itself.

The grounding check's "known team names" universe (every team in the db, not
just the ones in this particular fact block, so a mention of a real-but-
wrong team, e.g. "Alabama" in a USC case, is recognized as a team-name
mention and checked against the fact block rather than silently ignored as
an arbitrary capitalized word) used to live here as a private
`_all_team_names` helper; issue #13 promoted it to a shared
`list_all_team_names` so `api.catalog`'s `/api/teams` route can share the
same query instead of forking it, and issue #209 settled it in
`api.repositories.teams`, below this layer (it had sat in `api.deps`, which
imports this package, so importing it from there was an upward import).

**The templated fallback is never cached (issue #65).** When `narrate()`
degrades to the fallback (a Claude transport error, or two grounding
failures), the fallback is returned to the user with `cached=False` and
nothing is written, so the next identical request asks Claude again instead
of being served the fallback forever. Cache rows written before that fix
may still hold fallback text. The fallback is a pure template of the
evidence, so it is computed before the lookup, and a cached entry whose text
equals it is treated as a miss; a later successful narration overwrites the
row through the cache's upsert.

Accepted trade-off: a key whose fact block fails grounding persistently now
costs up to two Claude calls on every request, instead of being pinned to
the fallback after the first failure.

**A cache outage never fails the verdict (issue #206).** `_cached_narration`
treats a `psycopg.Error` from any store's `get` as a miss and from its `set`
as a skipped write, logging one warning each, so the verdict narrates
normally with `cached=False`. `PostgresNarrationCache` already degrades this
way on its own; this guard makes the same promise for every
`NarrationCacheStore`. Only database errors are caught -- a programming bug
in a store still surfaces.

**A cached row with the wrong `contested` flag is a miss (issue #151).**
`contested` is computed per request from `api.config.CONTESTED_YEARS`, which
is keyed by league. Before #151 it was a bare CFB year set, so NFL 2003/2017
rows were cached with `contested=True`, and their text was narrated under
that wrong flag. Both the flag and the text therefore have to be
regenerated: a hit whose `cached.contested` differs from the freshly
computed flag is treated like a legacy fallback row, narrated again, and
overwritten through the cache's upsert. A hit whose flag matches is served
unchanged. This was chosen over a PROMPT_VERSION bump, which would discard
every cached narration in both leagues to fix a handful of NFL rows, and it
heals any later change to the contested lists the same way without a global
bust. The cache key and `CachedNarration` are unchanged.
"""

from __future__ import annotations

import logging
import sqlite3

import psycopg
from pydantic.main import IncEx

from api.config import CONTESTED_YEARS, PROMPT_VERSION
from api.models import ComparisonResultOut, NarrationOut, Sport, TeamCaseOut
from api.persona.cache import CachedNarration, NarrationCacheStore, cache_key
from api.persona.claude_client import Narrator
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text
from api.persona.narrate import narrate
from api.repositories.teams import list_all_team_names

logger = logging.getLogger(__name__)

# Issue #183: the Elo ledger is published to clients but kept out of both
# fact blocks, so the narrator's input stays byte-identical to before #183.
# Left in, every pre-game rating and per-game shift would reach the prompt
# and, through `find_ungrounded_tokens(text, fact_block_json, ...)`,
# grounding's accepted-number set -- quietly licensing the narrator to quote
# figures nobody decided it should narrate (#175's open question). Removing an
# entry here is that decision, and needs a PROMPT_VERSION bump with it.
#
# Issue #218: `game_id` (`games.id`, a nine-digit CFBD number) is published on
# every per-game record (`OpponentResultOut`, `HeadToHeadMeetingOut`,
# `CommonOpponentMeetingOut`) so apps/web can key its game lists on it, and
# is kept out of both fact blocks for the same reason. With it excluded the
# block Claude sees is byte-identical to the pre-#218 block, so
# `PROMPT_VERSION` does not move and no cached narration is invalidated
# (`tests/test_persona_fact_block_game_id.py` pins the byte equality; the
# cache key does not cover the fact block, #145, which is why that equality
# has to hold rather than be re-keyed). `"__all__"` applies the exclusion to
# every item of a list; a `None` `worst_loss` is simply skipped.
#
# `IncEx` is pydantic's own type for `model_dump_json(exclude=...)`: nested
# mappings of field name -> `True` (drop the field) or a further mapping.
_GAME_ID: dict[str, bool] = {"game_id": True}
_EACH_GAME_ID: dict[str, IncEx | bool] = {"__all__": _GAME_ID}
# `ComparisonTeamSummaryOut` is `TeamCaseOut` without `games` (#183, #218).
_TEAM_SUMMARY_EXCLUDE: dict[str, IncEx | bool] = {
    "elo_ledger": True,
    "quality_wins": _EACH_GAME_ID,
    "worst_loss": _GAME_ID,
}
TEAM_CASE_FACT_BLOCK_EXCLUDE: dict[str, IncEx | bool] = {
    **_TEAM_SUMMARY_EXCLUDE,
    "games": _EACH_GAME_ID,
}
COMPARISON_FACT_BLOCK_EXCLUDE: dict[str, IncEx | bool] = {
    "team_a": _TEAM_SUMMARY_EXCLUDE,
    "team_b": _TEAM_SUMMARY_EXCLUDE,
    "head_to_head": {"meetings": _EACH_GAME_ID},
    "common_opponents": {
        "__all__": {
            "team_a_meetings": _EACH_GAME_ID,
            "team_b_meetings": _EACH_GAME_ID,
        }
    },
}


def team_case_fact_block_json(case: TeamCaseOut) -> str:
    """The FACT BLOCK JSON the narrator and the grounding check see for a
    champion or team-case verdict. The one definition: tests that exercise
    grounding on "the real fact block" build it here too, so they cannot
    drift into a more permissive block than production hands Claude."""
    return case.model_dump_json(exclude=TEAM_CASE_FACT_BLOCK_EXCLUDE)


def comparison_fact_block_json(comparison: ComparisonResultOut) -> str:
    """The FACT BLOCK JSON for a compare verdict; see
    `team_case_fact_block_json`."""
    return comparison.model_dump_json(exclude=COMPARISON_FACT_BLOCK_EXCLUDE)


def is_contested(sport: Sport, year: int) -> bool:
    """§4.1's `contested` flag -- true for the seasons in `sport` where the
    human polls and the computed ratings disagreed
    (`api.config.CONTESTED_YEARS`, keyed by league since issue #151).
    """
    return year in CONTESTED_YEARS[sport]


def narrate_team_case(
    conn: sqlite3.Connection,
    case: TeamCaseOut,
    *,
    user_team: str | None,
    question_type: str,
    method: str,
    sport: Sport = "cfb",
    cache: NarrationCacheStore,
    narrator: Narrator,
) -> NarrationOut:
    key = cache_key(
        question_type=question_type,
        year=case.year,
        teams=(case.team_name,),
        user_team=user_team,
        method=method,
        sport=sport,
        prompt_version=PROMPT_VERSION,
    )
    return _cached_narration(
        conn,
        year=case.year,
        fact_block_json=team_case_fact_block_json(case),
        key=key,
        fallback_text=team_case_fallback_text(case),
        user_team=user_team,
        sport=sport,
        cache=cache,
        narrator=narrator,
    )


def narrate_comparison(
    conn: sqlite3.Connection,
    comparison: ComparisonResultOut,
    *,
    user_team: str | None,
    method: str,
    sport: Sport = "cfb",
    cache: NarrationCacheStore,
    narrator: Narrator,
) -> NarrationOut:
    key = cache_key(
        question_type="compare",
        year=comparison.year,
        teams=(comparison.team_a.team_name, comparison.team_b.team_name),
        user_team=user_team,
        method=method,
        sport=sport,
        prompt_version=PROMPT_VERSION,
    )
    return _cached_narration(
        conn,
        year=comparison.year,
        fact_block_json=comparison_fact_block_json(comparison),
        key=key,
        fallback_text=comparison_fallback_text(comparison),
        user_team=user_team,
        sport=sport,
        cache=cache,
        narrator=narrator,
    )


def _cached_narration(
    conn: sqlite3.Connection,
    *,
    year: int,
    fact_block_json: str,
    key: str,
    fallback_text: str,
    user_team: str | None,
    sport: Sport,
    cache: NarrationCacheStore,
    narrator: Narrator,
) -> NarrationOut:
    """Serve a real cached narration, or narrate and cache the result unless
    it is the fallback. Two kinds of cached entry count as a miss (see the
    module docstring): one whose text is this request's `fallback_text` (a
    legacy fallback row, issue #65), and one whose `contested` flag differs
    from the one computed now (narrated under a stale contested list, issue
    #151).

    `fact_block_json` comes from `team_case_fact_block_json` /
    `comparison_fact_block_json`, never a bare `model_dump_json()`, so the
    #183 ledger exclusion cannot be bypassed here.
    """
    contested = is_contested(sport, year)

    try:
        cached = cache.get(key)
    except psycopg.Error as exc:
        logger.warning("Narration cache read failed, narrating uncached: %s", exc)
        cached = None
    if cached is not None and cached.text != fallback_text and cached.contested == contested:
        return NarrationOut(text=cached.text, contested=cached.contested, cached=True)

    result = narrate(
        fact_block_json=fact_block_json,
        user_team=user_team,
        contested=contested,
        known_team_names=list_all_team_names(conn, sport),
        narrator=narrator,
        fallback_text=fallback_text,
    )

    if not result.is_fallback:
        try:
            cache.set(key, CachedNarration(text=result.text, contested=contested))
        except psycopg.Error as exc:
            logger.warning("Narration cache write failed, narration not cached: %s", exc)
    return NarrationOut(text=result.text, contested=contested, cached=False)
