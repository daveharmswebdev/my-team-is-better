"""Issue #300: the curated list of FBS conference title games.

CFBD files conference title games as season_type 'regular' from 2001 on (in
1998-2000 they sit in the postseason payload), and its `notes` names them
only from 2022. Nothing in the record says which games are title games, and
a "last same-conference game" rule is wrong in both directions (Army-Navy as
the 2024 American title game, rescheduled games, Big East games, 2020's
title games). So the flag is data, not a rule:
`data/raw/cfbd_conference_championships.json` lists each title game by CFBD
id, and `ingest_one` sets `games.conference_championship = 1` for exactly
those ids, leaving `season_type` as CFBD reports it.

These tests use the real committed cache and the real list (no synthetic
game records). The cited games are

  * 253370251, 2005 Big 12 Championship, Texas at Colorado (regular, notes
    null), and 253290245, Texas at Texas A&M, the Big 12 week-13 game the
    week before it.
  * 400955153, 2017 SEC Championship, Georgia at Auburn (regular).
  * 62359, 1998 Big 12 Championship, Kansas State at Texas A&M (postseason).

No test here calls the live CFBD API: the cache read is replaced with a
read of the committed `data/raw/` file.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.conference_championships import (
    CONFERENCE_CHAMPIONSHIPS_PATH,
    ConferenceChampionship,
    ConferenceChampionshipError,
    load_conference_championships,
)
from cfb_strength.ingest.fcs_playoff_games import load_fcs_playoff_games
from cfb_strength.ingest.ingest_season import ingest_one
from cfb_strength.ingest.nflverse import ingest_season as nfl_ingest
from cfb_strength.ingest.nflverse.normalize import build_team_lookup
from cfb_strength.ingest.normalize import dedupe_game_records

ENGINE_DIR = Path(__file__).resolve().parents[1]
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
LOGGER_NAME = "cfb_strength.ingest.conference_championships"

# Which seasons each FBS conference held a title game, by CFBD conference
# name. One game per cell, 180 in total.
TITLE_GAME_SEASONS: dict[str, list[int]] = {
    "SEC": list(range(1998, 2026)),
    "Big 12": [*range(1998, 2011), *range(2017, 2026)],
    "Mid-American": list(range(1998, 2026)),
    "Western Athletic": [1998],
    "ACC": list(range(2005, 2026)),
    "Conference USA": list(range(2005, 2026)),
    "Big Ten": list(range(2011, 2026)),
    "Pac-12": list(range(2011, 2024)),
    "Mountain West": list(range(2013, 2026)),
    "American Athletic": list(range(2015, 2026)),
    "Sun Belt": [2018, 2019, *range(2021, 2026)],
}

# #343's comment on #300: SEC / Big 12 / ACC / MAC title games, 2001-2007.
ISSUE_343_TITLE_GAME_IDS = {
    213420099, 223410008, 233400061, 243390002, 253370099, 263360057, 273350099,
    213350251, 223410038, 233400201, 243390038, 253370251, 263360201, 273350142,
    253370259, 263360059, 273350103,
    243370193, 253352459, 263340195, 273352117,
}  # fmt: skip

# 2001 Auburn at LSU, Dec 1: a rescheduled regular-season game, not a title game.
NOT_A_TITLE_GAME = 213350099


def _cached_games(year: int, season_type: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(
        (COMMITTED_RAW_DIR / f"{year}_{season_type}.json").read_text()
    )
    return records


@pytest.fixture
def committed_cache_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point `ingest_one`'s cache read at the committed `data/raw/` file,
    whatever `CFB_DATA_DIR` says, and never reach the network."""

    def _fake_get_games(
        year: int, season_type: str, *, force: bool = False
    ) -> tuple[list[dict[str, Any]], bool]:
        return _cached_games(year, season_type), False

    monkeypatch.setattr("cfb_strength.ingest.ingest_season.get_games", _fake_get_games)


def _ingest(
    db_path: Path,
    year: int,
    season_type: str = "regular",
    *,
    championships: tuple[ConferenceChampionship, ...] | None = None,
) -> sqlite3.Connection:
    conn = get_conn(db_path)
    ingest_one(conn, year, season_type, conference_championships=championships)
    return conn


