"""Illustrative tests for the compute-and-store CLI entry point, against a
throwaway sqlite file built from the real schema.sql (not the real ingested
database -- ingestion is being built concurrently by a different agent and
may not be populated yet; see this module's RETURN notes).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.contracts import Game
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.compute_ratings import compute_and_store, main
from cfb_strength.ratings.keener import KeenerRating


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    conn.close()
    return db_path


def _insert_team(
    conn: sqlite3.Connection, team_id: int, school: str, sport: str = "cfb"
) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport) VALUES (?, ?, ?, ?)",
        (team_id, school, None, sport),
    )


def _insert_team_season(
    conn: sqlite3.Connection,
    team_id: int,
    year: int,
    classification: str | None,
    sport: str = "cfb",
) -> None:
    conn.execute(
        "INSERT INTO team_season (team_id, year, conference, classification, sport) "
        "VALUES (?, ?, ?, ?, ?)",
        (team_id, year, "Test Conf", classification, sport),
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
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, ?, 1, 'regular', NULL, 0, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', ?)
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
            sport,
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


def test_compute_and_store_writes_rating_breakdowns(tmp_path: Path) -> None:
    """Issue #31: one rating_breakdowns row per opponent actually played,
    plus one opponent_team_id=NULL residual row, per displayed FBS team."""
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

    compute_and_store(conn, year, "keener")

    residual_rows = conn.execute(
        "SELECT team_id, contribution FROM rating_breakdowns "
        "WHERE year = ? AND method = ? AND opponent_team_id IS NULL",
        (year, "keener"),
    ).fetchall()
    assert {r["team_id"] for r in residual_rows} == {1, 2, 3}

    entry_rows = conn.execute(
        "SELECT team_id, opponent_team_id, games_played, wins, losses, credit, contribution "
        "FROM rating_breakdowns WHERE year = ? AND method = ? AND opponent_team_id IS NOT NULL",
        (year, "keener"),
    ).fetchall()
    # 3-team cycle: each team played 2 distinct opponents -> 2 entry rows each.
    assert len(entry_rows) == 6
    for row in entry_rows:
        assert row["games_played"] == 1
        assert row["credit"] is not None

    # delete-then-insert: recomputing must not duplicate rows.
    compute_and_store(conn, year, "keener")
    total_after = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE year = ? AND method = ?",
        (year, "keener"),
    ).fetchone()["c"]
    assert total_after == len(entry_rows) + len(residual_rows)
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


# ---------------------------------------------------------------------------
# Issue #57: sport-scoping for the NFL. `games`/`teams`/`team_season`/
# `ratings`/`rating_breakdowns` all share rows across sports now (#51), so
# every read and write compute_ratings.py performs must be scoped by
# `sport` or CFB and NFL silently bleed into each other for an overlapping
# year (e.g. 2023).
# ---------------------------------------------------------------------------


def test_sport_isolates_win_graph_for_overlapping_year(tmp_path: Path) -> None:
    """CFB and NFL games in the *same* year must not merge into one
    win-graph. Team ids are disjoint (as they are in production, per #51's
    surrogate-id minting), but the win-graph size (`n`) and per-team
    games-played normalization both depend on which universe of games is
    considered -- so a CFB rating computed with NFL games incorrectly
    included would differ from a CFB rating computed against CFB games
    alone, even though no CFB team ever plays an NFL team directly."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2023

    # CFB teams/games: ids 1-3.
    for tid in (1, 2, 3):
        _insert_team(conn, tid, f"CFB Team {tid}", sport="cfb")
        _insert_team_season(conn, tid, year, "fbs", sport="cfb")
    _insert_game(conn, 1, year, 1, 2, 30, 10, sport="cfb")
    _insert_game(conn, 2, year, 2, 3, 20, 17, sport="cfb")
    _insert_game(conn, 3, year, 3, 1, 3, 40, sport="cfb")

    # NFL teams/games: ids 101-103 (disjoint), classification=None (no
    # FBS/FCS concept for the NFL -- matches #51's real ingest behavior).
    for tid in (101, 102, 103):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 24, 20, sport="nfl")
    _insert_game(conn, 102, year, 102, 103, 27, 3, sport="nfl")
    _insert_game(conn, 103, year, 103, 101, 14, 31, sport="nfl")
    conn.commit()

    cfb_count = compute_and_store(conn, year, "keener", "cfb")
    nfl_count = compute_and_store(conn, year, "keener", "nfl")
    assert cfb_count == 3
    assert nfl_count == 3

    cfb_rows = conn.execute(
        "SELECT team_id, sport, rating FROM ratings WHERE year = ? AND method = ? AND sport = ?",
        (year, "keener", "cfb"),
    ).fetchall()
    nfl_rows = conn.execute(
        "SELECT team_id, sport, rating FROM ratings WHERE year = ? AND method = ? AND sport = ?",
        (year, "keener", "nfl"),
    ).fetchall()
    assert {r["team_id"] for r in cfb_rows} == {1, 2, 3}
    assert {r["team_id"] for r in nfl_rows} == {101, 102, 103}
    assert all(r["sport"] == "cfb" for r in cfb_rows)
    assert all(r["sport"] == "nfl" for r in nfl_rows)

    # The CFB ratings must match what KeenerRating produces against the CFB
    # win-graph alone -- proof the NFL games were never mixed into the
    # matrix/normalization (win-graph size `n`, games-played divisor, etc.
    # would all differ if they had been).
    cfb_games_only = [
        Game(home_team_id=1, away_team_id=2, home_points=30, away_points=10),
        Game(home_team_id=2, away_team_id=3, home_points=20, away_points=17),
        Game(home_team_id=3, away_team_id=1, home_points=3, away_points=40),
    ]
    expected = KeenerRating().rate(cfb_games_only)
    actual_by_team = {r["team_id"]: r["rating"] for r in cfb_rows}
    for team_id, tr in expected.items():
        assert actual_by_team[team_id] == pytest.approx(tr.rating)

    conn.close()


