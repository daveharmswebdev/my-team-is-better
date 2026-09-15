"""The committed regression fixtures pass `cfb doctor`'s check apart from
their deliberate season slicing (issue #110, epic #113).

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
- `season_missing_ratings`, for seasons the fixture carries but deliberately
  stores no ratings for under that method. These fixtures store no ratings
  at all, so there is one finding per method, and each must name exactly the
  fixture's own seasons and nothing else;
- `season_missing_player_stats`, for seasons the fixture carries but
  deliberately stores no player stats for (issue #296). Only a league with a
  committed player-stats cache (NFL) can raise it, so there is exactly one
  such finding for that fixture and none for the other, and it must name
  exactly the fixture's own seasons, for the fixture's own sport;
- `league_has_no_games`, for the league the fixture doesn't carry.

What this covers, and what it doesn't: `check_currency` compares the schema
and which (season, season_type) batches are present. It never reads game
content or counts, so a fixture missing one game, holding a score the cache
has since changed, or carrying an edited mascot or `ingestion_log` row
passes here. `tests/test_regression_fixtures_regenerate_identically.py`
catches those, by comparing every row with a fresh regeneration.

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
from cfb_strength.ingest.currency import CurrencyReport, Problem, check_currency

ENGINE_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ENGINE_DIR / "tests" / "fixtures"
# The committed cache, named explicitly rather than via `config.RAW_DIR`,
# which `CFB_DATA_DIR` can point somewhere else.
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"

SPORTS: tuple[Sport, ...] = get_args(Sport)
METHODS: tuple[Method, ...] = get_args(Method)

WAIVABLE_FOR_A_SLICE = frozenset(
    {
        "season_behind_cache",
        "season_missing_ratings",
        "season_missing_player_stats",
        "league_has_no_games",
    }
)


@dataclass(frozen=True)
class CommittedFixture:
    path: Path
    seasons: tuple[int, ...]
    # Whether the league has a committed player-stats cache, so the slice's
    # deliberately empty player tables raise `season_missing_player_stats`.
    player_stats_cache: bool


# Written out by hand, not read from the generator: this is the oracle the
# generator's output is checked against.
COMMITTED_FIXTURES: dict[Sport, CommittedFixture] = {
    "cfb": CommittedFixture(
        FIXTURES_DIR / "cfb_regression.sqlite3",
        (2001, 2003, 2004, 2005, 2013, 2017, 2019),
        player_stats_cache=False,
    ),
    "nfl": CommittedFixture(
        FIXTURES_DIR / "nfl_regression.sqlite3",
        (1999, 2004, 2013, 2022),
        player_stats_cache=True,
    ),
}


def _report(sport: Sport) -> CurrencyReport:
    return check_currency(COMMITTED_FIXTURES[sport].path, COMMITTED_RAW_DIR)


def _player_stats_gap_is_the_slice(problem: Problem, sport: Sport) -> bool:
    """A `season_missing_player_stats` finding is explained by the slice only
    when the fixture's league has a player-stats cache and the finding names
    exactly that fixture's sport and its own seasons, nothing more or less."""
    fixture = COMMITTED_FIXTURES[sport]
    return (
        problem.code == "season_missing_player_stats"
        and fixture.player_stats_cache
        and problem.sport == sport
        and problem.seasons == fixture.seasons
    )


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
    rating, or lacking its own league, or missing player stats for a season
    it doesn't carry, fails here."""
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
        elif problem.code == "season_missing_player_stats":
            assert _player_stats_gap_is_the_slice(problem, sport), problem.message

    no_games = {p.sport for p in report.problems if p.code == "league_has_no_games"}
    assert no_games == set(SPORTS) - {sport}
    # One season_missing_ratings per method: the fixture stores no ratings.
    unrated = [p for p in report.problems if p.code == "season_missing_ratings"]
    assert len(unrated) == len(METHODS)
    # One season_missing_player_stats where the league has a player-stats
    # cache, none where it doesn't: the fixture stores no player stats.
    no_players = [p for p in report.problems if p.code == "season_missing_player_stats"]
    assert len(no_players) == (1 if fixture.player_stats_cache else 0)


def _player_stats_gap(sport: Sport | None, seasons: tuple[int, ...]) -> Problem:
    return Problem("season_missing_player_stats", sport, "synthetic", seasons)


def test_player_stats_waiver_accepts_only_the_fixtures_own_seasons_and_sport() -> None:
    nfl = COMMITTED_FIXTURES["nfl"].seasons
    cfb = COMMITTED_FIXTURES["cfb"].seasons

    assert _player_stats_gap_is_the_slice(_player_stats_gap("nfl", nfl), "nfl")

    # Seasons other than the fixture's own: a subset, a superset, others, none.
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("nfl", nfl[:-1]), "nfl")
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("nfl", (*nfl, 2023)), "nfl")
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("nfl", (2000, 2005)), "nfl")
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("nfl", ()), "nfl")
    # Another sport, even when it names the fixture's seasons.
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("cfb", nfl), "nfl")
    assert not _player_stats_gap_is_the_slice(_player_stats_gap(None, nfl), "nfl")
    # CFB has no player-stats cache: no occurrence on the cfb fixture is the slice's.
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("cfb", cfb), "cfb")
    assert not _player_stats_gap_is_the_slice(_player_stats_gap("nfl", nfl), "cfb")
    # Another code is never this waiver.
    assert not _player_stats_gap_is_the_slice(
        Problem("season_missing_ratings", "nfl", "synthetic", nfl), "nfl"
    )


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
        assert league.player_stat_seasons == (), league.sport


def test_cfb_fixture_carries_mascots_from_the_teams_cache() -> None:
    aliases = _report("cfb").cfb_aliases
    assert aliases.teams_cache_present
    assert aliases.teams > 0
    assert aliases.with_mascot > 0
