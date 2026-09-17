"""Unit coverage for the nflverse player-stats normalize layer (issue #289):
the cache projection's row filter, player ids, unknown players, franchise
team resolution, REG/POST mapping and the loud failures.

Fixtures, all real rows cut once from nflverse's files, never synthetic:

* `tests/fixtures/raw_nfl_stats_player_week_unprojected_sample.csv`: four
  rows of `2024_08_IND_HOU` in the raw file's column names (the projected
  columns plus four it drops -- `player_name`, `position_group`,
  `receiving_air_yards` and `def_sacks`): Anthony Richardson (32 attempts),
  Josh Downs (rushing_yards 13 on 0 carries -- the row an attempts/carries
  filter wrongly drops), Robert Woods (receiving only, kept since #313
  widened the columns) and Denico Autry (all zero on offence, still
  dropped). Recut from the raw 2024 weekly file for #313.
* `tests/fixtures/raw_nfl_player_sample/nfl/`: projected-cache-shaped cuts
  of `stats_player_week_<year>.csv` and `players.csv`. See
  test_ingest_nflverse_players_integration.py's docstring for what each
  season's cut holds; it also checks every row is in the committed cache.
* Games come from the committed `tests/fixtures/nfl_regression.sqlite3`
  (1999/2004/2013/2022), or for 2001 from the committed `games.csv` cache
  through the existing `normalize_game`.
"""

from __future__ import annotations

import csv
import dataclasses
import sqlite3
from pathlib import Path

import pytest

