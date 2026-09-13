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

A second fixture, `tests/fixtures/raw_games_duplicate_records_sample.json`
(issue #125), holds nine real records extracted verbatim, in cache order,
from `data/raw/{2004,2008,2025}_regular.json`. CFBD's `/games` payload lists
some real games twice under two different game ids:

  * 2004: `63840` / `243322226`, FAU 49 - Edward Waters 15. This is the pair
    whose away team ids differ (`1000899` vs `2206`), and it is the only
    source of Edward Waters' second `teams` row (#91).
  * 2004: `63829` / `242830326`, Texas State 13 - FAU 20, an ordinary pair.
  * 2004: `243322229`, FIU 40 - Florida A&M 23. A genuinely distinct game on
    the same date as the Edward Waters pair, kept as a negative control.
  * 2008: `282430099` / `400361387`, LSU 41 - App State 13.
  * 2025: `401833370` / `401806686`, Augsburg 43 - Hamline 3.

These tests never touch the live `data/cfb.sqlite3` and never call the live
CFBD API (the raw JSON here is a committed fixture, not a live cache read).
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.contracts import GameRow, TeamRow
from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.ingest_season import _write_games, _write_teams, ingest_one
from cfb_strength.ingest.normalize import normalize_game, team_rows_from_game

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "raw_games_sample.json"
DUPLICATES_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "raw_games_duplicate_records_sample.json"
)


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


# ---------------------------------------------------------------------------
# issue #125: CFBD lists some real games twice under two game ids
# ---------------------------------------------------------------------------


def _duplicate_records(season: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(DUPLICATES_FIXTURE_PATH.read_text())
    return [r for r in records if r["season"] == season]


def _ingest_records(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    season: int,
    records: list[dict[str, Any]],
) -> sqlite3.Connection:
    """Run the real `ingest_one` for one regular-season batch, with the
    cache read swapped for `records` so no test depends on `data/raw/`."""

    def _fake_get_games(
        year: int, season_type: str, *, force: bool = False
    ) -> tuple[list[dict[str, Any]], bool]:
        assert (year, season_type) == (season, "regular")
        return records, False

    monkeypatch.setattr("cfb_strength.ingest.ingest_season.get_games", _fake_get_games)
    conn = get_conn(db_path)
    ingest_one(conn, season, "regular")
    return conn


def _game_ids(conn: sqlite3.Connection, home: str, away: str) -> list[int]:
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM games WHERE home_team = ? AND away_team = ? ORDER BY id",
            (home, away),
        )
    ]


def test_duplicate_fixture_pairs_really_share_the_matching_key() -> None:
    """Guards the fixture itself: each pair agrees on season, start *date*,
    both team names and both scores, and differs in game id. Every 2004 pair
    also differs in start *time*, so matching needs the date part only."""
    by_id = {r["id"]: r for s in (2004, 2008, 2025) for r in _duplicate_records(s)}

    def key(r: dict[str, Any]) -> tuple[object, ...]:
        return (
            r["season"],
            r["startDate"][:10],
            r["homeTeam"],
            r["awayTeam"],
            r["homePoints"],
            r["awayPoints"],
        )

    for low, high in ((63840, 243322226), (63829, 242830326), (282430099, 400361387),
                      (401806686, 401833370)):
        assert key(by_id[low]) == key(by_id[high])
    assert by_id[63840]["startDate"] != by_id[243322226]["startDate"]
    assert (by_id[63840]["awayId"], by_id[243322226]["awayId"]) == (1000899, 2206)


def test_ingest_writes_the_edward_waters_game_once_keeping_the_espn_id_record(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, _duplicate_records(2004))
    try:
        assert _game_ids(conn, "Florida Atlantic", "Edward Waters") == [243322226]
    finally:
        conn.close()


def test_ingest_mints_no_teams_row_for_the_duplicate_only_edward_waters_id(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`1000899` appears only on the dropped copy, so a fresh ingest must not
    create a `teams` or `team_season` row for it (#91)."""
    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, _duplicate_records(2004))
    try:
        edward_waters = [
            r["id"]
            for r in conn.execute("SELECT id FROM teams WHERE school = 'Edward Waters' ORDER BY id")
        ]
        assert edward_waters == [2206]
        assert conn.execute("SELECT 1 FROM teams WHERE id = 1000899").fetchone() is None
        assert conn.execute("SELECT 1 FROM team_season WHERE team_id = 1000899").fetchone() is None
    finally:
        conn.close()


def test_ingest_writes_an_ordinary_2004_duplicate_once(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, _duplicate_records(2004))
    try:
        assert _game_ids(conn, "Texas State", "Florida Atlantic") == [242830326]
        # 5 raw records -> 3 real games, and the log counts games written.
        assert conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"] == 3
        log = conn.execute(
            "SELECT game_count FROM ingestion_log WHERE year = 2004 AND season_type = 'regular'"
        ).fetchone()
        assert log["game_count"] == 3
    finally:
        conn.close()


def test_ingest_2008_duplicate_keeps_the_record_carrying_cfbd_elo(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both 2008 copies carry identical line scores, so line scores cannot
    break this tie. Only `282430099` carries CFBD's own pregame Elo."""
    conn = _ingest_records(empty_schema_db, monkeypatch, 2008, _duplicate_records(2008))
    try:
        assert _game_ids(conn, "LSU", "App State") == [282430099]
    finally:
        conn.close()


def test_ingest_2025_duplicate_keeps_the_record_carrying_line_scores(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Here the line-score record has the *higher* id, so "lowest id wins"
    alone would pick the wrong copy."""
    conn = _ingest_records(empty_schema_db, monkeypatch, 2025, _duplicate_records(2025))
    try:
        assert _game_ids(conn, "Augsburg", "Hamline") == [401833370]
    finally:
        conn.close()


def test_duplicate_survivor_does_not_depend_on_payload_order(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = list(reversed(_duplicate_records(2004)))
    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, records)
    try:
        assert _game_ids(conn, "Florida Atlantic", "Edward Waters") == [243322226]
        assert _game_ids(conn, "Texas State", "Florida Atlantic") == [242830326]
    finally:
        conn.close()


def test_distinct_games_on_the_same_date_both_survive(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control, real data: FIU-Florida A&M was played the same day
    as FAU-Edward Waters (2004-11-27) and must not be treated as a copy."""
    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, _duplicate_records(2004))
    try:
        assert _game_ids(conn, "Florida International", "Florida A&M") == [243322229]
        assert _game_ids(conn, "Florida Atlantic", "Edward Waters") == [243322226]
    finally:
        conn.close()


def test_same_teams_same_date_with_a_different_score_are_not_duplicates(
    empty_schema_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: a copy of a real record that differs only in id and
    in one score is a different game and must be written as one."""
    real = next(r for r in _duplicate_records(2004) if r["id"] == 242830326)
    other = copy.deepcopy(real)
    other["id"] = 999_000_001
    other["awayPoints"] = real["awayPoints"] + 1

    conn = _ingest_records(empty_schema_db, monkeypatch, 2004, [real, other])
    try:
        assert _game_ids(conn, "Texas State", "Florida Atlantic") == [242830326, 999_000_001]
    finally:
        conn.close()
