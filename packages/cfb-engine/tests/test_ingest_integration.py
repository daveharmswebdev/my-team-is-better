"""Integration coverage for `cfb_strength.ingest`: normalize real cached raw
CFBD JSON game records end-to-end into `GameRow`/`TeamRow` contract objects
and upserted `games`/`teams`/`team_season` rows.

Fixture: `tests/fixtures/raw_games_sample.json`, three real records extracted
once from the committed `data/raw/2005_regular.json` / `2005_postseason.json`
cache (never re-derived synthetically, per this module's brief -- schedule
shape and classification fields matter for ingest correctness):

  1. Cincinnati (home, fbs) vs Eastern Michigan (away, fbs) -- an ordinary
     completed FBS-vs-FBS game.
  2. Towson (home, fcs) vs Morgan State (away, fcs) -- both sides non-FBS,
     to check classification/team-row handling off the FBS happy path.
  3. Texas (home, fbs) vs USC (away, fbs), the 2006 Rose Bowl -- neutral
     site, postseason, the same real game the golden-dataset regression
     test in test_golden_dataset_regressions.py checks evidence for.

These tests never touch the live `data/cfb.sqlite3` and never call the live
CFBD API (the raw JSON here is a committed fixture, not a live cache read).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cfb_strength.contracts import GameRow, TeamRow
from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.ingest_season import _write_games, _write_teams
from cfb_strength.ingest.normalize import normalize_game, team_rows_from_game

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "raw_games_sample.json"


def _load_raw_records() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


def test_fixture_has_the_three_expected_real_games() -> None:
    records = _load_raw_records()
    assert len(records) == 3
    ids = {r["id"] for r in records}
    assert ids == {252442132, 252440119, 260040030}


def test_normalize_game_produces_correct_gamerow_for_ordinary_fbs_game() -> None:
    records = _load_raw_records()
    raw = next(r for r in records if r["id"] == 252442132)

    row = normalize_game(raw, season=2005, season_type="regular")

    assert isinstance(row, GameRow)
    assert row.id == 252442132
    assert row.season == 2005
    assert row.week == 1
    assert row.season_type == "regular"
    assert row.home_team == "Cincinnati"
    assert row.away_team == "Eastern Michigan"
    assert row.home_points == 28
    assert row.away_points == 26
    assert row.home_classification == "fbs"
    assert row.away_classification == "fbs"
    assert row.neutral_site is False
    assert row.completed is True
    # raw_json round-trips the full original record (sorted-key JSON dump).
    assert json.loads(row.raw_json)["id"] == 252442132


def test_normalize_game_handles_neutral_site_postseason_rose_bowl() -> None:
    records = _load_raw_records()
    raw = next(r for r in records if r["id"] == 260040030)

    row = normalize_game(raw, season=2005, season_type="postseason")

    assert row.home_team == "Texas"
    assert row.away_team == "USC"
    assert row.home_points == 41
    assert row.away_points == 38
    assert row.neutral_site is True
    assert row.season_type == "postseason"
    assert row.venue == "Rose Bowl"


def test_normalize_game_carries_non_fbs_classification() -> None:
    records = _load_raw_records()
    raw = next(r for r in records if r["id"] == 252440119)

    row = normalize_game(raw, season=2005, season_type="regular")

    assert row.home_classification == "fcs"
    assert row.away_classification == "fcs"


def test_team_rows_from_game_derives_both_sides() -> None:
    records = _load_raw_records()
    raw = next(r for r in records if r["id"] == 260040030)

    rows = team_rows_from_game(raw)

    assert len(rows) == 2
    by_school = {r.school: r for r in rows}
    assert set(by_school) == {"Texas", "USC"}
    assert isinstance(by_school["Texas"], TeamRow)
    assert by_school["Texas"].classification == "fbs"
    assert by_school["Texas"].conference == "Big 12"
    assert by_school["USC"].conference == "Pac-10"


def test_full_normalize_and_write_pipeline_upserts_into_empty_db(
    empty_schema_db: Path,
) -> None:
    """End-to-end: raw JSON -> normalize -> write into a real (empty-schema)
    sqlite db, then confirm the rows are queryable exactly as the rest of
    the pipeline (ratings/evidence) expects them."""
    records = _load_raw_records()
    conn: sqlite3.Connection = get_conn(empty_schema_db)

    game_rows = [normalize_game(r, season=2005, season_type=r["seasonType"]) for r in records]
    team_rows: dict[int, TeamRow] = {}
    for r in records:
        for tr in team_rows_from_game(r):
            team_rows[tr.id] = tr

    _write_teams(conn, team_rows, 2005)
    _write_games(conn, game_rows)
    conn.commit()

    game_count = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    team_count = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
    assert game_count == 3
    assert team_count == len(team_rows)

    texas_usc = conn.execute(
        "SELECT home_team, away_team, home_points, away_points FROM games WHERE id = ?",
        (260040030,),
    ).fetchone()
    assert texas_usc["home_team"] == "Texas"
    assert texas_usc["away_team"] == "USC"
    assert texas_usc["home_points"] == 41
    assert texas_usc["away_points"] == 38

    # Re-running the write (as a real re-ingest would) upserts rather than
    # duplicates.
    _write_teams(conn, team_rows, 2005)
    _write_games(conn, game_rows)
    conn.commit()
    game_count_after = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    assert game_count_after == 3

    conn.close()
