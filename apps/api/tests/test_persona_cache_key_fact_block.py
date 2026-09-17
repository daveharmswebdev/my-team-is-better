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
and the grounding rules' version, so a changed block or tightened rules miss
exactly the affected entries.

Since issue #291 the rules that decide what may be served are the typed-claim
validator's, so the version is `api.persona.claims.GROUNDING_VERSION`
(`claims-v1`), not the lexical checker's `grounding-v2`, which production
stopped calling in #291 and #292 deleted.

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
from fixtures.narrator_fake import FakeNarrator

from api.config import PROMPT_VERSION
from api.models import ComparisonResultOut, NarrationOut, TeamCaseOut
from api.persona import claims, service
from api.persona.cache import InMemoryNarrationCache, cache_key
from api.persona.claims import GROUNDING_VERSION
from api.persona.service import (
    comparison_fact_block_json,
    narrate_comparison,
    narrate_team_case,
    team_case_fact_block_json,
)
from api.repositories.teams import TeamRecord, list_team_records

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

# No numbers, no team names, no claims: accepted against any fact block, so a
# second narrator call can only mean a cache miss, never a claim retry.
NARRATION = "Solid case, no notes."


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def catalog(conn: sqlite3.Connection) -> list[TeamRecord]:
    # What the route reads once and passes in (issues #245, #291).
    return list_team_records(conn, "cfb")


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
    catalog: list[TeamRecord],
    cache: InMemoryNarrationCache,
    narrator: FakeNarrator,
) -> NarrationOut:
    return narrate_team_case(
        case,
        user_team=None,
        question_type="team_case",
        method="keener",
        sport="cfb",
        catalog=catalog,
        cache=cache,
        narrator=narrator,
    )


def _narrate_comparison(
    comparison: ComparisonResultOut,
    catalog: list[TeamRecord],
    cache: InMemoryNarrationCache,
    narrator: FakeNarrator,
) -> NarrationOut:
    return narrate_comparison(
        comparison,
        user_team=None,
        method="keener",
        sport="cfb",
        catalog=catalog,
        cache=cache,
        narrator=narrator,
    )


# ---------------------------------------------------------------------------
# (a) the same fact block is a hit; a block differing in one field is a miss
# ---------------------------------------------------------------------------


def test_team_case_identical_block_hits_and_changed_block_misses(
    conn: sqlite3.Connection, catalog: list[TeamRecord]
) -> None:
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator(always=NARRATION)
    case = _case(conn)

    first = _narrate_case(case, catalog, cache, narrator)
    assert first.cached is False
    assert len(narrator.calls) == 1

    # Byte-identical block (a fresh instance built the same way): a hit.
    again = _narrate_case(_case(conn), catalog, cache, narrator)
    assert again.cached is True
    assert len(narrator.calls) == 1

    # One field's content differs, everything in the old key is unchanged.
    changed = case.model_copy(update={"wins": case.wins + 1})
    assert team_case_fact_block_json(changed) != team_case_fact_block_json(case)
    miss = _narrate_case(changed, catalog, cache, narrator)
    assert miss.cached is False
    assert len(narrator.calls) == 2


def test_comparison_identical_block_hits_and_changed_block_misses(
    conn: sqlite3.Connection, catalog: list[TeamRecord]
) -> None:
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator(always=NARRATION)
    comparison = _comparison(conn)

    first = _narrate_comparison(comparison, catalog, cache, narrator)
    assert first.cached is False
    assert len(narrator.calls) == 1

    again = _narrate_comparison(_comparison(conn), catalog, cache, narrator)
    assert again.cached is True
    assert len(narrator.calls) == 1

    # The verdict's wording changed; teams, year, method and sport did not.
    reworded = comparison.model_copy(update={"verdict": comparison.verdict + " Barely."})
    assert comparison_fact_block_json(reworded) != comparison_fact_block_json(comparison)
    miss = _narrate_comparison(reworded, catalog, cache, narrator)
    assert miss.cached is False
    assert len(narrator.calls) == 2


def test_a_narration_cached_for_one_block_is_never_served_for_another(
    conn: sqlite3.Connection, catalog: list[TeamRecord]
) -> None:
    """The two blocks' entries coexist: after both have been narrated, each
    is a hit on its own block and neither is served for the other."""
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator(always=NARRATION)
    case = _case(conn)
    changed = case.model_copy(update={"wins": case.wins + 1})

    _narrate_case(case, catalog, cache, narrator)
    _narrate_case(changed, catalog, cache, narrator)
    assert len(narrator.calls) == 2

    assert _narrate_case(case, catalog, cache, narrator).cached is True
    assert _narrate_case(changed, catalog, cache, narrator).cached is True
    assert len(narrator.calls) == 2


# ---------------------------------------------------------------------------
# (b) the service's key is exactly `cache_key(...)` over the production block
# ---------------------------------------------------------------------------


def test_service_writes_under_the_key_built_from_the_production_fact_block(
    conn: sqlite3.Connection, catalog: list[TeamRecord]
) -> None:
    """Guards every test that looks a service-written entry up by key:
    the key is `cache_key` over the block the service's own function
    builds, with `PROMPT_VERSION` and the claims' `GROUNDING_VERSION`."""
    cache = InMemoryNarrationCache()
    case = _case(conn)
    comparison = _comparison(conn)

    _narrate_case(case, catalog, cache, FakeNarrator(always=NARRATION))
    _narrate_comparison(comparison, catalog, cache, FakeNarrator(always=NARRATION))

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
# (c) the grounding version the service keys on is the claims' (#291)
# ---------------------------------------------------------------------------


def test_the_service_keys_on_the_claims_grounding_version() -> None:
    keyed_on = vars(service)["GROUNDING_VERSION"]
    assert GROUNDING_VERSION == "claims-v1"
    assert keyed_on == claims.GROUNDING_VERSION
    # "grounding-v2" was the lexical checker's version, the string this key
    # carried before #291. #292 deleted that module, so the literal is quoted
    # here: the key must never silently fall back to it, which would make
    # every narration cached under the old rules a hit.
    assert keyed_on != "grounding-v2"


def test_a_new_grounding_version_misses_every_entry_checked_under_the_old_one(
    conn: sqlite3.Connection,
    catalog: list[TeamRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bumping the constant the service reads is enough: no PROMPT_VERSION
    move, no fact-block change, and the cached narration is a miss."""
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator(always=NARRATION)
    case = _case(conn)

    _narrate_case(case, catalog, cache, narrator)
    assert _narrate_case(case, catalog, cache, narrator).cached is True
    assert len(narrator.calls) == 1

    monkeypatch.setattr(service, "GROUNDING_VERSION", GROUNDING_VERSION + "-tightened")

    bumped = _narrate_case(case, catalog, cache, narrator)
    assert bumped.cached is False
    assert len(narrator.calls) == 2
