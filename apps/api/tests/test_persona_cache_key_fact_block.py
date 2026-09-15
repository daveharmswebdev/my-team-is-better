"""Failing-first tests for issue #145: the narration cache key covers the
fact block a narration was generated from and the version of the grounding
rules it was checked under.

Before #145 the key was `hash(question_type, year, team(s), user_team,
method, sport, PROMPT_VERSION)`: nothing in it said which facts the cached
text was written from, so every change to the fact block (a new field, a
reworded verdict, a corrected score) had to be paid for with a
`PROMPT_VERSION` bump that discarded every cached narration in both
leagues, and a change to what the grounding check accepts could not
invalidate anything at all. Now the key also carries a sha256 of the exact
block `team_case_fact_block_json` / `comparison_fact_block_json` produce
and `api.persona.grounding.GROUNDING_VERSION`, so a changed block or
tightened rules miss exactly the affected entries.

Both service entry points are driven end to end with `InMemoryNarrationCache`
and a counting fake narrator against real evidence from the committed
fixture: no Postgres, no Claude. A byte-identical case is a hit (the
narrator is not called again); a case whose block differs in one field's
content is a miss (it is).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case

from api.config import PROMPT_VERSION
from api.models import ComparisonResultOut, NarrationOut, TeamCaseOut
from api.persona import service
from api.persona.cache import InMemoryNarrationCache, cache_key
from api.persona.grounding import GROUNDING_VERSION
from api.persona.service import (
    comparison_fact_block_json,
    narrate_comparison,
    narrate_team_case,
    team_case_fact_block_json,
)
from api.repositories.teams import list_all_team_names

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

# No numbers and no team names: grounded against any fact block, so a
# second narrator call can only mean a cache miss, never a grounding retry.
NARRATION = "Solid case, no notes."


class _CountingNarrator:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return NARRATION


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def known_team_names(conn: sqlite3.Connection) -> list[str]:
    # What the route derives from the catalog it reads (issue #245).
    return list_all_team_names(conn, "cfb")


def _case(conn: sqlite3.Connection) -> TeamCaseOut:
    return TeamCaseOut.from_dataclass(
        build_team_case(conn, 2005, "Texas", method="keener", sport="cfb")
    )


def _comparison(conn: sqlite3.Connection) -> ComparisonResultOut:
    return ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2005, "Texas", "USC", method="keener", sport="cfb")
    )


def _narrate_case(
    case: TeamCaseOut,
    known_team_names: list[str],
    cache: InMemoryNarrationCache,
    narrator: _CountingNarrator,
) -> NarrationOut:
    return narrate_team_case(
        case,
        user_team=None,
        question_type="team_case",
        method="keener",
        sport="cfb",
        known_team_names=known_team_names,
        cache=cache,
        narrator=narrator,
    )


def _narrate_comparison(
    comparison: ComparisonResultOut,
    known_team_names: list[str],
    cache: InMemoryNarrationCache,
    narrator: _CountingNarrator,
) -> NarrationOut:
    return narrate_comparison(
        comparison,
        user_team=None,
        method="keener",
        sport="cfb",
        known_team_names=known_team_names,
        cache=cache,
        narrator=narrator,
    )


# ---------------------------------------------------------------------------
# (a) the same fact block is a hit; a block differing in one field is a miss
# ---------------------------------------------------------------------------


def test_team_case_identical_block_hits_and_changed_block_misses(
    conn: sqlite3.Connection, known_team_names: list[str]
) -> None:
    cache = InMemoryNarrationCache()
    narrator = _CountingNarrator()
    case = _case(conn)

    first = _narrate_case(case, known_team_names, cache, narrator)
    assert first.cached is False
    assert narrator.calls == 1

    # Byte-identical block (a fresh instance built the same way): a hit.
    again = _narrate_case(_case(conn), known_team_names, cache, narrator)
    assert again.cached is True
    assert narrator.calls == 1

    # One field's content differs, everything in the old key is unchanged.
    changed = case.model_copy(update={"wins": case.wins + 1})
    assert team_case_fact_block_json(changed) != team_case_fact_block_json(case)
    miss = _narrate_case(changed, known_team_names, cache, narrator)
    assert miss.cached is False
    assert narrator.calls == 2


def test_comparison_identical_block_hits_and_changed_block_misses(
    conn: sqlite3.Connection, known_team_names: list[str]
) -> None:
    cache = InMemoryNarrationCache()
    narrator = _CountingNarrator()
    comparison = _comparison(conn)

    first = _narrate_comparison(comparison, known_team_names, cache, narrator)
    assert first.cached is False
    assert narrator.calls == 1

    again = _narrate_comparison(_comparison(conn), known_team_names, cache, narrator)
    assert again.cached is True
    assert narrator.calls == 1

    # The verdict's wording changed; teams, year, method and sport did not.
    reworded = comparison.model_copy(update={"verdict": comparison.verdict + " Barely."})
    assert comparison_fact_block_json(reworded) != comparison_fact_block_json(comparison)
    miss = _narrate_comparison(reworded, known_team_names, cache, narrator)
    assert miss.cached is False
    assert narrator.calls == 2


def test_a_narration_cached_for_one_block_is_never_served_for_another(
    conn: sqlite3.Connection, known_team_names: list[str]
) -> None:
    """The two blocks' entries coexist: after both have been narrated, each
    is a hit on its own block and neither is served for the other."""
    cache = InMemoryNarrationCache()
    narrator = _CountingNarrator()
    case = _case(conn)
    changed = case.model_copy(update={"wins": case.wins + 1})

    _narrate_case(case, known_team_names, cache, narrator)
    _narrate_case(changed, known_team_names, cache, narrator)
    assert narrator.calls == 2

    assert _narrate_case(case, known_team_names, cache, narrator).cached is True
    assert _narrate_case(changed, known_team_names, cache, narrator).cached is True
    assert narrator.calls == 2


# ---------------------------------------------------------------------------
# (b) the service's key is exactly `cache_key(...)` over the production block
# ---------------------------------------------------------------------------


def test_service_writes_under_the_key_built_from_the_production_fact_block(
    conn: sqlite3.Connection, known_team_names: list[str]
) -> None:
    """Guards every test that looks a service-written entry up by key:
    the key is `cache_key` over the block the service's own function
    builds, with `PROMPT_VERSION` and `GROUNDING_VERSION`."""
    cache = InMemoryNarrationCache()
    case = _case(conn)
    comparison = _comparison(conn)

    _narrate_case(case, known_team_names, cache, _CountingNarrator())
    _narrate_comparison(comparison, known_team_names, cache, _CountingNarrator())

    case_key = cache_key(
        question_type="team_case",
        year=2005,
        teams=("Texas",),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=team_case_fact_block_json(case),
        grounding_version=GROUNDING_VERSION,
    )
    comparison_key = cache_key(
        question_type="compare",
        year=2005,
        teams=("Texas", "USC"),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=comparison_fact_block_json(comparison),
        grounding_version=GROUNDING_VERSION,
    )
    assert cache.get(case_key) is not None
    assert cache.get(comparison_key) is not None


# ---------------------------------------------------------------------------
# (c) GROUNDING_VERSION exists and the service keys on it
# ---------------------------------------------------------------------------


def test_grounding_version_is_a_non_empty_string() -> None:
    assert isinstance(GROUNDING_VERSION, str)
    assert GROUNDING_VERSION


def test_a_new_grounding_version_misses_every_entry_checked_under_the_old_one(
    conn: sqlite3.Connection,
    known_team_names: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bumping the constant the service reads is enough: no PROMPT_VERSION
    move, no fact-block change, and the cached narration is a miss."""
    cache = InMemoryNarrationCache()
    narrator = _CountingNarrator()
    case = _case(conn)

    _narrate_case(case, known_team_names, cache, narrator)
    assert _narrate_case(case, known_team_names, cache, narrator).cached is True
    assert narrator.calls == 1

    monkeypatch.setattr(service, "GROUNDING_VERSION", GROUNDING_VERSION + "-tightened")

    bumped = _narrate_case(case, known_team_names, cache, narrator)
    assert bumped.cached is False
    assert narrator.calls == 2