def test_recomputing_one_sport_does_not_delete_the_other_sports_rows(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2023

    for tid in (1, 2):
        _insert_team(conn, tid, f"CFB Team {tid}", sport="cfb")
        _insert_team_season(conn, tid, year, "fbs", sport="cfb")
    _insert_game(conn, 1, year, 1, 2, 21, 14, sport="cfb")

    for tid in (101, 102):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 24, 20, sport="nfl")
    conn.commit()

    compute_and_store(conn, year, "keener", "cfb")
    compute_and_store(conn, year, "keener", "nfl")

    cfb_before = conn.execute(
        "SELECT COUNT(*) AS c FROM ratings WHERE sport = 'cfb'"
    ).fetchone()["c"]
    breakdown_cfb_before = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE sport = 'cfb'"
    ).fetchone()["c"]
    assert cfb_before == 2
    assert breakdown_cfb_before > 0

    # Recomputing NFL alone must not touch CFB's rows for the same year.
    compute_and_store(conn, year, "keener", "nfl")

    cfb_after = conn.execute(
        "SELECT COUNT(*) AS c FROM ratings WHERE sport = 'cfb'"
    ).fetchone()["c"]
    breakdown_cfb_after = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE sport = 'cfb'"
    ).fetchone()["c"]
    nfl_after = conn.execute(
        "SELECT COUNT(*) AS c FROM ratings WHERE sport = 'nfl'"
    ).fetchone()["c"]
    assert cfb_after == cfb_before
    assert breakdown_cfb_after == breakdown_cfb_before
    assert nfl_after == 2

    # And the reverse direction: recomputing CFB alone must not touch NFL's.
    nfl_before_second = nfl_after
    compute_and_store(conn, year, "keener", "cfb")
    nfl_after_second = conn.execute(
        "SELECT COUNT(*) AS c FROM ratings WHERE sport = 'nfl'"
    ).fetchone()["c"]
    assert nfl_after_second == nfl_before_second

    conn.close()


def test_nfl_ratings_display_every_team_no_fbs_style_filter(tmp_path: Path) -> None:
    """NFL has no FBS/FCS-style classification split (#51 writes
    `classification=None` for every NFL `team_season` row) -- every team
    that appears in the win-graph must be ranked/displayed, unlike CFB
    where only FBS-classified teams are."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2023

    for tid in (101, 102, 103):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 24, 20, sport="nfl")
    _insert_game(conn, 102, year, 102, 103, 27, 3, sport="nfl")
    conn.commit()

    count = compute_and_store(conn, year, "keener", "nfl")
    assert count == 3  # all three teams displayed despite classification=None

    rows = conn.execute(
        "SELECT team_id FROM ratings WHERE year = ? AND method = ? AND sport = ?",
        (year, "keener", "nfl"),
    ).fetchall()
    assert {r["team_id"] for r in rows} == {101, 102, 103}
    conn.close()


def test_default_sport_is_cfb_and_existing_calls_unaffected(tmp_path: Path) -> None:
    """Every pre-existing call site invokes `compute_and_store(conn, year,
    method)` with no `sport` argument -- confirms the default keeps that
    call shape producing `sport='cfb'` rows, unchanged from before #57."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    for tid in (1, 2):
        _insert_team(conn, tid, f"Team {tid}")
        _insert_team_season(conn, tid, year, "fbs")
    _insert_game(conn, 1, year, 1, 2, 21, 14)
    conn.commit()

    count = compute_and_store(conn, year, "keener")  # no sport arg
    assert count == 2

    rows = conn.execute(
        "SELECT sport FROM ratings WHERE year = ? AND method = ?", (year, "keener")
    ).fetchall()
    assert all(r["sport"] == "cfb" for r in rows)
    conn.close()


def test_main_sport_flag_scopes_to_nfl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2024
    for tid in (101, 102):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 24, 20, sport="nfl")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "cfb_strength.ratings.compute_ratings.get_conn",
        lambda: get_conn(db_path),
    )

    exit_code = main(["--years", str(year), "--method", "keener", "--sport", "nfl"])
    assert exit_code == 0

    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT team_id, sport FROM ratings WHERE year = ?", (year,)
    ).fetchall()
    assert len(rows) == 2
    assert all(r["sport"] == "nfl" for r in rows)
    conn.close()
