"""Integration coverage for `cfb_strength.ingest.nflverse`: real cached
nflverse CSV rows, normalized end-to-end into upserted `games`/`teams`/
`team_season`/`ingestion_log` rows in a real sqlite db (schema.sql +
connection.py's migration), alongside the existing CFBD path.

Uses the same real-data fixtures as test_ingest_nflverse_normalize.py
(`tests/fixtures/raw_nfl_games_sample.csv` / `raw_nfl_teams_sample.csv`) --
never synthetic rows, matching this project's existing ingest-test style.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.nflverse.ingest_season import ingest_one
from cfb_strength.ingest.nflverse.normalize import TeamLookup, build_team_lookup, mint_surrogate_id

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GAMES_SAMPLE = FIXTURES_DIR / "raw_nfl_games_sample.csv"
TEAMS_SAMPLE = FIXTURES_DIR / "raw_nfl_teams_sample.csv"


def _load_games() -> list[dict[str, str]]:
    with GAMES_SAMPLE.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_team_lookup() -> TeamLookup:
    with TEAMS_SAMPLE.open(newline="") as f:
        team_rows = list(csv.DictReader(f))
    return build_team_lookup(team_rows)


def test_ingest_one_writes_nfl_rows_with_sport_and_source_id(empty_schema_db: Path) -> None:
    games_raw = _load_games()
    team_lookup = _load_team_lookup()
    conn: sqlite3.Connection = get_conn(empty_schema_db)

    result = ingest_one(conn, 2023, "regular", games_raw, team_lookup)

    assert result.status == "ok"
    assert result.game_count == 1  # only 2023_04_ATL_JAX is a 2023 regular-season row

    game_rows = conn.execute("SELECT * FROM games WHERE sport = 'nfl'").fetchall()
    assert len(game_rows) == 1
    row = game_rows[0]
    assert row["source_id"] == "2023_04_ATL_JAX"
    assert row["id"] == mint_surrogate_id("nfl_game", "2023_04_ATL_JAX")
    assert row["home_team"] == "Jacksonville Jaguars"
    assert row["away_team"] == "Atlanta Falcons"

    team_rows = conn.execute("SELECT * FROM teams WHERE sport = 'nfl'").fetchall()
    assert {r["source_id"] for r in team_rows} == {"ATL", "JAX"}
    for r in team_rows:
        assert r["id"] == mint_surrogate_id("nfl_team", r["source_id"])

    log_row = conn.execute(
        "SELECT * FROM ingestion_log "
        "WHERE year = 2023 AND season_type = 'regular' AND sport = 'nfl'"
    ).fetchone()
    assert log_row is not None
    assert log_row["game_count"] == 1
    assert log_row["status"] == "ok"

    conn.close()


def test_ingest_one_postseason_batch_covers_all_four_rounds(empty_schema_db: Path) -> None:
    games_raw = _load_games()
    team_lookup = _load_team_lookup()
    conn: sqlite3.Connection = get_conn(empty_schema_db)

    result = ingest_one(conn, 2023, "postseason", games_raw, team_lookup)

    assert result.game_count == 4  # WC, DIV, CON, SB
    conn.close()


def test_reingesting_the_same_batch_twice_produces_no_duplicate_rows(
    empty_schema_db: Path,
) -> None:
    games_raw = _load_games()
    team_lookup = _load_team_lookup()
    conn: sqlite3.Connection = get_conn(empty_schema_db)

    ingest_one(conn, 2023, "regular", games_raw, team_lookup)
    ingest_one(conn, 2023, "postseason", games_raw, team_lookup)
    game_count_1 = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    team_count_1 = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]

    # Re-run the exact same batches -- idempotent upsert, no duplicates.
    ingest_one(conn, 2023, "regular", games_raw, team_lookup)
    ingest_one(conn, 2023, "postseason", games_raw, team_lookup)
    game_count_2 = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    team_count_2 = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]

    assert game_count_2 == game_count_1
    assert team_count_2 == team_count_1
    assert game_count_1 == 5  # 1 regular + 4 postseason

    conn.close()


def test_nfl_ingest_coexists_with_pre_existing_cfb_rows_without_id_collisions(
    regression_db: Path,
) -> None:
    """`regression_db` already has real CFBD teams/games rows (sport='cfb',
    source_id NULL) from the committed fixture. Ingesting an NFL sample into
    the same connection must not collide with any of them on id, and both
    sports must be independently queryable afterwards."""
    games_raw = _load_games()
    team_lookup = _load_team_lookup()
    conn: sqlite3.Connection = get_conn(regression_db)
    # A no-op on the committed fixture, which is at the current schema
    # (#110). A stale one fails here on the StaleDatabaseWarning gate. The
    # in-place migration of a pre-#51 db is test_schema_migration.py's job.
    ensure_schema(conn)

    cfb_game_ids_before = {
        r["id"] for r in conn.execute("SELECT id FROM games WHERE sport = 'cfb'").fetchall()
    }
    cfb_team_ids_before = {
        r["id"] for r in conn.execute("SELECT id FROM teams WHERE sport = 'cfb'").fetchall()
    }
    assert cfb_game_ids_before, "regression_db fixture should already have CFB games"
    assert cfb_team_ids_before, "regression_db fixture should already have CFB teams"

    ingest_one(conn, 2023, "regular", games_raw, team_lookup)
    ingest_one(conn, 2023, "postseason", games_raw, team_lookup)

    nfl_game_ids = {
        r["id"] for r in conn.execute("SELECT id FROM games WHERE sport = 'nfl'").fetchall()
    }
    nfl_team_ids = {
        r["id"] for r in conn.execute("SELECT id FROM teams WHERE sport = 'nfl'").fetchall()
    }
    assert nfl_game_ids, "expected NFL games to have been written"
    assert nfl_team_ids, "expected NFL teams to have been written"

    assert nfl_game_ids.isdisjoint(cfb_game_ids_before)
    assert nfl_team_ids.isdisjoint(cfb_team_ids_before)

    # CFB rows are untouched and both sets remain independently queryable.
    cfb_game_ids_after = {
        r["id"] for r in conn.execute("SELECT id FROM games WHERE sport = 'cfb'").fetchall()
    }
    assert cfb_game_ids_after == cfb_game_ids_before

    total_games = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    assert total_games == len(cfb_game_ids_before) + len(nfl_game_ids)

    conn.close()


def test_ingest_one_suspect_status_when_batch_has_no_games(empty_schema_db: Path) -> None:
    games_raw = _load_games()
    team_lookup = _load_team_lookup()
    conn: sqlite3.Connection = get_conn(empty_schema_db)

    # 2022 has no rows in the fixture sample.
    result = ingest_one(conn, 2022, "regular", games_raw, team_lookup)

    assert result.game_count == 0
    assert result.status == "suspect"
    conn.close()