from cfb_strength.config import RAW_DIR
from cfb_strength.contracts import PlayerStats
from cfb_strength.ingest.nflverse import client as nflverse_client
from cfb_strength.ingest.nflverse import player_normalize
from cfb_strength.ingest.nflverse.normalize import (
    build_team_lookup,
    mint_surrogate_id,
    normalize_game,
)
from cfb_strength.ingest.nflverse.player_normalize import (
    STAT_FIELDS,
    GameInfo,
    build_franchise_lookup,
    build_player_season,
    build_roster,
    game_info,
    has_any_stat,
    parse_stats,
    player_season_type,
    resolve_side,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
UNPROJECTED_SAMPLE = FIXTURES_DIR / "raw_nfl_stats_player_week_unprojected_sample.csv"
PLAYER_SAMPLE_DIR = FIXTURES_DIR / "raw_nfl_player_sample" / "nfl"
TEAMS_SAMPLE = FIXTURES_DIR / "raw_nfl_teams_sample.csv"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _unprojected() -> dict[str, dict[str, str]]:
    return {r["player_display_name"]: r for r in _read_csv(UNPROJECTED_SAMPLE)}


def _stat_rows(year: int) -> list[dict[str, str]]:
    return _read_csv(PLAYER_SAMPLE_DIR / f"stats_player_week_{year}.csv")


def _franchise() -> dict[str, str]:
    return build_franchise_lookup(_read_csv(TEAMS_SAMPLE))


def _roster() -> dict[str, object]:
    return dict(build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")))


def _games(conn: sqlite3.Connection, season: int) -> list[GameInfo]:
    rows = conn.execute(
        "SELECT id, source_id, season_type, home_team_id, away_team_id, home_points, "
        "away_points, raw_json FROM games WHERE sport = 'nfl' AND season = ? "
        "ORDER BY source_id",
        (season,),
    ).fetchall()
    return [game_info(dict(r)) for r in rows]


def _game(conn: sqlite3.Connection, source_id: str) -> GameInfo:
    season = int(source_id[:4])
    return next(g for g in _games(conn, season) if g.source_id == source_id)


# --- rule 1: the cache projection's row filter ------------------------------


def test_row_filter_keeps_a_rushing_yards_only_row_with_zero_carries() -> None:
    downs = _unprojected()["Josh Downs"]
    assert downs["carries"] == "0" and downs["rushing_yards"] == "13"

    assert has_any_stat(downs) is True


def test_row_filter_keeps_a_receiving_only_row_and_drops_an_all_zero_one() -> None:
    rows = _unprojected()

    assert has_any_stat(rows["Anthony Richardson"]) is True
    # Receiving became a PlayerStats column in #313, so a catch now keeps a
    # row that the ten passing/rushing columns dropped.
    assert rows["Robert Woods"]["receptions"] == "2"
    assert has_any_stat(rows["Robert Woods"]) is True
    # A defensive line with nothing on offence is still dropped: the def_*
    # columns are deliberately out of the contract (#316/#317).
    assert rows["Denico Autry"]["def_sacks"] == "0"
    assert has_any_stat(rows["Denico Autry"]) is False


def test_row_filter_treats_an_empty_cell_as_no_stat() -> None:
    row = {**_unprojected()["Denico Autry"], "passing_yards": ""}
    assert has_any_stat(row) is False
    assert has_any_stat({**row, "sack_yards_lost": "-7"}) is True


def test_stats_projection_keeps_exactly_the_documented_columns_and_rows() -> None:
    projected = nflverse_client.project_stats_player_week(_read_csv(UNPROJECTED_SAMPLE))

    assert [r["player_display_name"] for r in projected] == [
        "Anthony Richardson",
        "Josh Downs",
        "Robert Woods",
    ]
    assert tuple(projected[0]) == nflverse_client.STATS_PLAYER_WEEK_CACHE_COLUMNS
    # The raw file's other columns (the EPA, air-yards and def_* families)
    # are dropped, so nothing outside the contract reaches the cache.
    assert "def_sacks" not in projected[0] and "receiving_air_yards" not in projected[0]
    assert nflverse_client.STATS_PLAYER_WEEK_CACHE_COLUMNS == (
        "player_id",
        "player_display_name",
        "position",
        "season",
        "week",
        "season_type",
        "game_id",
        "team",
        "opponent_team",
        *STAT_FIELDS,
    )


def test_player_projection_keeps_only_the_documented_columns() -> None:
    assert nflverse_client.PLAYERS_CACHE_COLUMNS == (
        "gsis_id",
        "display_name",
        "position",
        "birth_date",
        "pfr_id",
        "espn_id",
    )


def test_stat_fields_are_the_player_stats_contract_in_order() -> None:
    assert STAT_FIELDS == tuple(f.name for f in dataclasses.fields(PlayerStats))


def test_client_fetches_once_writes_the_projection_and_then_reads_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    text = UNPROJECTED_SAMPLE.read_text()

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return text

    monkeypatch.setattr(nflverse_client, "_fetch_csv_live", fake_fetch)

    rows, live = nflverse_client.get_stats_player_week(2024, raw_dir=tmp_path)
    assert live is True
    assert calls == [nflverse_client.stats_player_week_url(2024)]
    cache = nflverse_client.stats_player_week_cache_path(2024, tmp_path)
    assert cache == tmp_path / "nfl" / "stats_player_week_2024.csv"
    assert _read_csv(cache) == rows
    assert len(rows) == 3

    again, live_again = nflverse_client.get_stats_player_week(2024, raw_dir=tmp_path)
    assert (again, live_again) == (rows, False)
    assert len(calls) == 1

    nflverse_client.get_stats_player_week(2024, raw_dir=tmp_path, force=True)
    assert len(calls) == 2


def test_client_refuses_a_stats_file_missing_a_projected_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = UNPROJECTED_SAMPLE.read_text().replace("sack_yards_lost", "sack_yards", 1)
    monkeypatch.setattr(nflverse_client, "_fetch_csv_live", lambda url: text)

    with pytest.raises(nflverse_client.NflverseClientError, match="sack_yards_lost"):
        nflverse_client.get_stats_player_week(2024, raw_dir=tmp_path)
    assert not nflverse_client.stats_player_week_cache_path(2024, tmp_path).exists()


def test_parse_stats_keeps_empty_as_none_never_zero() -> None:
    row = {**_unprojected()["Josh Downs"], "sacks_suffered": ""}
    stats = parse_stats(row)

    assert stats.rushing_yards == 13
    assert stats.carries == 0
    assert stats.sacks_suffered is None


def test_parse_stats_raises_naming_a_non_integer_column() -> None:
    row = {**_unprojected()["Josh Downs"], "passing_yards": "12.5"}
    with pytest.raises(ValueError, match="passing_yards"):
        parse_stats(row)


# --- rule 2: player ids -----------------------------------------------------


def test_player_ids_are_deterministic_in_the_nfl_player_namespace() -> None:
    a = mint_surrogate_id("nfl_player", "00-0010346")
    assert a == mint_surrogate_id("nfl_player", "00-0010346")
    assert 2_000_000_000 <= a < 2_500_000_000
    assert not 1_000_000_000 <= a < 2_000_000_000  # disjoint from nfl_team/nfl_game
    assert mint_surrogate_id("nfl_player", "00-0010346") != mint_surrogate_id(
        "nfl_player", "00-0019596"
    )


def test_two_gsis_ids_minting_one_player_id_in_a_season_raise(
    nfl_regression_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A collision would silently merge two careers into one player.
    rows = [r for r in _stat_rows(2022) if r["game_id"] == "2022_11_PHI_IND"]
    assert len({r["player_id"] for r in rows}) > 1
    monkeypatch.setattr(player_normalize, "player_id_for", lambda gsis_id: 2_000_000_001)

    with pytest.raises(ValueError, match="surrogate id collision: player id 2000000001"):
        build_player_season(
            2022,
            rows,
            _games(nfl_regression_conn, 2022),
            _franchise(),
            build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
        )


# --- REG/POST and rule 4 ----------------------------------------------------


def test_player_season_type_maps_reg_and_post() -> None:
    assert player_season_type("REG") == "regular"
    assert player_season_type("POST") == "postseason"
    with pytest.raises(ValueError, match="WC"):
        player_season_type("WC")


def test_a_stat_line_whose_season_type_disagrees_with_its_game_raises(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(2022) if r["game_id"] == "2022_11_PHI_IND"]
    bad = {**rows[0], "season_type": "POST"}

    with pytest.raises(ValueError, match=rf"2022_11_PHI_IND.*{bad['player_id']}"):
        build_player_season(
            2022,
            [bad, *rows[1:]],
            _games(nfl_regression_conn, 2022),
            _franchise(),
            build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
        )


def test_an_unmatched_game_id_raises_naming_game_and_player(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    row = {**_stat_rows(1999)[0], "game_id": "1999_01_XXX_YYY"}

    with pytest.raises(ValueError, match=rf"1999_01_XXX_YYY.*{row['player_id']}"):
        build_player_season(
            1999,
            [row],
            _games(nfl_regression_conn, 1999),
            _franchise(),
            build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
        )


# --- rule 5: team resolution ------------------------------------------------


def test_a_current_franchise_abbreviation_resolves_to_the_historical_side(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    oak_home = next(g for g in _games(nfl_regression_conn, 1999) if g.home_abbr == "OAK")
    oak_away = next(g for g in _games(nfl_regression_conn, 1999) if g.away_abbr == "OAK")

    assert resolve_side("LV", oak_home, _franchise()) == "home"
    assert resolve_side("LV", oak_away, _franchise()) == "away"
    assert oak_home.team_id("home") == mint_surrogate_id("nfl_team", "OAK")


def test_st_louis_and_san_diego_resolve_through_their_franchise_ids(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    stl = next(g for g in _games(nfl_regression_conn, 1999) if g.home_abbr == "STL")
    assert resolve_side("LA", stl, _franchise()) == "home"
    sd = next(g for g in _games(nfl_regression_conn, 2004) if "SD" in (g.home_abbr, g.away_abbr))
    side = "home" if sd.home_abbr == "SD" else "away"
    assert resolve_side("LAC", sd, _franchise()) == side


def test_an_unresolvable_non_empty_team_raises(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    game = _game(nfl_regression_conn, "1999_09_PHI_CAR")
    with pytest.raises(ValueError, match="KC"):
        resolve_side("KC", game, _franchise())
    with pytest.raises(ValueError, match="XYZ"):
        resolve_side("XYZ", game, _franchise())


def test_an_unresolvable_team_on_a_stat_line_raises_naming_its_ids(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    row = next(r for r in _stat_rows(1999) if r["game_id"] == "1999_09_PHI_CAR" and r["team"])
    bad = {**row, "team": "KC"}
    with pytest.raises(ValueError, match=rf"1999_09_PHI_CAR.*{row['player_id']}"):
        build_player_season(
            1999,
            [bad],
            _games(nfl_regression_conn, 1999),
            _franchise(),
            build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
        )


def test_an_empty_team_row_is_skipped_and_reported(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(1999) if r["game_id"] == "1999_09_PHI_CAR"]
    bono = next(r for r in rows if r["player_display_name"] == "Steve Bono")
    assert bono["team"] == ""

    build = build_player_season(
        1999,
        rows,
        _games(nfl_regression_conn, 1999),
        _franchise(),
        build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
    )

    bono_id = mint_surrogate_id("nfl_player", "00-0001471")
    assert all(line.player_id != bono_id for line in build.game_stats)
    assert [(s.reason, s.game_id, s.player_id, s.player_name) for s in build.report.skipped] == [
        ("empty_team", "1999_09_PHI_CAR", "00-0001471", "Steve Bono")
    ]
    assert build.report.stat_lines == len(rows) - 1


# --- rule 3: players missing from players.csv --------------------------------


def test_a_player_missing_from_players_csv_is_created_from_the_stat_row(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(2022) if r["game_id"] == "2022_11_PHI_IND"]
    ryan = next(r for r in rows if r["player_display_name"] == "Matt Ryan")
    roster_rows = [
        p for p in _read_csv(PLAYER_SAMPLE_DIR / "players.csv") if p["gsis_id"] != ryan["player_id"]
    ]

    build = build_player_season(
        2022, rows, _games(nfl_regression_conn, 2022), _franchise(), build_roster(roster_rows)
    )

    ryan_id = mint_surrogate_id("nfl_player", ryan["player_id"])
    player = next(p for p in build.players if p.id == ryan_id)
    assert (player.display_name, player.position, player.birth_date, player.sport) == (
        "Matt Ryan",
        "QB",
        None,
        "nfl",
    )
    assert [(s.source, s.source_id) for s in build.source_ids if s.player_id == ryan_id] == [
        ("gsis", ryan["player_id"])
    ]
    assert build.report.players_without_roster_entry == (ryan["player_id"],)


def test_a_player_in_players_csv_gets_gsis_pfr_and_espn_source_ids(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(2022) if r["game_id"] == "2022_11_PHI_IND"]
    ryan = next(r for r in rows if r["player_display_name"] == "Matt Ryan")
    roster_row = next(
        p for p in _read_csv(PLAYER_SAMPLE_DIR / "players.csv") if p["gsis_id"] == ryan["player_id"]
    )
    assert roster_row["pfr_id"] and roster_row["espn_id"]

    build = build_player_season(
        2022,
        rows,
        _games(nfl_regression_conn, 2022),
        _franchise(),
        build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
    )

    ryan_id = mint_surrogate_id("nfl_player", ryan["player_id"])
    player = next(p for p in build.players if p.id == ryan_id)
    assert player.birth_date == (roster_row["birth_date"] or None)
    assert sorted((s.source, s.source_id) for s in build.source_ids if s.player_id == ryan_id) == [
        ("espn", roster_row["espn_id"]),
        ("gsis", ryan["player_id"]),
        ("pfr", roster_row["pfr_id"]),
    ]
    assert build.report.players_without_roster_entry == ()


def test_a_player_is_written_only_when_a_stored_line_or_starter_references_them(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(2022) if r["game_id"] == "2022_11_PHI_IND"]
    build = build_player_season(
        2022,
        rows,
        _games(nfl_regression_conn, 2022),
        _franchise(),
        build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
    )

    referenced = {line.player_id for line in build.game_stats} | {
        s.player_id for s in build.starters
    }
    assert {p.id for p in build.players} == referenced
    assert len(build.players) < len(_read_csv(PLAYER_SAMPLE_DIR / "players.csv"))


# --- rows with no usable player identity (measured, see the return) -----------


def test_rows_with_no_player_id_are_skipped_and_reported() -> None:
    games_csv = _read_csv(RAW_DIR / "nfl" / "games.csv")
    lookup = build_team_lookup(_read_csv(TEAMS_SAMPLE))
    raw_game = next(g for g in games_csv if g["game_id"] == "2001_11_GB_DET")
    info = game_info(dataclasses.asdict(normalize_game(raw_game, lookup)))
    rows = _stat_rows(2001)
    team_rows = [r for r in rows if r["player_id"] == ""]
    assert len(team_rows) == 1

    build = build_player_season(
        2001, rows, [info], _franchise(), build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv"))
    )

    assert [(s.reason, s.game_id, s.player_id) for s in build.report.skipped] == [
        ("no_player_identity", "2001_11_GB_DET", "")
    ]
    assert build.report.stat_lines == len(rows) - 1


def test_an_unknown_player_with_no_name_anywhere_is_skipped_and_reported(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    rows = [r for r in _stat_rows(1999) if r["player_id"] == "00-0005532"]
    assert rows and all(r["player_display_name"] == "" for r in rows)

    build = build_player_season(
        1999,
        rows,
        _games(nfl_regression_conn, 1999),
        _franchise(),
        build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
    )

    assert build.game_stats == ()
    assert [(s.reason, s.game_id, s.player_id) for s in build.report.skipped] == [
        ("no_player_identity", "1999_15_NO_BAL", "00-0005532")
    ]
    assert mint_surrogate_id("nfl_player", "00-0005532") not in {p.id for p in build.players}


# --- issue #313: 34 columns, the sign convention and the MAX fields ---------


def _season_stats(
    conn: sqlite3.Connection, season: int, gsis_id: str, season_type: str = "regular"
) -> PlayerStats:
    build = build_player_season(
        season,
        _stat_rows(season),
        _games(conn, season),
        _franchise(),
        build_roster(_read_csv(PLAYER_SAMPLE_DIR / "players.csv")),
    )
    row = next(
        r
        for r in build.season_stats
        if r.player_id == mint_surrogate_id("nfl_player", gsis_id) and r.season_type == season_type
    )
    return row.stats


def _game_values(season: int, gsis_id: str, column: str, season_type: str = "REG") -> list[str]:
    """One player's cells for `column`, in week order, from the season cut."""
    rows = [
        r
        for r in _stat_rows(season)
        if r["player_id"] == gsis_id and r["season_type"] == season_type
    ]
    return [r[column] for r in sorted(rows, key=lambda r: int(r["week"]))]


def test_a_season_takes_the_max_of_fg_long_not_the_sum(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    # Mike Vanderjagt, 1999 Indianapolis: 16 regular-season lines, longest
    # 53 in week 12 -- not his last game (27), so "max" and "last" can't be
    # confused, and not the sum (578), which is no field goal anyone kicked.
    cells = _game_values(1999, "00-0016830", "fg_long")
    longs = [int(v) for v in cells if v]
    assert len(cells) == 16 and len(longs) == 15
    assert max(longs) == 53 and longs[-1] == 27 and cells.index("53") == 11
    assert sum(longs) == 578

    stats = _season_stats(nfl_regression_conn, 1999, "00-0016830")

    assert stats.fg_long == 53
    assert stats.fg_att == sum(int(v) for v in _game_values(1999, "00-0016830", "fg_att"))


def test_a_season_takes_the_max_of_pt_long_not_the_sum(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    # Hunter Smith, 1999 Indianapolis: 16 games, longest 61 in week 14.
    longs = [int(v) for v in _game_values(1999, "00-0015194", "pt_long")]
    assert len(longs) == 16
    assert max(longs) == 61 and longs[-1] == 49 and longs.index(61) == 13
    assert sum(longs) == 840

    stats = _season_stats(nfl_regression_conn, 1999, "00-0015194")

    assert stats.pt_long == 61
    assert stats.pt_att == sum(int(v) for v in _game_values(1999, "00-0015194", "pt_att"))


def test_a_max_field_present_on_one_game_row_only_is_that_row(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    # Jeff Wilkins kicked for the 1999 Rams and punted once, in week 7: his
    # season pt_long is that one punt, and the 14 empty cells are skipped.
    # In the postseason he never punted, so that row's pt_long stays None.
    punts = _game_values(1999, "00-0017693", "pt_long")
    assert [v for v in punts if v] == ["34"] and len(punts) == 15
    assert set(_game_values(1999, "00-0017693", "pt_long", "POST")) == {""}

    stats = _season_stats(nfl_regression_conn, 1999, "00-0017693")
    postseason = _season_stats(nfl_regression_conn, 1999, "00-0017693", "postseason")

    assert stats.pt_long == 34
    assert stats.fg_long == 49
    assert postseason.pt_long is None
    assert postseason.fg_long == 29


def test_a_negative_sack_yards_cell_parses_positive() -> None:
    row = next(
        r for r in _stat_rows(1999) if r["sack_yards_lost"] and int(r["sack_yards_lost"]) < 0
    )
    assert row["sack_yards_lost"].startswith("-")
    stats = parse_stats(row)

    assert stats.sack_yards_lost == -int(row["sack_yards_lost"])
    assert stats.sack_yards_lost is not None and stats.sack_yards_lost > 0
    # Nothing else is flipped: net yardage keeps the source's sign.
    assert stats.passing_yards == int(row["passing_yards"])


def test_a_season_sack_yards_lost_is_the_positive_sum_of_its_games(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    # Kurt Warner, 1999 St. Louis: nflverse publishes -176 across 15 games.
    cells = [int(v) for v in _game_values(1999, "00-0017200", "sack_yards_lost")]
    assert sum(cells) == -176 and min(cells) < 0

    stats = _season_stats(nfl_regression_conn, 1999, "00-0017200")

    assert stats.sack_yards_lost == 176
    assert stats.sacks_suffered == 26


def test_a_column_empty_on_every_game_row_stays_none_while_an_all_zero_one_stays_zero(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    # Warner never kicked: fg_long is empty on all 15 lines (None, not 0),
    # while fg_att is a real 0 on all 15.
    assert set(_game_values(1999, "00-0017200", "fg_long")) == {""}
    assert set(_game_values(1999, "00-0017200", "fg_att")) == {"0"}

    stats = _season_stats(nfl_regression_conn, 1999, "00-0017200")

    assert stats.fg_long is None
    assert stats.fg_att == 0


def test_every_cached_season_publishes_all_thirty_four_stat_columns() -> None:
    # A season nflverse publishes differently must fail here, naming the
    # column, not at a random KeyError deep in _parse_stat.
    missing = {}
    for year in range(1999, 2026):
        path = nflverse_client.stats_player_week_cache_path(year, RAW_DIR)
        assert path.is_file(), f"{path} is missing from the committed cache"
        with path.open(newline="") as f:
            header = next(csv.reader(f))
        absent = [name for name in STAT_FIELDS if name not in header]
        if absent:
            missing[year] = absent

    assert missing == {}
    assert len(STAT_FIELDS) == 34


def test_parse_stats_raises_on_a_row_missing_a_stat_column() -> None:
    # The parse must not tolerate a missing column (no `row.get(name, "")`):
    # a season nflverse stopped publishing one of the 34 would otherwise
    # read as an era that didn't track it.
    row = {k: v for k, v in _stat_rows(1999)[0].items() if k != "receiving_first_downs"}

    with pytest.raises(KeyError, match="receiving_first_downs"):
        parse_stats(row)


def test_the_committed_cache_reproduces_bradys_2007_sack_totals() -> None:
    # Tom Brady's 2007 regular season: 21 sacks for 128 yards, the way an
    # official stat line reads it (#298).
    rows = _read_csv(RAW_DIR / "nfl" / "stats_player_week_2007.csv")
    brady = [r for r in rows if r["player_id"] == "00-0019596" and r["season_type"] == "REG"]
    assert len(brady) == 16

    stats = [parse_stats(r) for r in brady]

    assert sum(s.sacks_suffered or 0 for s in stats) == 21
    assert sum(s.sack_yards_lost or 0 for s in stats) == 128
    assert sum(int(r["sack_yards_lost"]) for r in brady) == -128


def test_the_sixty_yard_bucket_is_a_real_zero_in_1999_and_non_zero_in_2023() -> None:
    made = {}
    for year in (1999, 2023):
        rows = _read_csv(RAW_DIR / "nfl" / f"stats_player_week_{year}.csv")
        stats = [parse_stats(r) for r in rows]
        assert all(s.fg_made_60_ is not None for s in stats), year
        made[year] = sum(s.fg_made_60_ or 0 for s in stats)

    assert made[1999] == 0
    assert made[2023] > 0
