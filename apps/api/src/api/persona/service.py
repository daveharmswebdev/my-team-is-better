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
`_all_team_names` helper; issue #13 promoted it to `api.deps.
list_all_team_names` so `api.catalog`'s `/api/teams` route can share the
same query instead of forking it.
"""

from __future__ import annotations

import sqlite3

from api.config import CONTESTED_YEARS, PROMPT_VERSION
from api.deps import list_all_team_names
from api.models import ComparisonResultOut, NarrationOut, TeamCaseOut
from api.persona.cache import CachedNarration, NarrationCacheStore, cache_key
from api.persona.claude_client import Narrator
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text
from api.persona.narrate import narrate

# Issue #183: the Elo ledger is published to clients but kept out of both
# fact blocks, so the narrator's input stays byte-identical to before #183.
# Left in, every pre-game rating and per-game shift would reach the prompt
# and, through `find_ungrounded_tokens(text, fact_block_json, ...)`,
# grounding's accepted-number set -- quietly licensing the narrator to quote
# figures nobody decided it should narrate (#175's open question). Removing an
# entry here is that decision, and needs a PROMPT_VERSION bump with it.
TEAM_CASE_FACT_BLOCK_EXCLUDE: dict[str, bool] = {"elo_ledger": True}
COMPARISON_FACT_BLOCK_EXCLUDE: dict[str, dict[str, bool]] = {
    "team_a": {"elo_ledger": True},
    "team_b": {"elo_ledger": True},
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


def is_contested(year: int) -> bool:
    """§4.1's `contested` flag -- true for the years the human polls and
    the computed ratings disagreed (`api.config.CONTESTED_YEARS`).
    """
    return year in CONTESTED_YEARS


def narrate_team_case(
    conn: sqlite3.Connection,
    case: TeamCaseOut,
    *,
    user_team: str | None,
    question_type: str,
    method: str,
    sport: str = "cfb",
    cache: NarrationCacheStore,
    narrator: Narrator,
) -> NarrationOut:
    contested = is_contested(case.year)
    key = cache_key(
        question_type=question_type,
        year=case.year,
        teams=(case.team_name,),
        user_team=user_team,
        method=method,
        sport=sport,
        prompt_version=PROMPT_VERSION,
    )

    cached = cache.get(key)
    if cached is not None:
        return NarrationOut(text=cached.text, contested=cached.contested, cached=True)

    fact_block_json = team_case_fact_block_json(case)
    text = narrate(
        fact_block_json=fact_block_json,
        user_team=user_team,
        contested=contested,
        known_team_names=list_all_team_names(conn, sport),
        narrator=narrator,
        fallback_text=team_case_fallback_text(case),
    )

    cache.set(key, CachedNarration(text=text, contested=contested))
    return NarrationOut(text=text, contested=contested, cached=False)


def narrate_comparison(
    conn: sqlite3.Connection,
    comparison: ComparisonResultOut,
    *,
    user_team: str | None,
    method: str,
    sport: str = "cfb",
    cache: NarrationCacheStore,
    narrator: Narrator,
) -> NarrationOut:
    contested = is_contested(comparison.year)
    team_a_name = comparison.team_a.team_name
    team_b_name = comparison.team_b.team_name
    key = cache_key(
        question_type="compare",
        year=comparison.year,
        teams=(team_a_name, team_b_name),
        user_team=user_team,
        method=method,
        sport=sport,
        prompt_version=PROMPT_VERSION,
    )

    cached = cache.get(key)
    if cached is not None:
        return NarrationOut(text=cached.text, contested=cached.contested, cached=True)

    fact_block_json = comparison_fact_block_json(comparison)
    text = narrate(
        fact_block_json=fact_block_json,
        user_team=user_team,
        contested=contested,
        known_team_names=list_all_team_names(conn, sport),
        narrator=narrator,
        fallback_text=comparison_fallback_text(comparison),
    )

    cache.set(key, CachedNarration(text=text, contested=contested))
    return NarrationOut(text=text, contested=contested, cached=False)
