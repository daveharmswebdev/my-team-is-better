"""Coverage for `cfb doctor` (issue #97, epic #113): a read-only check that a
sqlite db's *data* is current, not just its schema.

The failure this guards against is real, not hypothetical: a machine-local
`data/cfb.sqlite3` built before #51 is a complete-looking 790-team CFB ingest
with no NFL rows and no mascots, and `ensure_schema` happily migrates the
missing columns into it -- producing a current-*schema* db whose data is
still stale. Nothing distinguished it from a fresh build.

Every defect test below starts from a tiny db that is current in every
respect (`_build_current_db`, paired with a tiny fake raw cache from
`_build_raw_dir`), applies exactly one defect, and asserts the doctor reports
exactly that one problem -- so disabling any single check turns at least one
test red rather than hiding behind another check that also fires.

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
from cfb_strength.contracts import Method, Sport
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest import currency

SPORTS: tuple[str, ...] = get_args(Sport)
METHODS: tuple[str, ...] = get_args(Method)

# Seasons each league's fixture db holds games and every method's ratings
# for, and that its fake raw cache holds. All inside both ingest windows
# (CFB 1998-2025, NFL 1999-2025).
SEASONS: dict[str, tuple[int, ...]] = {"cfb": (2001, 2002), "nfl": (2001, 2002)}
EXTRA_SEASON = 2003


def _team_ids(sport: str) -> tuple[int, int]:
    base = SPORTS.index(sport) * 1_000_000_000
    return base + 1, base + 2


def _build_current_db(path: Path) -> Path:
    conn = get_conn(path)
    ensure_schema(conn)
    for sport, seasons in SEASONS.items():
        home, away = _team_ids(sport)
        for team_id, school in ((home, f"{sport} Home"), (away, f"{sport} Away")):
            mascot = "Mascots" if sport == "cfb" and team_id == home else None
            conn.execute(
                "INSERT INTO teams (id, school, classification, sport, mascot) VALUES (?, ?, ?, ?, ?)",
                (team_id, school, "fbs" if sport == "cfb" else None, sport, mascot),
            )
        for season in seasons:
            conn.execute(
                """
                INSERT INTO games (
                    id, season, week, season_type, neutral_site, completed,
                    home_team_id, away_team_id, home_team, away_team,
                    home_points, away_points, raw_json, sport
                ) VALUES (?, ?, 1, 'regular', 0, 1, ?, ?, ?, ?, 21, 14, '{}', ?)
                """,
                (home + season * 10, season, home, away, f"{sport} Home", f"{sport} Away", sport),
            )
            for method in METHODS:
                for rank, team_id in enumerate((home, away), start=1):
                    conn.execute(
                        "INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, "
                        "ties, computed_at, sport) VALUES (?, ?, ?, ?, ?, ?, ?, 0, "
                        "'2026-01-01T00:00:00+00:00', ?)",
                        (season, method, team_id, 1.0 / rank, rank, 2 - rank, rank - 1, sport),
                    )
    conn.commit()
    conn.close()
    return path


def _write_cfb_cache(raw_dir: Path, seasons: tuple[int, ...]) -> None:
    for season in seasons:
        for season_type in ("regular", "postseason"):
            (raw_dir / f"{season}_{season_type}.json").write_text("[]")
    # Outside the CFB ingest window (1998-2025): `cfb ingest` would never
    # write it, so a db lacking it is not behind the cache.
    (raw_dir / "1997_regular.json").write_text("[]")
    (raw_dir / "teams.json").write_text("[]")


def _write_nfl_cache(raw_dir: Path, seasons: tuple[int, ...]) -> None:
    nfl = raw_dir / "nfl"
    nfl.mkdir(parents=True, exist_ok=True)
    with (nfl / "games.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["game_id", "season", "game_type", "week", "away_team", "home_team"])
        for season in seasons:
            writer.writerow([f"{season}_01_BUF_NE", season, "REG", 1, "BUF", "NE"])
        # The in-progress season nflverse already publishes rows for, outside
        # the NFL ingest window (1999-2025) -- exactly what the real
        # committed games.csv carries, and what Render's build never ingests.
        writer.writerow(["2026_01_BUF_NE", 2026, "REG", 1, "BUF", "NE"])


CACHE_WRITERS = {"cfb": _write_cfb_cache, "nfl": _write_nfl_cache}


def _build_raw_dir(
    tmp_path: Path,
    *,
    skip: tuple[str, ...] = (),
    extra: dict[str, tuple[int, ...]] | None = None,
) -> Path:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for sport, seasons in SEASONS.items():
        if sport in skip:
            continue
        CACHE_WRITERS[sport](raw_dir, seasons + (extra or {}).get(sport, ()))
    return raw_dir


def _problems(report: currency.CurrencyReport) -> set[tuple[str, str | None]]:
    return {(p.code, p.sport) for p in report.problems}


def _mutate(db: Path, *statements: str) -> None:
    conn = sqlite3.connect(db)
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def current_db(tmp_path: Path) -> Path:
    return _build_current_db(tmp_path / "current.sqlite3")


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    return _build_raw_dir(tmp_path)


def test_fixtures_cover_every_league_in_the_alias() -> None:
    # A league added to `Sport` must get a fixture db and a fake cache here,
    # or the "fully current" test below would stop covering it.
    assert set(SEASONS) == set(SPORTS)
    assert set(CACHE_WRITERS) == set(SPORTS)


# ---------------------------------------------------------------------------
# The healthy case
# ---------------------------------------------------------------------------


def test_fully_current_db_reports_no_problems_and_exits_zero(
    current_db: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = currency.check_currency(current_db, raw_dir)
    assert report.problems == ()
    assert report.is_current

    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 0
    out = capsys.readouterr().out
    for sport in SPORTS:
        assert sport in out
    for method in METHODS:
        assert method in out
    assert "mascot" in out


def test_expected_leagues_and_methods_come_from_the_contract_aliases(
    current_db: Path, raw_dir: Path
) -> None:
    report = currency.check_currency(current_db, raw_dir)

    assert tuple(league.sport for league in report.leagues) == SPORTS
    for league in report.leagues:
        assert tuple(league.rated_seasons) == METHODS
        assert league.game_seasons == SEASONS[league.sport]
        for method in METHODS:
            assert league.rated_seasons[method] == SEASONS[league.sport]


def test_every_league_has_a_raw_cache_reader() -> None:
    # A league without one would never be checked against its cache (c).
    assert set(currency.CACHED_SEASON_READERS) == set(SPORTS)


def test_a_missing_raw_dir_is_a_problem_not_a_silent_skip(
    tmp_path: Path, current_db: Path
) -> None:
    report = currency.check_currency(current_db, tmp_path / "no-such-raw-dir")

    assert _problems(report) == {("raw_cache_missing", None)}


def test_cli_dispatches_doctor(current_db: Path, raw_dir: Path) -> None:
    assert "doctor" in cli.USAGE
    assert cli.main(["doctor", "--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 0


# ---------------------------------------------------------------------------
# (a) schema not current -- reported, never fixed
# ---------------------------------------------------------------------------


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
    current_db: Path, raw_dir: Path, statement: str, missing: str
) -> None:
    _mutate(current_db, statement)

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("schema_not_current", None)}
    assert missing in report.problems[0].message
    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 1


# ---------------------------------------------------------------------------
# (b) a league with zero games
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", SPORTS)
def test_league_with_no_games_is_reported(tmp_path: Path, current_db: Path, sport: str) -> None:
    # No cache for that league either, so this is the one defect: the
    # behind-cache check (c) has nothing to compare against.
    raw_dir = _build_raw_dir(tmp_path, skip=(sport,))
    _mutate(
        current_db,
        f"DELETE FROM ratings WHERE sport = '{sport}'",
        f"DELETE FROM games WHERE sport = '{sport}'",
    )

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("league_has_no_games", sport)}
    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 1


# ---------------------------------------------------------------------------
# (c) a season in the committed cache that the db lacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", SPORTS)
def test_cached_season_missing_from_games_is_reported(
    tmp_path: Path, current_db: Path, sport: str
) -> None:
    raw_dir = _build_raw_dir(tmp_path, extra={sport: (EXTRA_SEASON,)})

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_behind_cache", sport)}
    assert report.problems[0].seasons == (EXTRA_SEASON,)
    assert str(EXTRA_SEASON) in report.problems[0].message
    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 1


def test_a_postseason_only_cfb_cache_file_still_counts_as_a_cached_season(
    current_db: Path, raw_dir: Path
) -> None:
    (raw_dir / f"{EXTRA_SEASON}_postseason.json").write_text("[]")

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("season_behind_cache", "cfb")}
    assert report.problems[0].seasons == (EXTRA_SEASON,)


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
    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 1


# ---------------------------------------------------------------------------
# (e) no CFB mascots although the CFBD /teams cache is committed
# ---------------------------------------------------------------------------


def test_cfb_teams_with_no_mascots_are_reported_when_the_teams_cache_exists(
    current_db: Path, raw_dir: Path
) -> None:
    _mutate(current_db, "UPDATE teams SET mascot = NULL WHERE sport = 'cfb'")

    report = currency.check_currency(current_db, raw_dir)

    assert _problems(report) == {("no_cfb_mascots", "cfb")}
    assert currency.main(["--db-path", str(current_db), "--raw-dir", str(raw_dir)]) == 1


def test_no_mascots_is_not_a_problem_without_a_teams_cache(current_db: Path, raw_dir: Path) -> None:
    _mutate(current_db, "UPDATE teams SET mascot = NULL WHERE sport = 'cfb'")
    (raw_dir / "teams.json").unlink()

    assert currency.check_currency(current_db, raw_dir).problems == ()


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

    assert currency.main(["--db-path", str(pre_51_db), "--raw-dir", str(raw_dir)]) == 1
    out = capsys.readouterr().out
    assert "teams.mascot" in out
    assert "nfl" in out


def test_doctor_leaves_a_stale_db_byte_identical(pre_51_db: Path, raw_dir: Path) -> None:
    before = _sha256(pre_51_db)
    siblings_before = sorted(p.name for p in pre_51_db.parent.iterdir())

    assert currency.main(["--db-path", str(pre_51_db), "--raw-dir", str(raw_dir)]) == 1

    assert _sha256(pre_51_db) == before, "cfb doctor modified the database it was checking"
    # No journal/WAL/shm left behind either.
    assert sorted(p.name for p in pre_51_db.parent.iterdir()) == siblings_before


def test_missing_db_file_exits_nonzero_with_a_clear_message(
    tmp_path: Path, raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.sqlite3"

    assert currency.main(["--db-path", str(missing), "--raw-dir", str(raw_dir)]) == 1

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

    assert currency.main(["--db-path", str(bogus), "--raw-dir", str(raw_dir)]) == 1

    err = capsys.readouterr().err
    assert str(bogus) in err
    assert "Traceback" not in err