def _game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT conference_championship, season_type, raw_json FROM games WHERE id = ?",
        (game_id,),
    ).fetchone()
    assert row is not None, f"game {game_id} was not written"
    return row


def _entry(game_id: int) -> ConferenceChampionship:
    return next(c for c in load_conference_championships() if c.game_id == game_id)


# ---------------------------------------------------------------------------
# the cited games, through the real CFBD ingest path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "season_type", "game_id"),
    [
        (2005, "regular", 253370251),
        (2017, "regular", 400955153),
        (1998, "postseason", 62359),
    ],
)
def test_listed_title_games_are_flagged_and_keep_cfbds_season_type(
    empty_schema_db: Path, committed_cache_only: None, year: int, season_type: str, game_id: int
) -> None:
    conn = _ingest(empty_schema_db, year, season_type)

    row = _game(conn, game_id)
    assert row["conference_championship"] == 1
    assert row["season_type"] == season_type
    assert json.loads(row["raw_json"])["seasonType"] == season_type


def test_the_week_13_big_12_game_before_the_2005_title_game_is_not_flagged(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    conn = _ingest(empty_schema_db, 2005)

    row = _game(conn, 253290245)
    assert row["conference_championship"] == 0
    assert row["season_type"] == "regular"


def test_exactly_the_listed_games_of_a_batch_are_flagged(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    expected = {
        c.game_id
        for c in load_conference_championships()
        if (c.season, c.season_type) == (2005, "regular")
    }
    assert len(expected) == 5
    conn = _ingest(empty_schema_db, 2005)

    flagged = {
        r["id"] for r in conn.execute("SELECT id FROM games WHERE conference_championship = 1")
    }
    assert flagged == expected
    # The title-game flag never changes season_type. The only games of the
    # batch stored as postseason are the listed FCS playoff games (#379).
    fcs_playoff = {
        g.game_id
        for g in load_fcs_playoff_games()
        if (g.season, g.season_type) == (2005, "regular")
    }
    relabelled = {
        r["id"] for r in conn.execute("SELECT id FROM games WHERE season_type != 'regular'")
    }
    assert relabelled == fcs_playoff
    assert relabelled.isdisjoint(flagged)


def test_the_rescheduled_2001_auburn_lsu_game_is_not_flagged(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    conn = _ingest(empty_schema_db, 2001)

    assert _game(conn, NOT_A_TITLE_GAME)["conference_championship"] == 0
    assert _game(conn, 213420099)["conference_championship"] == 1


def test_one_info_line_per_applied_flag(
    empty_schema_db: Path, committed_cache_only: None, caplog: pytest.LogCaptureFixture
) -> None:
    expected_ids = {
        c.game_id
        for c in load_conference_championships()
        if (c.season, c.season_type) == (2005, "regular")
    }

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _ingest(empty_schema_db, 2005)

    lines = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert all(r.levelno == logging.INFO for r in lines)
    assert len(lines) == len(expected_ids)
    assert {
        next(i for i in expected_ids if str(i) in r.getMessage()) for r in lines
    } == expected_ids
    big12 = next(r.getMessage() for r in lines if "253370251" in r.getMessage())
    assert "Big 12" in big12
    assert "Wikipedia: 2005 Big 12 Championship Game" in big12


def test_a_season_with_no_listed_games_in_the_batch_flags_nothing(
    empty_schema_db: Path, committed_cache_only: None, caplog: pytest.LogCaptureFixture
) -> None:
    # From 2001 every title game is in the regular payload.
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        conn = _ingest(empty_schema_db, 2005, "postseason")

    assert [r for r in caplog.records if r.name == LOGGER_NAME] == []
    assert conn.execute("SELECT SUM(conference_championship) FROM games").fetchone()[0] == 0


def test_every_nfl_row_is_not_a_conference_championship(empty_schema_db: Path) -> None:
    # The AFC/NFC Championship games in the sample stay 0: the flag is CFB's.
    with (FIXTURES_DIR / "raw_nfl_games_sample.csv").open(newline="") as f:
        games_raw = list(csv.DictReader(f))
    with (FIXTURES_DIR / "raw_nfl_teams_sample.csv").open(newline="") as f:
        team_lookup = build_team_lookup(list(csv.DictReader(f)))
    conn = get_conn(empty_schema_db)
    for season_type in ("regular", "postseason"):
        nfl_ingest.ingest_one(conn, 2023, season_type, games_raw, team_lookup)

    rows = conn.execute("SELECT conference_championship FROM games WHERE sport = 'nfl'").fetchall()
    assert len(rows) == 5
    assert {r["conference_championship"] for r in rows} == {0}


def test_every_nfl_row_in_the_regression_fixture_is_not_a_conference_championship(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    flagged = nfl_regression_conn.execute(
        "SELECT COUNT(*) FROM games WHERE sport = 'nfl' AND conference_championship != 0"
    ).fetchone()[0]
    assert flagged == 0


def test_the_cfb_regression_fixture_flags_exactly_the_listed_games(
    regression_conn: sqlite3.Connection,
) -> None:
    seasons = {
        r[0] for r in regression_conn.execute("SELECT DISTINCT season FROM games WHERE sport='cfb'")
    }
    expected = {c.game_id for c in load_conference_championships() if c.season in seasons}
    flagged = {
        r[0]
        for r in regression_conn.execute("SELECT id FROM games WHERE conference_championship = 1")
    }
    assert flagged == expected


# ---------------------------------------------------------------------------
# a wrong or stale entry is loud, never a silent skip
# ---------------------------------------------------------------------------


def test_a_listed_id_missing_from_its_seasons_payload_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    ghost = dataclasses.replace(_entry(253370251), game_id=999999999)

    with pytest.raises(ConferenceChampionshipError, match="999999999"):
        _ingest(empty_schema_db, 2005, championships=(ghost,))


def test_an_entry_whose_teams_dont_match_its_record_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    entry = _entry(253370251)
    swapped = dataclasses.replace(entry, home_team=entry.away_team, away_team=entry.home_team)

    with pytest.raises(ConferenceChampionshipError, match="253370251"):
        _ingest(empty_schema_db, 2005, championships=(swapped,))


def test_an_entry_whose_season_doesnt_match_its_record_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    # 253370251 is in the 2005 payload, but the entry claims 2006.
    wrong_season = dataclasses.replace(_entry(253370251), season=2006)

    with pytest.raises(ConferenceChampionshipError, match="253370251"):
        _ingest(empty_schema_db, 2005, championships=(wrong_season,))


def test_an_entry_whose_season_type_doesnt_match_its_record_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    # 62359 is in the 1998 postseason payload, but the entry claims regular.
    wrong_type = dataclasses.replace(_entry(62359), season_type="regular")

    with pytest.raises(ConferenceChampionshipError, match="62359"):
        _ingest(empty_schema_db, 1998, "postseason", championships=(wrong_type,))


def test_a_failed_entry_writes_nothing_for_the_batch(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    ghost = dataclasses.replace(_entry(253370251), game_id=999999999)

    with pytest.raises(ConferenceChampionshipError):
        _ingest(empty_schema_db, 2005, championships=(ghost,))
    conn = get_conn(empty_schema_db)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def _write_file(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"description": "test", "championships": entries}))
    return path


def _committed_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(CONFERENCE_CHAMPIONSHIPS_PATH.read_text())[
        "championships"
    ]
    return entries


def test_a_duplicate_id_in_the_file_raises(tmp_path: Path) -> None:
    entries = _committed_entries()
    duplicated = [*entries, dict(entries[0])]

    with pytest.raises(ConferenceChampionshipError, match=str(entries[0]["id"])):
        load_conference_championships(_write_file(tmp_path / "c.json", duplicated))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", ""),
        ("conference", ""),
        ("home_team", None),
        ("season_type", "bowl"),
        ("season", "2005"),
        ("id", True),
    ],
)
def test_an_entry_with_a_bad_field_raises(tmp_path: Path, field: str, value: object) -> None:
    entries = _committed_entries()
    entries[0] = {**entries[0], field: value}

    with pytest.raises(ConferenceChampionshipError, match=field):
        load_conference_championships(_write_file(tmp_path / "c.json", entries))


def test_an_entry_missing_a_field_raises(tmp_path: Path) -> None:
    entries = _committed_entries()
    entries[0] = {k: v for k, v in entries[0].items() if k != "source"}

    with pytest.raises(ConferenceChampionshipError, match="source"):
        load_conference_championships(_write_file(tmp_path / "c.json", entries))


def test_an_entry_with_an_unknown_field_raises(tmp_path: Path) -> None:
    entries = _committed_entries()
    entries[0] = {**entries[0], "week": 14}

    with pytest.raises(ConferenceChampionshipError, match="week"):
        load_conference_championships(_write_file(tmp_path / "c.json", entries))


def test_a_file_without_a_championships_list_raises(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"overrides": []}))

    with pytest.raises(ConferenceChampionshipError, match="championships"):
        load_conference_championships(path)


