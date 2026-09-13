"""The committed regression fixtures are current, apart from their deliberate
season slicing (issue #110, epic #113).

`tests/fixtures/cfb_regression.sqlite3` and `nfl_regression.sqlite3` are
season slices of a real ingest, produced by
`tests/fixtures/build_regression_fixtures.py`. A slice can never pass
`cfb doctor` outright: it omits most cached seasons, stores no ratings (the
golden tests compute them), and carries one league. So this runs the doctor's
own check, `ingest.currency.check_currency`, on each committed fixture
against the committed `data/raw/` and allows exactly the findings that
`.claude/agents/validator.md` waives for a deliberate slice:

- `season_behind_cache`, for seasons the fixture omits. A season the
  fixture does carry must have both of its cached season types;
- `season_missing_ratings`, because the fixture stores no ratings. It must
  name exactly the fixture's seasons, for every method;
- `league_has_no_games`, for the league the fixture doesn't carry.

Anything else fails: `schema_not_current` (the fixture predates the schema,
which is also what trips the `StaleDatabaseWarning` gate in pyproject.toml),
any `raw_cache_*` (this test reads the committed cache, so that would mean
the test is misconfigured, not the fixture), `no_cfb_mascots` (a CFB fixture
built without the #77 alias enrichment) and `cache_past_max_year`.

`check_currency` opens the fixture read-only and never migrates it, so this
reads the committed file in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pytest

from cfb_strength.contracts import Method, Sport
from cfb_strength.ingest.currency import CurrencyReport, check_currency

ENGINE_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ENGINE_DIR / "tests" / "fixtures"
# The committed cache, named explicitly rather than via `config.RAW_DIR`,
# which `CFB_DATA_DIR` can point somewhere else.
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"

SPORTS: tuple[Sport, ...] = get_args(Sport)
METHODS: tuple[Method, ...] = get_args(Method)

WAIVABLE_FOR_A_SLICE = frozenset(
    {"season_behind_cache", "season_missing_ratings", "league_has_no_games"}
)


@dataclass(frozen=True)
class CommittedFixture:
    path: Path
    seasons: tuple[int, ...]


# Written out by hand, not read from the generator: this is the oracle the
# generator's output is checked against.
COMMITTED_FIXTURES: dict[Sport, CommittedFixture] = {
    "cfb": CommittedFixture(
        FIXTURES_DIR / "cfb_regression.sqlite3", (2001, 2003, 2004, 2005, 2013, 2017, 2019)
    ),
    "nfl": CommittedFixture(FIXTURES_DIR / "nfl_regression.sqlite3", (1999, 2004, 2013, 2022)),
}


def _report(sport: Sport) -> CurrencyReport:
    return check_currency(COMMITTED_FIXTURES[sport].path, COMMITTED_RAW_DIR)


def test_every_league_has_a_committed_regression_fixture() -> None:
    assert tuple(COMMITTED_FIXTURES) == SPORTS


@pytest.mark.parametrize("sport", SPORTS)
def test_committed_fixture_has_only_the_findings_a_season_slice_waives(sport: Sport) -> None:
    report = _report(sport)
    codes = [problem.code for problem in report.problems]

    assert "schema_not_current" not in codes, report.missing_schema
    assert not [code for code in codes if code.startswith("raw_cache_")], codes
    assert "no_cfb_mascots" not in codes
    assert "cache_past_max_year" not in codes
    assert set(codes) <= WAIVABLE_FOR_A_SLICE, [p.message for p in report.problems]


@pytest.mark.parametrize("sport", SPORTS)
def test_each_waived_finding_is_explained_by_the_slice(sport: Sport) -> None:
    """The waivable codes are only waivable for the reason the slice gives.
    A fixture missing one of its own seasons' season types, or holding a
    rating, or lacking its own league, fails here."""
    fixture = COMMITTED_FIXTURES[sport]
    report = _report(sport)

    for problem in report.problems:
        if problem.code == "league_has_no_games":
            assert problem.sport != sport, problem.message
        elif problem.code == "season_behind_cache" and problem.sport == sport:
            assert not set(problem.seasons) & set(fixture.seasons), problem.message
        elif problem.code == "season_missing_ratings":
            assert problem.sport == sport, problem.message
            assert problem.seasons == fixture.seasons, problem.message

    no_games = {p.sport for p in report.problems if p.code == "league_has_no_games"}
    assert no_games == set(SPORTS) - {sport}
    # One season_missing_ratings per method: the fixture stores no ratings.
    unrated = [p for p in report.problems if p.code == "season_missing_ratings"]
    assert len(unrated) == len(METHODS)


@pytest.mark.parametrize("sport", SPORTS)
def test_committed_fixture_holds_exactly_its_seasons_in_every_season_type(sport: Sport) -> None:
    fixture = COMMITTED_FIXTURES[sport]
    report = _report(sport)

    for league in report.leagues:
        if league.sport == sport:
            assert league.game_seasons == fixture.seasons
            for season_type, seasons in league.game_seasons_by_type.items():
                assert seasons == fixture.seasons, season_type
                # Each fixture season is a real cached season of that type.
                assert set(seasons) <= set(league.cached_seasons_by_type[season_type])
        else:
            assert league.game_seasons == ()
        assert all(rated == () for rated in league.rated_seasons.values()), league.sport


def test_cfb_fixture_carries_mascots_from_the_teams_cache() -> None:
    aliases = _report("cfb").cfb_aliases
    assert aliases.teams_cache_present
    assert aliases.teams > 0
    assert aliases.with_mascot > 0
