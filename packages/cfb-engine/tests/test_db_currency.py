"""Coverage for `cfb doctor` (issue #97, epic #113): a read-only check that a
sqlite db's *data* is current, not just its schema.

The failure this guards against is real, not hypothetical: a machine-local
`data/cfb.sqlite3` built before #51 is a complete-looking 790-team CFB ingest
with no NFL rows and no mascots, and `ensure_schema` happily migrates the
missing columns into it -- producing a current-*schema* db whose data is
still stale. Nothing distinguished it from a fresh build.

Every defect test below starts from a tiny db that is current in every
respect (`_build_current_db`: a regular AND a postseason game plus every
method's ratings for each season of each league), paired with a tiny fake raw
cache holding exactly those (season, season_type) pairs (`_build_raw_dir`).
It applies one defect and asserts the doctor reports exactly the problems
that defect implies -- so disabling any single check turns at least one test
red rather than hiding behind another check that also fires.

Ingest windows come from the ingest modules themselves, so the boundary tests
follow a MIN_YEAR/MAX_YEAR bump instead of pinning today's numbers.

Platform independence (CI runs ubuntu-latest, development happens on macOS):
nothing here depends on how a given SQLite build treats a read-only open of a
WAL db. The WAL tests assert only outcomes the doctor controls -- it opens a
sidecar-less WAL db `immutable`, never a live one -- and the error-message
tests force the failure with a monkeypatched `currency.get_conn` rather than
hoping the platform produces one.

Hermetic: every db and raw dir lives in `tmp_path`; the real 43MB cache and
the real local db are never read.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import get_args

import pytest

from cfb_strength import cli
from cfb_strength.config import SEASON_TYPES
from cfb_strength.contracts import Method, Sport
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest import currency
from cfb_strength.ingest import ingest_season as cfbd_ingest
from cfb_strength.ingest.nflverse import ingest_season as nflverse_ingest
from cfb_strength.ratings.compute_ratings import compute_and_store

SPORTS: tuple[str, ...] = get_args(Sport)
METHODS: tuple[str, ...] = get_args(Method)
# The methods whose ratings come with an Elo ledger (#183). Written out here
# rather than imported from `currency` on purpose, so the tests fail if the
# doctor's own list stops matching the contract's note (`TeamCase.elo_ledger`).
LEDGER_METHODS: tuple[str, ...] = ("elo",)
LEDGER_TABLES: tuple[str, ...] = ("elo_ledger_configs", "elo_ledger_steps")

# Seasons each league's fixture db holds games (both season types) and every
# method's ratings for, and that its fake raw cache holds. Deliberately in
# the middle of both ingest windows, so boundary seasons can be added.
SEASONS: dict[str, tuple[int, ...]] = {"cfb": (2001, 2002), "nfl": (2001, 2002)}
EXTRA_SEASON = 2003

WINDOWS: dict[str, tuple[int, int]] = {
    "cfb": (cfbd_ingest.MIN_YEAR, cfbd_ingest.MAX_YEAR),
    "nfl": (nflverse_ingest.MIN_YEAR, nflverse_ingest.MAX_YEAR),
}

Pair = tuple[int, str]

OK_LINE = "OK: the db's data is current."
GENERIC_UNREADABLE = "could not be read as a sqlite database"


def _pairs(*seasons: int) -> list[Pair]:
    return [(season, season_type) for season in seasons for season_type in SEASON_TYPES]


def _team_ids(sport: str) -> tuple[int, int]:
    base = SPORTS.index(sport) * 1_000_000_000
    return base + 1, base + 2


def _build_current_db(path: Path) -> Path:
    conn = get_conn(path)
    ensure_schema(conn)
    for sport, seasons in SEASONS.items():
        home, away = _team_ids(sport)
        for team_id, school in ((home, f"{sport} Home"), (away, f"{sport} Away")):
            # One mascot per league, NFL included: the mascot check must be
            # scoped to CFB, and an NFL mascot is what proves it is.
            mascot = "Mascots" if team_id == home else None
            conn.execute(
                "INSERT INTO teams (id, school, classification, sport, mascot) "
                "VALUES (?, ?, ?, ?, ?)",
                (team_id, school, "fbs" if sport == "cfb" else None, sport, mascot),
            )
        for season in seasons:
            for offset, season_type in enumerate(SEASON_TYPES):
                conn.execute(
                    """
                    INSERT INTO games (
                        id, season, week, season_type, neutral_site, completed,
                        home_team_id, away_team_id, home_team, away_team,
                        home_points, away_points, raw_json, sport
                    ) VALUES (?, ?, 1, ?, 0, 1, ?, ?, ?, ?, 21, 14, '{}', ?)
                    """,
                    (
                        home + season * 10 + offset,
                        season,
                        season_type,
                        home,
                        away,
                        f"{sport} Home",
                        f"{sport} Away",
                        sport,
                    ),
                )
            for method in METHODS:
                for rank, team_id in enumerate((home, away), start=1):
                    conn.execute(
                        "INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, "
                        "ties, computed_at, sport) VALUES (?, ?, ?, ?, ?, ?, ?, 0, "
                        "'2026-01-01T00:00:00+00:00', ?)",
                        (season, method, team_id, 1.0 / rank, rank, 2 - rank, rank - 1, sport),
                    )
            # A ledger-writing method's ratings come with their ledger: the
            # config the walk ran with, and one step per rated team (#183).
            for method in LEDGER_METHODS:
                conn.execute(
                    "INSERT INTO elo_ledger_configs (year, method, sport, starting_rating, k, "
                    "hfa, scale, mov_scale, mov_autocorr, mov_denom_floor_fraction, "
                    "computed_at) "
                    "VALUES (?, ?, ?, 1500.0, 20.0, 55.0, 400.0, 2.2, 0.001, 0.5, "
                    "'2026-01-01T00:00:00+00:00')",
                    (season, method, sport),
                )
                for team_id, opponent_id, venue, result in (
                    (home, away, "home", "W"),
                    (away, home, "away", "L"),
                ):
                    conn.execute(
                        """
                        INSERT INTO elo_ledger_steps (
                            year, method, sport, team_id, game_number, week, season_type,
                            opponent_team_id, venue, team_points, opponent_points, result,
                            rating_before, opponent_rating_before, home_field_adjustment,
                            rating_gap, win_expectancy, mov_multiplier, shift, rating_after,
                            computed_at
                        ) VALUES (?, ?, ?, ?, 1, 1, 'regular', ?, ?, 21, 14, ?, 1500.0, 1500.0,
                                  55.0, 55.0, 0.5, 1.0, 10.0, 1510.0, '2026-01-01T00:00:00+00:00')
                        """,
                        (season, method, sport, team_id, opponent_id, venue, result),
                    )
    conn.commit()
    conn.close()
    return path


_ONE_GAME_JSON = '[{"id": 1}]'
_EARLY_BOWL_DATE = "2026-12-20T17:00:00.000Z"
_TITLE_GAME_DATE = "2027-01-19T00:30:00.000Z"
_FINISHED_POSTSEASON_JSON = (
    f'[{{"id": 1, "startDate": "{_EARLY_BOWL_DATE}", "completed": true}},'
    f' {{"id": 2, "startDate": "{_TITLE_GAME_DATE}", "completed": true}}]'
)


def _write_cfb_cache(raw_dir: Path, pairs: list[Pair]) -> None:
    for season, season_type in pairs:
        (raw_dir / f"{season}_{season_type}.json").write_text(_ONE_GAME_JSON)
    # Below the CFB ingest window: `cfb ingest` would never write it, so a db
    # lacking it is not behind the cache.
    (raw_dir / f"{WINDOWS['cfb'][0] - 1}_regular.json").write_text(_ONE_GAME_JSON)
    (raw_dir / "teams.json").write_text("[]")


# Every playoff round nflverse publishes (see ingest/nflverse/normalize.py's
# docstring). Written out here rather than imported from ingest on purpose:
# the tests must fail if ingest's own sets ever stop matching the real data.
NFL_POSTSEASON_GAME_TYPES = ("WC", "DIV", "CON", "SB")
_NFL_HEADER = [
    "game_id",
    "season",
    "game_type",
    "week",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
]


def _nfl_row(
    season: int, game_type: str, *, scores: tuple[str, str] = ("17", "24")
) -> list[object]:
    """`scores` is (away_score, home_score) exactly as the csv cells hold them."""
    return [f"{season}_{game_type}_BUF_NE", season, game_type, 1, "BUF", "NE", *scores]


def _write_nfl_rows(raw_dir: Path, rows: list[list[object]]) -> None:
    nfl = raw_dir / "nfl"
    nfl.mkdir(parents=True, exist_ok=True)
    with (nfl / "games.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_NFL_HEADER)
        writer.writerows(rows)


def _append_nfl_rows(raw_dir: Path, rows: list[list[object]]) -> None:
    with (raw_dir / "nfl" / "games.csv").open("a", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_nfl_cache(raw_dir: Path, pairs: list[Pair]) -> None:
    rows: list[list[object]] = []
    for season, season_type in pairs:
        game_types = ("REG",) if season_type == "regular" else NFL_POSTSEASON_GAME_TYPES
        rows += [_nfl_row(season, game_type) for game_type in game_types]
    _write_nfl_rows(raw_dir, rows)


CACHE_WRITERS = {"cfb": _write_cfb_cache, "nfl": _write_nfl_cache}


def _build_raw_dir(
    tmp_path: Path,
    *,
    extra: dict[str, list[Pair]] | None = None,
    name: str = "raw",
) -> Path:
    raw_dir = tmp_path / name
    raw_dir.mkdir()
    for sport, seasons in SEASONS.items():
        CACHE_WRITERS[sport](raw_dir, _pairs(*seasons) + (extra or {}).get(sport, []))
    return raw_dir


def _problems(report: currency.CurrencyReport) -> set[tuple[str, str | None]]:
    return {(p.code, p.sport) for p in report.problems}


def _mutate(db: Path, *statements: str) -> None:
    conn = sqlite3.connect(db)
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def _drop_season(db: Path, sport: str, season: int) -> None:
    _mutate(
        db,
        f"DELETE FROM ratings WHERE sport = '{sport}' AND year = {season}",
        f"DELETE FROM games WHERE sport = '{sport}' AND season = {season}",
    )


def _drop_ledger(
    db: Path, sport: str, seasons: tuple[int, ...], tables: tuple[str, ...] = LEDGER_TABLES
) -> None:
    years = ", ".join(str(season) for season in seasons)
    _mutate(
        db,
        *(
            f"DELETE FROM {table} WHERE sport = '{sport}' AND method = 'elo' AND year IN ({years})"
            for table in tables
        ),
    )


def _run(db: Path, raw_dir: Path) -> int:
    return currency.main(["--db-path", str(db), "--raw-dir", str(raw_dir)])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _siblings(path: Path) -> list[str]:
    return sorted(p.name for p in path.parent.iterdir())


@pytest.fixture
def current_db(tmp_path: Path) -> Path:
    return _build_current_db(tmp_path / "current.sqlite3")


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    return _build_raw_dir(tmp_path)


def test_fixtures_cover_every_league_in_the_alias() -> None:
    # A league added to `Sport` must get a fixture db, a fake cache and an
    # ingest window here, or the tests below would stop covering it.
    assert set(SEASONS) == set(SPORTS)
    assert set(CACHE_WRITERS) == set(SPORTS)
    assert set(WINDOWS) == set(SPORTS)


def test_every_league_has_a_raw_cache_reader() -> None:
    # A league without one would never be checked against its cache (c).
    assert set(currency.CACHED_SEASON_READERS) == set(SPORTS)


# ---------------------------------------------------------------------------
# The healthy case
# ---------------------------------------------------------------------------


def test_fully_current_db_reports_no_problems_and_exits_zero(
    current_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = currency.check_currency(current_db, raw_dir)
    assert report.problems == ()
    assert report.notes == ()
    assert report.is_current

    assert _run(current_db, raw_dir) == 0
    out = capsys.readouterr().out
    assert OK_LINE in out
    assert "NOT CURRENT" not in out
    for sport in SPORTS:
        assert sport in out
    for method in METHODS:
        assert method in out
    for season_type in SEASON_TYPES:
        assert season_type in out
    assert "mascot" in out


def test_expected_leagues_methods_and_season_types_come_from_the_contract(
    current_db: Path, raw_dir: Path
) -> None:
    report = currency.check_currency(current_db, raw_dir)

    assert tuple(league.sport for league in report.leagues) == SPORTS
    for league in report.leagues:
        seasons = SEASONS[league.sport]
        assert league.game_seasons == seasons
        assert dict(league.game_seasons_by_type) == {t: seasons for t in SEASON_TYPES}
        assert dict(league.cached_seasons_by_type) == {t: seasons for t in SEASON_TYPES}
        assert tuple(league.rated_seasons) == METHODS
        for method in METHODS:
            assert league.rated_seasons[method] == seasons


def test_cli_dispatches_doctor(current_db: Path, raw_dir: Path) -> None:
    assert "doctor" in cli.USAGE
    assert cli.main(["doctor", "--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 0


# ---------------------------------------------------------------------------
# A --raw-dir that doesn't look like the committed cache must never be green
# ---------------------------------------------------------------------------


def test_a_missing_raw_dir_is_a_problem_not_a_silent_skip(tmp_path: Path, current_db: Path) -> None:
    report = currency.check_currency(current_db, tmp_path / "no-such-raw-dir")

    assert _problems(report) == {("raw_cache_missing", None)}


@pytest.mark.parametrize("which", ["empty_dir", "parent_of_raw_dir"])
def test_an_existing_dir_that_is_not_the_raw_cache_is_not_green(
    tmp_path: Path, current_db: Path, which: str, capsys: pytest.CaptureFixture[str]
) -> None:
    raw_dir = _build_raw_dir(tmp_path)
    for sport in SPORTS:
        _drop_season(current_db, sport, SEASONS[sport][-1])
    wrong = tmp_path / "empty" if which == "empty_dir" else raw_dir.parent
    wrong.mkdir(exist_ok=True)

    report = currency.check_currency(current_db, wrong)

    assert _problems(report) == {("raw_cache_unrecognized", sport) for sport in SPORTS}
    assert _run(current_db, wrong) == 1
    out = capsys.readouterr().out
    assert OK_LINE not in out
    assert "NOT CURRENT" in out


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param("id,year\n1,2001\n2,2002\n", id="no_season_column"),
        pytest.param("game_id,season\n2001_REG,2001\n", id="no_game_type_column"),
        pytest.param("game_id,season,game_type\n2001_PRE,2001,PRE\n", id="only_skipped_game_types"),
        pytest.param("game_id,season,game_type\nx,not-a-year,REG\n", id="no_parseable_season"),
        pytest.param("game_id,season,game_type\n", id="no_rows"),
    ],
)
def test_an_unreadable_nfl_games_csv_is_not_green(
    current_db: Path, raw_dir: Path, rewrite: str
) -> None:
    _drop_season(current_db, "nfl", SEASONS["nfl"][-1])
    (raw_dir / "nfl" / "games.csv").write_text(rewrite)

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("raw_cache_unrecognized", "nfl")}
    assert _run(current_db, raw_dir) == 1


def test_a_row_with_an_unparseable_season_is_skipped_not_fatal(
    current_db: Path, raw_dir: Path
) -> None:
    # ingest matches `season` as the string of a requested year, so it never
    # ingests these rows; every valid row around them must still count.
    _append_nfl_rows(
        raw_dir,
        [
            ["x_NA_BUF_NE", "NA", "REG", 1, "BUF", "NE", "17", "24"],
            ["x_blank_BUF_NE", "", "SB", 1, "BUF", "NE", "17", "24"],
        ],
    )

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    assert report.notes == ()


def test_a_missing_nfl_games_csv_is_not_green(current_db: Path, raw_dir: Path) -> None:
    (raw_dir / "nfl" / "games.csv").unlink()

    assert _problems(currency.check_currency(current_db, raw_dir)) == {
        ("raw_cache_unrecognized", "nfl")
    }


def test_a_cfb_cache_without_season_files_is_not_green(current_db: Path, raw_dir: Path) -> None:
    _drop_season(current_db, "cfb", SEASONS["cfb"][-1])
    for path in raw_dir.glob("*_*.json"):
        path.unlink()

    assert _problems(currency.check_currency(current_db, raw_dir)) == {
        ("raw_cache_unrecognized", "cfb")
    }


def test_a_cfb_cache_without_teams_json_is_not_green(current_db: Path, raw_dir: Path) -> None:
    # Also the only way the mascot check (e) can be skipped, so the missing
    # mascots below must surface as the unrecognized cache, not as silence.
    _mutate(current_db, "UPDATE teams SET mascot = NULL WHERE sport = 'cfb'")
    (raw_dir / "teams.json").unlink()

    assert _problems(currency.check_currency(current_db, raw_dir)) == {
        ("raw_cache_unrecognized", "cfb")
    }


# ---------------------------------------------------------------------------
# NFL rows are read exactly the way nflverse ingest filters them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("game_type", NFL_POSTSEASON_GAME_TYPES)
def test_every_nfl_playoff_round_counts_as_postseason(
    current_db: Path, raw_dir: Path, game_type: str
) -> None:
    first, last = SEASONS["nfl"]
    # `last`'s postseason is represented in the cache by this one round only,
    # and the db lacks it: flagged only if this round counts as postseason.
    _write_nfl_rows(
        raw_dir,
        [_nfl_row(season, "REG") for season in (first, last)]
        + [_nfl_row(first, t) for t in NFL_POSTSEASON_GAME_TYPES]
        + [_nfl_row(last, game_type)],
    )
    _mutate(
        current_db,
        f"DELETE FROM games WHERE sport = 'nfl' AND season = {last} AND season_type = 'postseason'",
    )

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_behind_cache", "nfl")}
    assert report.problems[0].pairs == ((last, "postseason"),)


@pytest.mark.parametrize("where", ["in_window", "past_max_year"])
def test_game_types_nflverse_ingest_skips_are_skipped_not_fatal(
    current_db: Path, raw_dir: Path, where: str
) -> None:
    # nflverse ingest keeps only REG/WC/DIV/CON/SB rows and silently drops
    # anything else (a preseason row, say). One such row must neither make
    # the whole cache unrecognized nor invent a season the db should have.
    season = EXTRA_SEASON if where == "in_window" else WINDOWS["nfl"][1] + 1
    _append_nfl_rows(raw_dir, [_nfl_row(season, "PRE")])

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    if where == "past_max_year":
        # The window is applied before the game-type filter: a season past
        # MAX_YEAR is noted whatever its rows are.
        assert len(report.notes) == 1 and str(season) in report.notes[0]
    else:
        assert report.notes == ()


# ---------------------------------------------------------------------------
# (a) schema not current -- reported, never fixed
# ---------------------------------------------------------------------------


# `ALTER TABLE ... DROP COLUMN` needs SQLite >= 3.35 (2021). CI's
# python-build-standalone interpreter bundles a far newer SQLite.
@pytest.mark.parametrize(
    ("statement", "missing"),
    [
        ("ALTER TABLE teams DROP COLUMN alternate_names", "teams.alternate_names"),
        ("ALTER TABLE ratings DROP COLUMN ties", "ratings.ties"),
        ("DROP TABLE rating_breakdowns", "rating_breakdowns"),
        ("DROP INDEX idx_games_source_id", "idx_games_source_id"),
    ],
)
def test_schema_behind_ensure_schema_is_reported(
    current_db: Path,
    raw_dir: Path,
    statement: str,
    missing: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mutate(current_db, statement)

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("schema_not_current", None)}
    assert missing in report.problems[0].message
    assert _run(current_db, raw_dir) == 1
    out = capsys.readouterr().out
    assert OK_LINE not in out
    assert "NOT CURRENT" in out


# ---------------------------------------------------------------------------
# (b) a league with zero games
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", SPORTS)
def test_league_with_no_games_is_reported(current_db: Path, raw_dir: Path, sport: str) -> None:
    _mutate(
        current_db,
        f"DELETE FROM ratings WHERE sport = '{sport}'",
        f"DELETE FROM games WHERE sport = '{sport}'",
    )

    report = currency.check_currency(current_db, raw_dir)

    # Necessarily behind the cache too; (b) is the sharper diagnosis.
    assert _problems(report) == {("league_has_no_games", sport), ("season_behind_cache", sport)}
    assert _run(current_db, raw_dir) == 1


# ---------------------------------------------------------------------------
# (c) a (season, season_type) in the committed cache that the db lacks
# ---------------------------------------------------------------------------


def _behind(report: currency.CurrencyReport, sport: str) -> currency.Problem:
    assert _problems(report) == {("season_behind_cache", sport)}
    return report.problems[0]


@pytest.mark.parametrize("sport", SPORTS)
def test_cached_season_missing_from_games_is_reported(
    tmp_path: Path, current_db: Path, sport: str
) -> None:
    raw_dir = _build_raw_dir(tmp_path, extra={sport: _pairs(EXTRA_SEASON)})

    problem = _behind(currency.check_currency(current_db, raw_dir), sport)

    assert problem.seasons == (EXTRA_SEASON,)
    assert problem.pairs == tuple(_pairs(EXTRA_SEASON))
    assert str(EXTRA_SEASON) in problem.message
    assert _run(current_db, raw_dir) == 1


@pytest.mark.parametrize("season_type", SEASON_TYPES)
@pytest.mark.parametrize("sport", SPORTS)
def test_a_missing_season_type_is_reported_even_when_the_season_has_games(
    current_db: Path, raw_dir: Path, sport: str, season_type: str
) -> None:
    # The likeliest stale latest season: built mid-season, before the
    # postseason existed -- which changes who ranks first.
    season = SEASONS[sport][-1]
    _mutate(
        current_db,
        f"DELETE FROM games WHERE sport = '{sport}' AND season = {season} "
        f"AND season_type = '{season_type}'",
    )

    problem = _behind(currency.check_currency(current_db, raw_dir), sport)

    assert problem.pairs == ((season, season_type),)
    assert problem.seasons == (season,)
    assert season_type in problem.message
    assert _run(current_db, raw_dir) == 1


def test_a_postseason_only_cfb_cache_file_counts_as_a_cached_pair(
    current_db: Path, raw_dir: Path
) -> None:
    (raw_dir / f"{EXTRA_SEASON}_postseason.json").write_text(_ONE_GAME_JSON)

    problem = _behind(currency.check_currency(current_db, raw_dir), "cfb")

    assert problem.pairs == ((EXTRA_SEASON, "postseason"),)


def test_an_empty_cfb_cache_file_is_not_a_cached_pair(current_db: Path, raw_dir: Path) -> None:
    # `cfb ingest` writes zero games from `[]`, so a db without them is not
    # behind that file.
    (raw_dir / f"{EXTRA_SEASON}_postseason.json").write_text("[]")

    assert currency.check_currency(current_db, raw_dir).problems == ()


@pytest.mark.parametrize("edge", ["min_year", "max_year"])
@pytest.mark.parametrize("sport", SPORTS)
def test_the_ingest_window_boundaries_are_checked(
    tmp_path: Path, current_db: Path, sport: str, edge: str
) -> None:
    min_year, max_year = WINDOWS[sport]
    season = min_year if edge == "min_year" else max_year
    assert season not in SEASONS[sport], "fixture seasons must sit strictly inside the window"
    raw_dir = _build_raw_dir(tmp_path, extra={sport: _pairs(season)})

    problem = _behind(currency.check_currency(current_db, raw_dir), sport)

    assert problem.seasons == (season,)


@pytest.mark.parametrize("sport", SPORTS)
def test_seasons_just_outside_the_ingest_window_are_not_flagged(
    tmp_path: Path, current_db: Path, sport: str
) -> None:
    min_year, max_year = WINDOWS[sport]
    # MAX_YEAR+1 as an unfinished (regular-only) season: a finished one past
    # MAX_YEAR is its own problem, tested below.
    raw_dir = _build_raw_dir(
        tmp_path, extra={sport: _pairs(min_year - 1) + [(max_year + 1, "regular")]}
    )

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    assert _run(current_db, raw_dir) == 0


@pytest.mark.parametrize("sport", SPORTS)
def test_a_missing_middle_season_is_flagged(tmp_path: Path, current_db: Path, sport: str) -> None:
    first, middle = SEASONS[sport]
    raw_dir = _build_raw_dir(tmp_path, extra={sport: _pairs(EXTRA_SEASON)})
    # The db has the first and the last cached season, but not the one
    # between them. The whole season moves, ledger included, so the only
    # defect is the gap (a moved rating without its ledger would be (g)'s).
    _mutate(
        current_db,
        f"UPDATE games SET season = {EXTRA_SEASON} WHERE sport = '{sport}' AND season = {middle}",
        f"UPDATE ratings SET year = {EXTRA_SEASON} WHERE sport = '{sport}' AND year = {middle}",
        *(
            f"UPDATE {table} SET year = {EXTRA_SEASON} WHERE sport = '{sport}' AND year = {middle}"
            for table in LEDGER_TABLES
        ),
    )

    problem = _behind(currency.check_currency(current_db, raw_dir), sport)

    assert problem.seasons == (middle,)


# ---------------------------------------------------------------------------
# Cache seasons past an ingest's MAX_YEAR: a note while that season is still
# in progress, a failing problem once it has finished (the #9 class of bug)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", SPORTS)
def test_an_unfinished_season_past_max_year_is_a_note_that_stays_green(
    tmp_path: Path, current_db: Path, sport: str, capsys: pytest.CaptureFixture[str]
) -> None:
    beyond = WINDOWS[sport][1] + 1
    raw_dir = _build_raw_dir(tmp_path, extra={sport: [(beyond, "regular")]})

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    notes = [n for n in report.notes if n.startswith(f"{sport}:")]
    assert len(notes) == 1
    assert str(beyond) in notes[0]
    assert "MAX_YEAR" in notes[0]

    assert _run(current_db, raw_dir) == 0
    out = capsys.readouterr().out
    assert notes[0] in out
    assert OK_LINE in out


def test_no_note_without_cache_seasons_past_max_year(current_db: Path, raw_dir: Path) -> None:
    assert currency.check_currency(current_db, raw_dir).notes == ()


def _past_max_year(report: currency.CurrencyReport, sport: str, season: int) -> None:
    assert _problems(report) == {("cache_past_max_year", sport)}
    problem = report.problems[0]
    assert problem.seasons == (season,)
    assert "MAX_YEAR" in problem.message
    assert not [n for n in report.notes if n.startswith(f"{sport}:")]


def test_a_finished_nfl_season_past_max_year_fails(
    current_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beyond = WINDOWS["nfl"][1] + 1
    _append_nfl_rows(raw_dir, [_nfl_row(beyond, "REG"), _nfl_row(beyond, "SB")])

    _past_max_year(currency.check_currency(current_db, raw_dir), "nfl", beyond)
    assert _run(current_db, raw_dir) == 1
    assert OK_LINE not in capsys.readouterr().out


_PLAYED = ("17", "24")


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([("REG", _PLAYED)], id="regular_season_only"),
        pytest.param(
            [("REG", _PLAYED), ("WC", _PLAYED), ("DIV", _PLAYED), ("CON", _PLAYED)],
            id="no_super_bowl",
        ),
        pytest.param([("REG", _PLAYED), ("SB", ("", ""))], id="super_bowl_scheduled_not_played"),
        # nflverse-style missing values are strings, and "NA" is truthy.
        pytest.param([("REG", _PLAYED), ("SB", ("NA", "NA"))], id="super_bowl_scores_NA"),
        pytest.param([("REG", _PLAYED), ("SB", ("24", ""))], id="super_bowl_away_score_only"),
        pytest.param([("REG", _PLAYED), ("SB", ("NA", "24"))], id="super_bowl_home_score_only"),
    ],
)
def test_an_unfinished_nfl_season_past_max_year_is_only_a_note(
    current_db: Path, raw_dir: Path, rows: list[tuple[str, tuple[str, str]]]
) -> None:
    beyond = WINDOWS["nfl"][1] + 1
    _append_nfl_rows(raw_dir, [_nfl_row(beyond, t, scores=scores) for t, scores in rows])

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    assert len(report.notes) == 1 and str(beyond) in report.notes[0]
    assert _run(current_db, raw_dir) == 0


@pytest.mark.parametrize(
    "postseason",
    [
        pytest.param(_FINISHED_POSTSEASON_JSON, id="every_bowl_played"),
        # CFBD keeps a game that was never played as `completed: false` for
        # good -- the committed cache already holds such games (forfeits and
        # cancellations in 2023_regular.json). One cancelled bowl must not
        # leave a finished season a note forever.
        pytest.param(
            f'[{{"id": 1, "startDate": "{_EARLY_BOWL_DATE}", "completed": false,'
            f' "homePoints": null, "awayPoints": null}},'
            f' {{"id": 2, "startDate": "{_TITLE_GAME_DATE}", "completed": true}}]',
            id="one_earlier_bowl_cancelled",
        ),
    ],
)
def test_a_finished_cfb_season_past_max_year_fails(
    current_db: Path, raw_dir: Path, postseason: str
) -> None:
    beyond = WINDOWS["cfb"][1] + 1
    (raw_dir / f"{beyond}_regular.json").write_text(_ONE_GAME_JSON)
    (raw_dir / f"{beyond}_postseason.json").write_text(postseason)

    _past_max_year(currency.check_currency(current_db, raw_dir), "cfb", beyond)
    assert _run(current_db, raw_dir) == 1


@pytest.mark.parametrize(
    "postseason",
    [
        pytest.param(None, id="no_postseason_file"),
        pytest.param("[]", id="empty_postseason_file"),
        pytest.param(
            f'[{{"id": 1, "startDate": "{_EARLY_BOWL_DATE}", "completed": true}},'
            f' {{"id": 2, "startDate": "{_TITLE_GAME_DATE}", "completed": false}}]',
            id="title_game_still_to_play",
        ),
        pytest.param(
            f'[{{"id": 1, "startDate": "{_TITLE_GAME_DATE}", "completed": true}},'
            f' {{"id": 2, "startDate": "{_TITLE_GAME_DATE}", "completed": false}}]',
            id="latest_date_shared_with_an_unplayed_game",
        ),
        pytest.param('[{"id": 1, "completed": true}]', id="no_game_has_a_start_date"),
    ],
)
def test_an_unfinished_cfb_season_past_max_year_is_only_a_note(
    current_db: Path, raw_dir: Path, postseason: str | None
) -> None:
    beyond = WINDOWS["cfb"][1] + 1
    (raw_dir / f"{beyond}_regular.json").write_text(_ONE_GAME_JSON)
    if postseason is not None:
        (raw_dir / f"{beyond}_postseason.json").write_text(postseason)

    report = currency.check_currency(current_db, raw_dir)

    assert report.problems == ()
    assert len(report.notes) == 1 and str(beyond) in report.notes[0]
    assert _run(current_db, raw_dir) == 0


# ---------------------------------------------------------------------------
# (d) a season with games but no ratings for some method
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("sport", SPORTS)
def test_season_missing_ratings_for_a_method_is_reported(
    current_db: Path, raw_dir: Path, sport: str, method: str
) -> None:
    season = SEASONS[sport][0]
    _mutate(
        current_db,
        f"DELETE FROM ratings WHERE sport = '{sport}' AND year = {season} AND method = '{method}'",
    )

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_missing_ratings", sport)}
    problem = report.problems[0]
    assert problem.seasons == (season,)
    assert method in problem.message
    assert _run(current_db, raw_dir) == 1


# ---------------------------------------------------------------------------
# (g) elo ratings whose ledger is missing (issue #193)
# ---------------------------------------------------------------------------


def test_ledger_methods_match_the_contract_note() -> None:
    # `contracts.TeamCase.elo_ledger`: only `elo` writes a ledger.
    assert currency.LEDGER_METHODS == LEDGER_METHODS
    assert set(currency.LEDGER_METHODS) <= set(METHODS)


@pytest.mark.parametrize("sport", SPORTS)
def test_ledger_seasons_are_read_per_ledger_method(
    current_db: Path, raw_dir: Path, sport: str, capsys: pytest.CaptureFixture[str]
) -> None:
    report = currency.check_currency(current_db, raw_dir)

    league = next(league for league in report.leagues if league.sport == sport)
    assert tuple(league.ledger_seasons) == LEDGER_METHODS
    for method in LEDGER_METHODS:
        assert league.ledger_seasons[method] == SEASONS[sport]
    assert report.problems == ()

    assert _run(current_db, raw_dir) == 0
    assert "ledger" in capsys.readouterr().out


@pytest.mark.parametrize(
    "tables",
    [
        pytest.param(LEDGER_TABLES, id="both_tables"),
        pytest.param(("elo_ledger_configs",), id="configs_only"),
        pytest.param(("elo_ledger_steps",), id="steps_only"),
    ],
)
@pytest.mark.parametrize("sport", SPORTS)
def test_elo_ratings_without_their_ledger_are_reported(
    current_db: Path, raw_dir: Path, sport: str, tables: tuple[str, ...]
) -> None:
    # The #97 false-green shape after #183: `ensure_schema` adds the empty
    # ledger tables to a db whose elo ratings were computed before them.
    _drop_ledger(current_db, sport, SEASONS[sport], tables)

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_missing_elo_ledger", sport)}
    (problem,) = report.problems
    assert problem.seasons == SEASONS[sport]
    assert currency.format_seasons(SEASONS[sport]) in problem.message
    assert f"cfb rate --sport {sport} --method elo" in problem.message
    assert _run(current_db, raw_dir) == 1


@pytest.mark.parametrize("sport", SPORTS)
def test_missing_ledger_for_some_elo_seasons_names_exactly_those(
    current_db: Path, raw_dir: Path, sport: str
) -> None:
    missing, kept = SEASONS[sport]
    _drop_ledger(current_db, sport, (missing,))

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_missing_elo_ledger", sport)}
    (problem,) = report.problems
    assert problem.seasons == (missing,)
    assert str(missing) in problem.message
    assert str(kept) not in problem.message
    assert _run(current_db, raw_dir) == 1


@pytest.mark.parametrize("sport", SPORTS)
def test_a_db_with_only_keener_ratings_has_no_ledger_problem(
    current_db: Path, raw_dir: Path, sport: str
) -> None:
    # Keener writes a rating_breakdown, not a ledger: no elo ratings, no
    # ledger to miss. The unrated methods are (d)'s problem, not (g)'s.
    _mutate(current_db, f"DELETE FROM ratings WHERE sport = '{sport}' AND method != 'keener'")
    _drop_ledger(current_db, sport, SEASONS[sport])

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_missing_ratings", sport)}
    league = next(league for league in report.leagues if league.sport == sport)
    assert league.ledger_seasons["elo"] == ()


def test_a_db_whose_schema_predates_the_ledger_tables_is_reported_not_crashed(
    current_db: Path, raw_dir: Path
) -> None:
    # A pre-#183 db before `ensure_schema` ever ran on it: the tables the
    # ledger check reads do not exist. Reported (a) plus (g), never raised.
    _mutate(current_db, "DROP TABLE elo_ledger_steps", "DROP TABLE elo_ledger_configs")

    report = currency.check_currency(current_db, raw_dir)

    problems = _problems(report)
    assert ("schema_not_current", None) in problems
    for sport in SPORTS:
        assert ("season_missing_elo_ledger", sport) in problems
    assert _run(current_db, raw_dir) == 1


def test_a_real_elo_run_on_the_regression_fixture_writes_the_ledger_the_doctor_reads(
    regression_db: Path, raw_dir: Path
) -> None:
    """The synthetic fixture rows above are only as good as their resemblance
    to what `cfb rate --method elo` stores: check the doctor against a real
    run, then against that run with its steps deleted."""
    conn = get_conn(regression_db)
    try:
        assert compute_and_store(conn, 2005, "elo") > 0
    finally:
        conn.close()

    report = currency.check_currency(regression_db, raw_dir)
    cfb = next(league for league in report.leagues if league.sport == "cfb")
    assert cfb.rated_seasons["elo"] == (2005,)
    assert cfb.ledger_seasons["elo"] == (2005,)
    assert [p for p in report.problems if p.code == "season_missing_elo_ledger"] == []

    _drop_ledger(regression_db, "cfb", (2005,), ("elo_ledger_steps",))

    report = currency.check_currency(regression_db, raw_dir)
    ledger = [p for p in report.problems if p.code == "season_missing_elo_ledger"]
    assert len(ledger) == 1
    assert ledger[0].sport == "cfb"
    assert ledger[0].seasons == (2005,)


# ---------------------------------------------------------------------------
# (e) no CFB mascots although the CFBD /teams cache is committed
# ---------------------------------------------------------------------------


def test_cfb_teams_with_no_mascots_are_reported_even_when_nfl_teams_have_one(
    current_db: Path, raw_dir: Path
) -> None:
    _mutate(current_db, "UPDATE teams SET mascot = NULL WHERE sport = 'cfb'")
    conn = sqlite3.connect(current_db)
    nfl_mascots = conn.execute("SELECT COUNT(mascot) FROM teams WHERE sport = 'nfl'").fetchone()[0]
    conn.close()
    assert nfl_mascots > 0, "fixture must give an NFL team a mascot, or the CFB scoping is untested"

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("no_cfb_mascots", "cfb")}
    assert _run(current_db, raw_dir) == 1


def test_no_mascot_problem_for_a_db_with_no_cfb_teams(current_db: Path, raw_dir: Path) -> None:
    # "none of the 0 CFB teams has a mascot" would only repeat (b).
    _mutate(
        current_db,
        "DELETE FROM ratings WHERE sport = 'cfb'",
        "DELETE FROM games WHERE sport = 'cfb'",
        "DELETE FROM teams WHERE sport = 'cfb'",
    )

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("league_has_no_games", "cfb"), ("season_behind_cache", "cfb")}


# ---------------------------------------------------------------------------
# A real-shaped stale db: reported, not crashed on, and never modified
# ---------------------------------------------------------------------------

# The pre-#51 shape of the tables the doctor reads (the founder's local db as
# of #97): no `sport`, no `source_id`, no mascot/alias columns, no `ties`,
# and no rating_breakdowns/ingestion_log/team_season tables at all.
_PRE_51_DDL = """
CREATE TABLE teams (id INTEGER PRIMARY KEY, school TEXT NOT NULL, classification TEXT);
CREATE TABLE games (
    id INTEGER PRIMARY KEY, season INTEGER NOT NULL, week INTEGER,
    season_type TEXT NOT NULL, start_date TEXT,
    neutral_site INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
    home_team_id INTEGER NOT NULL, away_team_id INTEGER NOT NULL,
    home_team TEXT NOT NULL, away_team TEXT NOT NULL,
    home_points INTEGER, away_points INTEGER,
    home_conference TEXT, away_conference TEXT, venue TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'keener', team_id INTEGER NOT NULL,
    rating REAL NOT NULL, rank INTEGER NOT NULL, wins INTEGER NOT NULL,
    losses INTEGER NOT NULL, computed_at TEXT NOT NULL, UNIQUE(year, method, team_id)
);
"""


@pytest.fixture
def pre_51_db(tmp_path: Path) -> Path:
    db = tmp_path / "pre_51.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(_PRE_51_DDL)
    conn.execute("INSERT INTO teams VALUES (1, 'Alabama', 'fbs'), (2, 'Auburn', 'fbs')")
    for season in SEASONS["cfb"]:
        conn.execute(
            "INSERT INTO games (id, season, week, season_type, completed, home_team_id, "
            "away_team_id, home_team, away_team, home_points, away_points, raw_json) "
            "VALUES (?, ?, 1, 'regular', 1, 1, 2, 'Alabama', 'Auburn', 21, 14, '{}')",
            (season, season),
        )
        conn.execute(
            "INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, computed_at) "
            "VALUES (?, 'keener', 1, 1.0, 1, 1, 0, '2026-01-01T00:00:00+00:00')",
            (season,),
        )
    conn.commit()
    conn.close()
    return db


def test_pre_51_db_is_reported_as_stale_rather_than_crashing(
    pre_51_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = currency.check_currency(pre_51_db, raw_dir)

    problems = _problems(report)
    assert ("schema_not_current", None) in problems
    assert ("league_has_no_games", "nfl") in problems
    assert ("no_cfb_mascots", "cfb") in problems
    # Rows without a `sport` column are CFB, exactly as the migration would
    # backfill them -- so CFB's games are found, not reported missing.
    assert ("league_has_no_games", "cfb") not in problems
    cfb = next(league for league in report.leagues if league.sport == "cfb")
    assert cfb.game_seasons == SEASONS["cfb"]
    assert cfb.rated_seasons["keener"] == SEASONS["cfb"]

    assert _run(pre_51_db, raw_dir) == 1
    out = capsys.readouterr().out
    assert "teams.mascot" in out
    assert "nfl" in out
    assert "NOT CURRENT" in out
    assert OK_LINE not in out


def test_doctor_leaves_a_stale_db_byte_identical(pre_51_db: Path, raw_dir: Path) -> None:
    before = _sha256(pre_51_db)
    siblings_before = _siblings(pre_51_db)

    assert _run(pre_51_db, raw_dir) == 1

    assert _sha256(pre_51_db) == before, "cfb doctor modified the database it was checking"
    # No journal/WAL/shm left behind either.
    assert _siblings(pre_51_db) == siblings_before


def test_missing_db_file_exits_nonzero_with_a_clear_message(
    tmp_path: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.sqlite3"

    assert _run(missing, raw_dir) == 1

    err = capsys.readouterr().err
    assert str(missing) in err
    assert "does not exist" in err
    assert "Traceback" not in err
    assert not missing.exists(), "the doctor must not create the db it was asked to check"


def test_a_file_that_is_not_a_sqlite_db_exits_nonzero_with_a_clear_message(
    tmp_path: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bogus = tmp_path / "bogus.sqlite3"
    bogus.write_text("this is not a database, just some text " * 20)

    assert _run(bogus, raw_dir) == 1

    err = capsys.readouterr().err
    assert str(bogus) in err
    assert GENERIC_UNREADABLE in err
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# WAL-mode databases. Each test's outcome is fixed by what the doctor does,
# not by the platform's SQLite build: see the module docstring.
# ---------------------------------------------------------------------------


def _header(write_read_versions: bytes) -> bytes:
    """The first 100 bytes of a sqlite file: magic, page size, then the file
    format write/read versions at offsets 18/19 (1 = rollback, 2 = WAL)."""
    return b"SQLite format 3\x00" + b"\x10\x00" + write_read_versions + b"\x00" * 80


WAL_HEADER = _header(b"\x02\x02")
ROLLBACK_HEADER = _header(b"\x01\x01")


def _to_wal_without_sidecars(db: Path) -> None:
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    # Every committed page is in the main file after the checkpoint, so these
    # are safe to remove -- which is exactly the state of a WAL db copied
    # without its sidecars, or closed cleanly on Linux.
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    assert currency._is_wal_mode(db)


def test_a_wal_db_without_its_sidecar_files_is_checked_normally_and_left_untouched(
    current_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _to_wal_without_sidecars(current_db)
    before = _sha256(current_db)
    siblings_before = _siblings(current_db)

    assert _run(current_db, raw_dir) == 0

    assert OK_LINE in capsys.readouterr().out
    assert _sha256(current_db) == before
    # A read-only open that isn't immutable may create -wal/-shm next to the
    # db on some platforms; the doctor must not.
    assert _siblings(current_db) == siblings_before


def test_a_wal_db_without_its_sidecar_files_still_reports_its_defects(
    current_db: Path, raw_dir: Path
) -> None:
    _drop_season(current_db, "nfl", SEASONS["nfl"][-1])
    _to_wal_without_sidecars(current_db)
    siblings_before = _siblings(current_db)

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_behind_cache", "nfl")}
    assert report.problems[0].seasons == (SEASONS["nfl"][-1],)
    assert _run(current_db, raw_dir) == 1
    assert _siblings(current_db) == siblings_before


def test_a_wal_db_with_only_a_stale_shm_file_is_checked_normally_and_left_untouched(
    current_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A -shm is only an index into a -wal: with no -wal there are no
    # un-checkpointed commits to miss, so -wal alone decides. A plain
    # mode=ro open would still try to use the lone -shm (SQLITE_CANTOPEN on
    # macOS; possibly a new -wal next to the db elsewhere).
    _to_wal_without_sidecars(current_db)
    shm = Path(f"{current_db}-shm")
    shm.write_bytes(b"\x00" * 32768)
    before, shm_before = _sha256(current_db), _sha256(shm)
    siblings_before = _siblings(current_db)

    assert _run(current_db, raw_dir) == 0

    assert OK_LINE in capsys.readouterr().out
    assert _sha256(current_db) == before
    assert _sha256(shm) == shm_before
    assert _siblings(current_db) == siblings_before


def test_a_live_wal_db_is_read_through_its_wal_file_never_around_it(
    current_db: Path, raw_dir: Path
) -> None:
    # A writer still holds the db, and its last commit lives only in -wal.
    # `immutable` would ignore -wal and report the stale main file instead.
    holder = sqlite3.connect(current_db)
    try:
        assert holder.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        holder.execute("PRAGMA wal_autocheckpoint = 0")
        holder.execute("DELETE FROM ratings WHERE sport = 'nfl'")
        holder.execute("DELETE FROM games WHERE sport = 'nfl'")
        holder.commit()
        assert Path(f"{current_db}-wal").stat().st_size > 0

        report = currency.check_currency(current_db, raw_dir)
    finally:
        holder.close()

    assert _problems(report) == {("league_has_no_games", "nfl"), ("season_behind_cache", "nfl")}


@pytest.mark.parametrize(
    ("header", "sidecar", "expect_wal_hint"),
    [
        pytest.param(WAL_HEADER, "-wal", True, id="wal_header_with_wal_file"),
        # Without a -wal the db is opened immutable, which never touches the
        # -shm, so a lone -shm cannot be why the open failed.
        pytest.param(WAL_HEADER, "-shm", False, id="wal_header_with_only_a_shm_file"),
        pytest.param(WAL_HEADER, None, False, id="wal_looking_header_no_sidecars"),
        pytest.param(ROLLBACK_HEADER, "-wal", False, id="rollback_header"),
    ],
)
def test_the_wal_hint_is_shown_only_when_a_wal_file_exists(
    tmp_path: Path,
    raw_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    header: bytes,
    sidecar: str | None,
    expect_wal_hint: bool,
) -> None:
    db = tmp_path / "unopenable.sqlite3"
    db.write_bytes(header)
    if sidecar is not None:
        Path(f"{db}{sidecar}").write_bytes(b"")

    def refuse_to_open(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(currency, "get_conn", refuse_to_open)

    assert _run(db, raw_dir) == 1

    err = capsys.readouterr().err
    assert str(db) in err
    assert "Traceback" not in err
    if expect_wal_hint:
        assert "WAL-mode" in err
        assert GENERIC_UNREADABLE not in err
    else:
        assert "WAL-mode" not in err
        assert GENERIC_UNREADABLE in err


def test_a_corrupt_file_with_a_wal_looking_header_gets_the_generic_message(
    tmp_path: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bogus = tmp_path / "corrupt.sqlite3"
    bogus.write_bytes(WAL_HEADER + b"\xff" * 4000)

    assert _run(bogus, raw_dir) == 1

    err = capsys.readouterr().err
    assert GENERIC_UNREADABLE in err
    assert "WAL-mode" not in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(WAL_HEADER, True, id="wal"),
        pytest.param(ROLLBACK_HEADER, False, id="rollback"),
        pytest.param(WAL_HEADER[:19], False, id="truncated_header"),
        pytest.param(b"not a sqlite file, although long enough", False, id="not_sqlite"),
        pytest.param(
            b"Not SQLite form" + b"\x00\x10\x00\x02\x02" + b"\x00" * 80, False, id="bad_magic"
        ),
    ],
)
def test_is_wal_mode_reads_the_header_bytes(tmp_path: Path, content: bytes, expected: bool) -> None:
    path = tmp_path / "header.bin"
    path.write_bytes(content)

    assert currency._is_wal_mode(path) is expected