# ---------------------------------------------------------------------------
# the real committed list against the real committed cache
# ---------------------------------------------------------------------------


def test_the_committed_list_covers_every_conference_season_once() -> None:
    entries = load_conference_championships()
    assert CONFERENCE_CHAMPIONSHIPS_PATH == COMMITTED_RAW_DIR / "cfbd_conference_championships.json"
    assert len(entries) == 180
    assert len({c.game_id for c in entries}) == 180

    cells = Counter((c.conference, c.season) for c in entries)
    expected_cells = {(conf, y) for conf, years in TITLE_GAME_SEASONS.items() for y in years}
    assert set(cells) == expected_cells
    assert set(cells.values()) == {1}

    assert Counter(c.conference for c in entries) == {
        "SEC": 28,
        "Big 12": 22,
        "Mid-American": 28,
        "Western Athletic": 1,
        "ACC": 21,
        "Conference USA": 21,
        "Big Ten": 15,
        "Pac-12": 13,
        "Mountain West": 13,
        "American Athletic": 11,
        "Sun Belt": 7,
    }
    per_season = Counter(c.season for c in entries)
    expected_per_season = {
        1998: 4,
        **dict.fromkeys(range(1999, 2005), 3),
        **dict.fromkeys(range(2005, 2011), 5),
        2011: 6,
        2012: 6,
        2013: 7,
        2014: 7,
        2015: 8,
        2016: 8,
        2017: 9,
        2018: 10,
        2019: 10,
        2020: 9,
        **dict.fromkeys(range(2021, 2024), 10),
        2024: 9,
        2025: 9,
    }
    assert dict(per_season) == expected_per_season


