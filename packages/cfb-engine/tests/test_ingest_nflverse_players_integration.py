"""Integration coverage for the nflverse player-stats ingest (issue #289):
real projected nflverse rows, written into a copy of the committed NFL
golden fixture db (`tests/fixtures/nfl_regression.sqlite3`, whose games and
teams came from the existing NFL ingest), then read back with SQL.

`tests/fixtures/raw_nfl_player_sample/nfl/` holds small cuts of the
projected cache, one file per season, plus the matching `players.csv` rows:

* 1999: every LA (St. Louis) and IND line, and every line of
  `1999_09_PHI_CAR` (Steve Bono's empty-team row) and `1999_15_NO_BAL`
  (P. Franklin, an unknown player with no name).
* 2001: every line of `2001_11_GB_DET` (a 'Team' line with no player id).
* 2004: IND and NE. 2013: DEN and NO. 2022: KC and TB, plus every line of
  the four games nflverse lists the wrong starter for.
* `players.csv`: every player those lines reference and every QB the
  schedule lists in 1999/2004/2013/2022.

A starter is decided per side from that side's own lines, so a cut that
keeps every line of a team reproduces that team's full-season starters and
totals exactly. `test_player_sample_rows_are_in_the_committed_cache` keeps
the cut honest, and the committed-cache tests at the bottom check the
season-wide counts the cut can't.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.config import RAW_DIR
from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.nflverse import client as nflverse_client
from cfb_strength.ingest.nflverse import player_normalize
from cfb_strength.ingest.nflverse.ingest_players import (
    PlayerIngestReport,
    ingest_players,
    main,
)
from cfb_strength.ingest.nflverse.normalize import mint_surrogate_id
from cfb_strength.ingest.nflverse.player_normalize import STAT_FIELDS, PlayerSeasonReport

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PLAYER_SAMPLE_DIR = FIXTURES_DIR / "raw_nfl_player_sample" / "nfl"
TEAMS_SAMPLE = FIXTURES_DIR / "raw_nfl_teams_sample.csv"
FIXTURE_SEASONS = (1999, 2004, 2013, 2022)
WRITTEN_TABLES = (
    "players",
    "player_source_ids",
    "game_starters",
    "player_game_stats",
    "player_season_stats",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _sample_raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    (raw / "nfl").mkdir(parents=True)
    for path in PLAYER_SAMPLE_DIR.iterdir():
        shutil.copy(path, raw / "nfl" / path.name)
    shutil.copy(TEAMS_SAMPLE, raw / "nfl" / "teams.csv")
    return raw


def _refuse_live_fetch(url: str) -> str:
    raise AssertionError(f"live fetch attempted: {url}")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nflverse_client, "_fetch_csv_live", _refuse_live_fetch)


@pytest.fixture
def ingested(
    nfl_regression_db: Path, tmp_path: Path, no_network: None
) -> Iterator[tuple[sqlite3.Connection, PlayerIngestReport]]:
    conn = get_conn(nfl_regression_db)
    try:
        report = ingest_players(conn, list(FIXTURE_SEASONS), raw_dir=_sample_raw_dir(tmp_path))
        yield conn, report
    finally:
        conn.close()


def _player_id(conn: sqlite3.Connection, name: str) -> int:
    rows = conn.execute(
        "SELECT id FROM players WHERE sport = 'nfl' AND display_name = ?", (name,)
    ).fetchall()
    assert len(rows) == 1, f"expected one player named {name!r}, got {len(rows)}"
    return int(rows[0]["id"])


def _season_row(conn: sqlite3.Connection, name: str, season: int, season_type: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM player_season_stats WHERE player_id = ? AND season = ? AND season_type = ?",
        (_player_id(conn, name), season, season_type),
    ).fetchone()
    assert row is not None
    return row


def _starter_record(
    conn: sqlite3.Connection, name: str, season: int, season_type: str
) -> tuple[int, int, int]:
    rows = conn.execute(
        """
        SELECT s.team_id, g.home_team_id, g.home_points, g.away_points
        FROM game_starters s JOIN games g ON g.id = s.game_id
        WHERE s.player_id = ? AND g.season = ? AND g.season_type = ? AND s.position = 'QB'
        """,
        (_player_id(conn, name), season, season_type),
    ).fetchall()
    wins = losses = ties = 0
    for r in rows:
        mine, theirs = (
            (r["home_points"], r["away_points"])
            if r["team_id"] == r["home_team_id"]
            else (r["away_points"], r["home_points"])
        )
        if mine > theirs:
            wins += 1
        elif mine < theirs:
            losses += 1
        else:
            ties += 1
    return wins, losses, ties


def _season_report(report: PlayerIngestReport, season: int) -> PlayerSeasonReport:
    return next(s for s in report.seasons if s.season == season)


def _game_id(source_id: str) -> int:
    return mint_surrogate_id("nfl_game", source_id)


# --- the contract's expected values ----------------------------------------

REGULAR_TOTALS = [
    # name, season, (yards, tds, ints), games, (w, l, t)
    ("Kurt Warner", 1999, (4044, 38, 11), 15, (13, 3, 0)),
    ("Peyton Manning", 1999, (4135, 26, 15), 16, (13, 3, 0)),
    ("Peyton Manning", 2004, (4557, 49, 10), 16, (12, 3, 0)),
    ("Tom Brady", 2004, (3690, 28, 14), 16, (14, 2, 0)),
    ("Peyton Manning", 2013, (5477, 55, 10), 16, (13, 3, 0)),
    ("Drew Brees", 2013, (5162, 39, 12), 16, (11, 5, 0)),
    ("Patrick Mahomes", 2022, (5250, 41, 12), 17, (14, 3, 0)),
    ("Tom Brady", 2022, (4694, 25, 9), 17, (8, 8, 0)),
]

POSTSEASON_TOTALS = [
    ("Kurt Warner", 1999, (1063, 8, 4), 3, (3, 0, 0)),
    ("Peyton Manning", 2004, (695, 4, 2), 2, (1, 1, 0)),
    ("Tom Brady", 2004, (587, 5, 0), 3, (3, 0, 0)),
    ("Peyton Manning", 2013, (910, 5, 3), 3, (2, 1, 0)),
    ("Patrick Mahomes", 2022, (703, 7, 0), 3, (3, 0, 0)),
]


@pytest.mark.parametrize(("name", "season", "totals", "games", "record"), REGULAR_TOTALS)
def test_regular_season_totals_and_starter_records_match_the_contract(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
    name: str,
    season: int,
    totals: tuple[int, int, int],
    games: int,
    record: tuple[int, int, int],
) -> None:
    conn, _ = ingested
    row = _season_row(conn, name, season, "regular")
    assert (row["passing_yards"], row["passing_tds"], row["passing_interceptions"]) == totals
    assert row["games"] == games
    assert row["source"] == "nflverse"
    assert _starter_record(conn, name, season, "regular") == record


@pytest.mark.parametrize(("name", "season", "totals", "games", "record"), POSTSEASON_TOTALS)
def test_postseason_totals_and_starter_records_match_the_contract(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
    name: str,
    season: int,
    totals: tuple[int, int, int],
    games: int,
    record: tuple[int, int, int],
) -> None:
    conn, _ = ingested
    row = _season_row(conn, name, season, "postseason")
    assert (row["passing_yards"], row["passing_tds"], row["passing_interceptions"]) == totals
    assert row["games"] == games
    assert _starter_record(conn, name, season, "postseason") == record


def test_season_row_is_the_sum_of_its_game_rows_with_the_one_team(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, _ = ingested
    warner = _player_id(conn, "Kurt Warner")
    sums = conn.execute(
        f"""
        SELECT COUNT(*) AS games, {", ".join(f"SUM({c}) AS {c}" for c in STAT_FIELDS)},
               COUNT(DISTINCT p.team_id) AS teams, MIN(p.team_id) AS team_id
        FROM player_game_stats p JOIN games g ON g.id = p.game_id
        WHERE p.player_id = ? AND g.season = 1999 AND g.season_type = 'regular'
        """,
        (warner,),
    ).fetchone()
    row = _season_row(conn, "Kurt Warner", 1999, "regular")

    assert all(row[c] == sums[c] for c in STAT_FIELDS)
    assert row["games"] == sums["games"]
    assert sums["teams"] == 1
    assert row["team_id"] == sums["team_id"] == mint_surrogate_id("nfl_team", "STL")


def test_no_season_row_invents_a_null_stat_in_the_sample_seasons(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, _ = ingested
    # Every stat line in the projected cache carries all ten columns, so a
    # NULL can only come from a column the source leaves empty. None do in
    # these seasons: nothing may have been invented as NULL either.
    nulls = conn.execute(
        f"SELECT COUNT(*) FROM player_season_stats WHERE "
        f"{' OR '.join(f'{c} IS NULL' for c in STAT_FIELDS)}"
    ).fetchone()[0]
    assert nulls == 0


def test_a_stat_missing_on_every_game_row_stays_null_while_an_all_zero_stat_stays_zero(
    nfl_regression_db: Path, tmp_path: Path, no_network: None
) -> None:
    # An untracked stat is NULL on every line; the season total must stay
    # NULL, never read as 0. Edgerrin James's 1999 regular-season lines carry
    # passing_yards 0 on all 16, which must stay a real 0.
    raw = _sample_raw_dir(tmp_path)
    path = raw / "nfl" / "stats_player_week_1999.csv"
    rows = _read_csv(path)
    for row in rows:
        row["sacks_suffered"] = ""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    james = [
        r
        for r in rows
        if r["player_display_name"] == "Edgerrin James" and r["season_type"] == "REG"
    ]
    assert len(james) == 16 and {r["passing_yards"] for r in james} == {"0"}

    conn = get_conn(nfl_regression_db)
    try:
        ingest_players(conn, [1999], raw_dir=raw)
        james_row = _season_row(conn, "Edgerrin James", 1999, "regular")
        warner_row = _season_row(conn, "Kurt Warner", 1999, "regular")
        game_lines_with_sacks = conn.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE sacks_suffered IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    assert game_lines_with_sacks == 0
    assert james_row["games"] == 16
    assert james_row["sacks_suffered"] is None
    assert james_row["passing_yards"] == 0
    assert warner_row["sacks_suffered"] is None
    assert warner_row["passing_yards"] == 4044


def test_a_listed_starter_with_no_line_for_his_side_is_repaired_to_most_attempts(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, report = ingested
    game = conn.execute(
        "SELECT home_team_id, raw_json FROM games WHERE source_id = '2022_11_PHI_IND'"
    ).fetchone()
    assert json.loads(game["raw_json"])["home_qb_name"] == "Sam Ehlinger"

    starter = conn.execute(
        "SELECT player_id, source, position, sport FROM game_starters "
        "WHERE game_id = ? AND team_id = ?",
        (_game_id("2022_11_PHI_IND"), game["home_team_id"]),
    ).fetchone()
    assert (starter["player_id"], starter["source"], starter["position"], starter["sport"]) == (
        _player_id(conn, "Matt Ryan"),
        "derived_most_attempts",
        "QB",
        "nfl",
    )
    derived = {
        (d.game_id, d.side): (d.listed_player_id, d.attempts)
        for d in _season_report(report, 2022).derived_starters
    }
    assert derived[("2022_11_PHI_IND", "home")][1] == 32


def test_the_four_2022_repairs_are_the_contracts(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, report = ingested
    names = {
        r["id"]: r["display_name"]
        for r in conn.execute("SELECT id, display_name FROM players").fetchall()
    }
    repaired = sorted(
        (d.game_id, d.side, names[mint_surrogate_id("nfl_player", d.starter_player_id)], d.attempts)
        for d in _season_report(report, 2022).derived_starters
    )
    assert repaired == [
        ("2022_08_LV_NO", "home", "Andy Dalton", 30),
        ("2022_11_CAR_BAL", "away", "Baker Mayfield", 33),
        ("2022_11_PHI_IND", "home", "Matt Ryan", 32),
        ("2022_15_PIT_CAR", "away", "Mitchell Trubisky", 22),
    ]


def test_a_game_with_no_stat_lines_is_reported_and_keeps_its_listed_starters(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, report = ingested
    assert "1999_01_BAL_STL" in _season_report(report, 1999).games_without_stat_lines

    game = conn.execute(
        "SELECT id, home_team_id, away_team_id, raw_json FROM games "
        "WHERE source_id = '1999_01_BAL_STL'"
    ).fetchone()
    raw = json.loads(game["raw_json"])
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE game_id = ?", (game["id"],)
        ).fetchone()[0]
        == 0
    )
    starters = {
        r["team_id"]: (r["player_id"], r["source"])
        for r in conn.execute(
            "SELECT team_id, player_id, source FROM game_starters WHERE game_id = ?", (game["id"],)
        ).fetchall()
    }
    assert starters == {
        game["home_team_id"]: (
            mint_surrogate_id("nfl_player", raw["home_qb_id"]),
            "nflverse_schedule",
        ),
        game["away_team_id"]: (
            mint_surrogate_id("nfl_player", raw["away_qb_id"]),
            "nflverse_schedule",
        ),
    }
    # The name comes from players.csv, not the schedule: games.csv spells
    # this game's home QB "Kurt Waner".
    assert raw["home_qb_name"] == "Kurt Waner"
    listed = conn.execute(
        "SELECT display_name FROM players WHERE id = ?",
        (mint_surrogate_id("nfl_player", raw["home_qb_id"]),),
    ).fetchone()
    assert listed["display_name"] == "Kurt Warner"


def test_the_empty_team_row_is_reported_as_skipped(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, report = ingested
    skipped = [
        (s.reason, s.game_id, s.player_id, s.player_name)
        for s in _season_report(report, 1999).skipped
    ]
    assert ("empty_team", "1999_09_PHI_CAR", "00-0001471", "Steve Bono") in skipped
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE player_id = ? AND game_id = ?",
            (mint_surrogate_id("nfl_player", "00-0001471"), _game_id("1999_09_PHI_CAR")),
        ).fetchone()[0]
        == 0
    )


def test_the_report_counts_what_was_written(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, report = ingested
    for season in FIXTURE_SEASONS:
        s = _season_report(report, season)
        assert (
            s.stat_lines
            == conn.execute(
                "SELECT COUNT(*) FROM player_game_stats p JOIN games g ON g.id = p.game_id "
                "WHERE g.season = ?",
                (season,),
            ).fetchone()[0]
        )
        assert (
            s.season_rows
            == conn.execute(
                "SELECT COUNT(*) FROM player_season_stats WHERE season = ?", (season,)
            ).fetchone()[0]
        )
        assert (
            sum(s.starters_by_source.values())
            == conn.execute(
                "SELECT COUNT(*) FROM game_starters s JOIN games g ON g.id = s.game_id "
                "WHERE g.season = ?",
                (season,),
            ).fetchone()[0]
        )
    assert report.fetched_live is False


def test_players_carry_their_crosswalk_ids(
    ingested: tuple[sqlite3.Connection, PlayerIngestReport],
) -> None:
    conn, _ = ingested
    warner = _player_id(conn, "Kurt Warner")
    sources = dict(
        conn.execute(
            "SELECT source, source_id FROM player_source_ids WHERE player_id = ?", (warner,)
        ).fetchall()
    )
    assert sources["gsis"] == "00-0017200"
    assert warner == mint_surrogate_id("nfl_player", "00-0017200")
    assert sources["pfr"] == "WarnKu00"


# --- loud failures ----------------------------------------------------------


def test_ingesting_a_season_with_no_games_in_the_db_raises(
    nfl_regression_db: Path, tmp_path: Path, no_network: None
) -> None:
    conn = get_conn(nfl_regression_db)
    try:
        with pytest.raises(ValueError, match="2001"):
            ingest_players(conn, [2001], raw_dir=_sample_raw_dir(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0
    finally:
        conn.close()


def test_a_failing_season_writes_nothing(
    nfl_regression_db: Path, tmp_path: Path, no_network: None
) -> None:
    raw = _sample_raw_dir(tmp_path)
    path = raw / "nfl" / "stats_player_week_2004.csv"
    rows = _read_csv(path)
    rows[-1]["game_id"] = "2004_01_XXX_YYY"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    conn = get_conn(nfl_regression_db)
    try:
        with pytest.raises(ValueError, match="2004_01_XXX_YYY"):
            ingest_players(conn, [2004], raw_dir=raw)
        for table in WRITTEN_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        conn.close()


# --- idempotence and zero network -------------------------------------------


def _dump(conn: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        table: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall())
        for table in WRITTEN_TABLES
    }


def test_reingesting_a_season_leaves_every_written_table_identical(
    nfl_regression_db: Path, tmp_path: Path, no_network: None
) -> None:
    raw = _sample_raw_dir(tmp_path)
    conn = get_conn(nfl_regression_db)
    try:
        ingest_players(conn, [1999, 2022], raw_dir=raw)
        first = _dump(conn)
        ingest_players(conn, [1999], raw_dir=raw)
        second = _dump(conn)
        ingest_players(conn, [2022, 1999], raw_dir=raw)
        third = _dump(conn)
    finally:
        conn.close()

    assert all(first[t] for t in WRITTEN_TABLES)
    assert second == first
    assert third == first


def test_a_player_id_the_db_holds_for_another_gsis_id_raises_and_writes_nothing(
    nfl_regression_db: Path, tmp_path: Path, no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Swapping two players' minted ids keeps the season free of a collision
    # within itself, so only the check against the db's stored gsis ids can
    # stop Warner's id from silently becoming Manning's career.
    warner, manning = "00-0017200", "00-0010346"
    raw = _sample_raw_dir(tmp_path)
    conn = get_conn(nfl_regression_db)
    try:
        ingest_players(conn, [1999], raw_dir=raw)
        before = _dump(conn)
        real = player_normalize.player_id_for
        swap = {warner: manning, manning: warner}
        monkeypatch.setattr(
            player_normalize, "player_id_for", lambda gsis_id: real(swap.get(gsis_id, gsis_id))
        )

        with pytest.raises(ValueError, match="surrogate id collision"):
            ingest_players(conn, [1999], raw_dir=raw)
        after = _dump(conn)
    finally:
        conn.close()

    assert after == before


def test_the_ingest_makes_no_network_call_when_the_cache_is_present(
    nfl_regression_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("network call attempted")

    monkeypatch.setattr(nflverse_client, "_fetch_csv_live", _refuse_live_fetch)
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests.Session, "request", refuse)

    conn = get_conn(nfl_regression_db)
    try:
        report = ingest_players(conn, list(FIXTURE_SEASONS), raw_dir=_sample_raw_dir(tmp_path))
    finally:
        conn.close()
    assert report.fetched_live is False
    assert [s.season for s in report.seasons] == list(FIXTURE_SEASONS)


# --- the committed cache ----------------------------------------------------


def test_player_sample_rows_are_in_the_committed_cache() -> None:
    for path in sorted(PLAYER_SAMPLE_DIR.iterdir()):
        committed = RAW_DIR / "nfl" / path.name
        assert committed.is_file(), f"{committed} is missing from the committed cache"
        committed_rows = {tuple(r.items()) for r in _read_csv(committed)}
        sample_rows = _read_csv(path)
        assert sample_rows
        missing = [r for r in sample_rows if tuple(r.items()) not in committed_rows]
        assert missing == [], f"{path.name}: {len(missing)} rows not in the committed cache"


# Measured by the coordinator on the live files (brief for #289, rule 7/8).
COMMITTED_CACHE_EXPECTED = {
    1999: ({"nflverse_schedule": 518, "derived_most_attempts": 0}, ("1999_01_BAL_STL",)),
    2004: ({"nflverse_schedule": 534, "derived_most_attempts": 0}, ()),
    2013: ({"nflverse_schedule": 534, "derived_most_attempts": 0}, ()),
    2022: ({"nflverse_schedule": 564, "derived_most_attempts": 4}, ()),
}


def test_the_committed_cache_reproduces_the_contracts_season_counts(
    nfl_regression_db: Path, no_network: None
) -> None:
    conn = get_conn(nfl_regression_db)
    try:
        report = ingest_players(conn, list(FIXTURE_SEASONS), raw_dir=RAW_DIR)
    finally:
        conn.close()

    for season, (starters, no_lines) in COMMITTED_CACHE_EXPECTED.items():
        s = _season_report(report, season)
        assert s.starters_by_source == starters, season
        assert s.games_without_stat_lines == no_lines, season
        assert s.sides_without_starter == (), season


def test_main_ingests_from_the_committed_cache_and_prints_the_report(
    nfl_regression_db: Path, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--years", "1999", "--db-path", str(nfl_regression_db)]) == 0
    out = capsys.readouterr().out
    assert "1999" in out
    assert "1999_01_BAL_STL" in out
    assert "Steve Bono" in out


def test_main_rejects_years_outside_the_ingest_window(
    nfl_regression_db: Path, no_network: None
) -> None:
    assert main(["--years", "1990", "--db-path", str(nfl_regression_db)]) == 1


def test_main_returns_one_when_a_season_fails(nfl_regression_db: Path, no_network: None) -> None:
    assert main(["--years", "2001", "--db-path", str(nfl_regression_db)]) == 1
