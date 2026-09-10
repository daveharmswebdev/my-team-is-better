"""Illustrative tests for the compute-and-store CLI entry point, against a
throwaway sqlite file built from the real schema.sql (not the real ingested
database -- ingestion is being built concurrently by a different agent and
may not be populated yet; see this module's RETURN notes).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.compute_ratings import compute_and_store, main


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    conn.close()
    return db_path


def _insert_team(conn: sqlite3.Connection, team_id: int, school: str) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification) VALUES (?, ?, ?)",
        (team_id, school, None),
    )


def _insert_team_season(conn: sqlite3.Connection, team_id: int, year: int, classification: str) -> None:
    conn.execute(
        "INSERT INTO team_season (team_id, year, conference, classification) VALUES (?, ?, ?, ?)",
        (team_id, year, "Test Conf", classification),
    )


def _insert_game(
    conn: sqlite3.Connection,
    game_id: int,
    year: int,
    home_id: int,
    away_id: int,
    home_points: int,
    away_points: int,
    completed: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json
        ) VALUES (?, ?, 1, 'regular', NULL, 0, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}')
        """,
        (
            game_id,
            year,
            1 if completed else 0,
            home_id,
            away_id,
            f"team-{home_id}",
            f"team-{away_id}",
            home_points,
            away_points,
        ),
    )


def test_compute_and_store_writes_ranked_fbs_rows(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    for tid in (1, 2, 3):
        _insert_team(conn, tid, f"Team {tid}")
        _insert_team_season(conn, tid, year, "fbs")

    _insert_game(conn, 1, year, 1, 2, 30, 10)
    _insert_game(conn, 2, year, 2, 3, 20, 17)
    _insert_game(conn, 3, year, 3, 1, 3, 40)
    conn.commit()

    count = compute_and_store(conn, year, "keener")
    assert count == 3

    rows = conn.execute(
        "SELECT team_id, rating, rank, wins, losses FROM ratings WHERE year = ? AND method = ? ORDER BY rank",
        (year, "keener"),
    ).fetchall()
    assert len(rows) == 3
    assert [r["rank"] for r in rows] == [1, 2, 3]
    # ratings strictly descending by rank
    assert rows[0]["rating"] > rows[1]["rating"] > rows[2]["rating"]
    conn.close()


def test_compute_and_store_excludes_non_fbs_from_rank_but_not_from_graph(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    _insert_team(conn, 1, "FBS Team")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "FCS Cupcake")
    _insert_team_season(conn, 2, year, "fcs")

    _insert_game(conn, 1, year, 1, 2, 50, 0)
    conn.commit()

    count = compute_and_store(conn, year, "keener")
    assert count == 1  # only the FBS team gets a displayed row

    rows = conn.execute(
        "SELECT team_id FROM ratings WHERE year = ? AND method = ?", (year, "keener")
    ).fetchall()
    assert {r["team_id"] for r in rows} == {1}
    conn.close()


def test_compute_and_store_ignores_incomplete_games(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    _insert_team(conn, 1, "A")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "B")
    _insert_team_season(conn, 2, year, "fbs")

    _insert_game(conn, 1, year, 1, 2, 0, 0, completed=False)
    conn.commit()

    count = compute_and_store(conn, year, "keener")
    assert count == 0
    conn.close()


def test_delete_then_insert_replaces_prior_rows(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    _insert_team(conn, 1, "A")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "B")
    _insert_team_season(conn, 2, year, "fbs")
    _insert_game(conn, 1, year, 1, 2, 21, 14)
    conn.commit()

    compute_and_store(conn, year, "keener")
    first_count = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]

    compute_and_store(conn, year, "keener")
    second_count = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]

    assert first_count == second_count == 2
    conn.close()


def test_unknown_method_raises(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    with pytest.raises(ValueError):
        compute_and_store(conn, 2005, "not-a-real-method")
    conn.close()


def test_main_signature_and_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2010
    _insert_team(conn, 1, "A")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "B")
    _insert_team_season(conn, 2, year, "fbs")
    _insert_game(conn, 1, year, 1, 2, 28, 21)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "cfb_strength.ratings.compute_ratings.get_conn",
        lambda: get_conn(db_path),
    )

    exit_code = main(["--years", str(year), "--method", "keener"])
    assert exit_code == 0

    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT team_id, rank FROM ratings WHERE year = ?", (year,)
    ).fetchall()
    assert len(rows) == 2
    conn.close()


def test_year_range_parsing_via_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    for year in (2001, 2002):
        _insert_team(conn, year * 10 + 1, f"A{year}")
        _insert_team_season(conn, year * 10 + 1, year, "fbs")
        _insert_team(conn, year * 10 + 2, f"B{year}")
        _insert_team_season(conn, year * 10 + 2, year, "fbs")
        _insert_game(conn, year, year, year * 10 + 1, year * 10 + 2, 10, 7)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "cfb_strength.ratings.compute_ratings.get_conn",
        lambda: get_conn(db_path),
    )

    exit_code = main(["--years", "2001-2002"])
    assert exit_code == 0

    conn = get_conn(db_path)
    years_present = {
        r["year"] for r in conn.execute("SELECT DISTINCT year FROM ratings").fetchall()
    }
    assert years_present == {2001, 2002}
    conn.close()