def test_every_committed_entry_matches_its_cached_cfbd_record() -> None:
    payloads: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for c in load_conference_championships():
        for season_type in ("regular", "postseason"):
            key = (c.season, season_type)
            if key not in payloads:
                payloads[key] = dedupe_game_records(_cached_games(c.season, season_type))
        season_records = [
            (season_type, g)
            for season_type in ("regular", "postseason")
            for g in payloads[(c.season, season_type)]
            if g["id"] == c.game_id
        ]
        assert len(season_records) == 1, f"{c.game_id}: {len(season_records)} records"
        season_type, record = season_records[0]
        assert season_type == c.season_type, c.game_id
        assert record["seasonType"] == c.season_type, c.game_id
        assert record["season"] == c.season, c.game_id
        assert (record["homeTeam"], record["awayTeam"]) == (c.home_team, c.away_team), c.game_id
        assert record["homeConference"] == record["awayConference"] == c.conference, c.game_id
        assert record["homeClassification"] == record["awayClassification"] == "fbs", c.game_id
        assert c.source.startswith(f"Wikipedia: {c.season} "), c.game_id


def test_title_games_sit_in_the_postseason_payload_only_in_1998_2000() -> None:
    for c in load_conference_championships():
        expected = "postseason" if c.season <= 2000 else "regular"
        assert c.season_type == expected, c.game_id


def test_the_issue_343_title_games_are_listed_and_the_rescheduled_game_is_not() -> None:
    listed = {c.game_id for c in load_conference_championships()}
    assert ISSUE_343_TITLE_GAME_IDS <= listed
    assert NOT_A_TITLE_GAME not in listed


def test_the_list_agrees_with_cfbds_championship_notes_2022_2025() -> None:
    listed = {c.game_id for c in load_conference_championships()}
    noted = {
        g["id"]
        for year in range(2022, 2026)
        for g in dedupe_game_records(_cached_games(year, "regular"))
        if g.get("homeClassification") == "fbs"
        and g.get("awayClassification") == "fbs"
        and g["homeConference"] == g["awayConference"]
        and "Championship" in (g.get("notes") or "")
    }
    assert len(noted) == 38
    assert noted <= listed
    assert {c.game_id for c in load_conference_championships() if c.season >= 2022} == noted
