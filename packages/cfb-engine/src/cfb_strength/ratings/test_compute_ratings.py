"""Illustrative tests for the compute-and-store CLI entry point, against a
throwaway sqlite file built from the real schema.sql (not the real ingested
database -- ingestion is being built concurrently by a different agent and
may not be populated yet; see this module's RETURN notes).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from cfb_strength.contracts import Game
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.compute_ratings import (
    _franchise_successors,
    _load_games,
    _rerank_for_display,
    _store_elo_ledgers,
    compute_and_store,
    main,
)
from cfb_strength.ratings.elo import (
    ELO_CONFIGS,
    EloRating,
    rating_shift,
    revert_between_seasons,
)
from cfb_strength.ratings.keener import KeenerRating


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    conn.close()
    return db_path


def _insert_team(conn: sqlite3.Connection, team_id: int, school: str, sport: str = "cfb") -> None:
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
        "SELECT team_id, rating, rank, wins, losses FROM ratings "
        "WHERE year = ? AND method = ? ORDER BY rank",
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
    rows = conn.execute("SELECT team_id, rank FROM ratings WHERE year = ?", (year,)).fetchall()
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

    cfb_before = conn.execute("SELECT COUNT(*) AS c FROM ratings WHERE sport = 'cfb'").fetchone()[
        "c"
    ]
    breakdown_cfb_before = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE sport = 'cfb'"
    ).fetchone()["c"]
    assert cfb_before == 2
    assert breakdown_cfb_before > 0

    # Recomputing NFL alone must not touch CFB's rows for the same year.
    compute_and_store(conn, year, "keener", "nfl")

    cfb_after = conn.execute("SELECT COUNT(*) AS c FROM ratings WHERE sport = 'cfb'").fetchone()[
        "c"
    ]
    breakdown_cfb_after = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE sport = 'cfb'"
    ).fetchone()["c"]
    nfl_after = conn.execute("SELECT COUNT(*) AS c FROM ratings WHERE sport = 'nfl'").fetchone()[
        "c"
    ]
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
    rows = conn.execute("SELECT team_id, sport FROM ratings WHERE year = ?", (year,)).fetchall()
    assert len(rows) == 2
    assert all(r["sport"] == "nfl" for r in rows)
    conn.close()


# ---------------------------------------------------------------------------
# Elo (issue #86): a second and third registered method, one of which is
# stateful across seasons. The 14 tests above are unchanged and are the
# primary regression signal that adding them perturbed nothing.
# ---------------------------------------------------------------------------


def _insert_game_full(
    conn: sqlite3.Connection,
    game_id: int,
    year: int,
    home_id: int,
    away_id: int,
    home_points: int,
    away_points: int,
    week: int | None = 1,
    season_type: str = "regular",
    start_date: str | None = None,
    sport: str = "cfb",
) -> None:
    """Like `_insert_game`, but with the ordering columns exposed."""
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', ?)
        """,
        (
            game_id,
            year,
            week,
            season_type,
            start_date,
            home_id,
            away_id,
            f"team-{home_id}",
            f"team-{away_id}",
            home_points,
            away_points,
            sport,
        ),
    )


def test_elo_method_is_registered_and_writes_ratings(tmp_path: Path) -> None:
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

    count = compute_and_store(conn, year, "elo")
    assert count == 3

    rows = conn.execute(
        "SELECT team_id, rating, rank FROM ratings WHERE year = ? AND method = ? ORDER BY rank",
        (year, "elo"),
    ).fetchall()
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["rating"] > rows[1]["rating"] > rows[2]["rating"]
    # Elo lives on the ~1500 scale, not Keener's eigenvector scale.
    assert all(1000.0 < r["rating"] < 2000.0 for r in rows)
    conn.close()


def test_elo_writes_no_rating_breakdown_rows(tmp_path: Path) -> None:
    """Elo has no per-opponent decomposition, so it returns the default
    `RatingBreakdown()`. Writing a NULL-opponent residual row for it would
    assert a decomposition that does not exist."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    for tid in (1, 2):
        _insert_team(conn, tid, f"Team {tid}")
        _insert_team_season(conn, tid, year, "fbs")
    _insert_game(conn, 1, year, 1, 2, 30, 10)
    conn.commit()

    compute_and_store(conn, year, "elo")
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE method = 'elo'"
    ).fetchone()["c"]
    assert count == 0
    conn.close()


def test_single_team_wingraph_writes_no_breakdown_rows(tmp_path: Path) -> None:
    """Pins the deliberate change to `_store_breakdowns`: the residual row
    is emitted only when the breakdown is not default-constructed.

    Keener's `n == 1` early-return path (reachable only via a degenerate
    self-game) returns `rating=1.0` with an empty breakdown, so the row it
    used to write asserted `1.0 == 0.0 + 0.0` -- a violation of
    `RatingBreakdown`'s documented invariant. Dropping it is a fix, and it
    is unobservable through the only reader (`evidence/proof.py` defaults
    `residual_contribution` to 0.0 when no NULL-opponent row exists)."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    _insert_team(conn, 1, "Lonely")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_game(conn, 1, year, 1, 1, 21, 14)
    conn.commit()

    count = compute_and_store(conn, year, "keener")
    assert count == 1
    breakdown_rows = conn.execute(
        "SELECT COUNT(*) AS c FROM rating_breakdowns WHERE year = ? AND method = 'keener'",
        (year,),
    ).fetchone()["c"]
    assert breakdown_rows == 0
    conn.close()


def _seed_three_seasons(conn: sqlite3.Connection) -> None:
    for tid in (1, 2, 3):
        _insert_team(conn, tid, f"Team {tid}")
        for year in (2001, 2002, 2003):
            _insert_team_season(conn, tid, year, "fbs")
    game_id = 0
    scores = {
        2001: [(1, 2, 42, 0), (2, 3, 35, 3), (3, 1, 7, 38)],
        2002: [(1, 2, 21, 20), (2, 3, 24, 21), (3, 1, 17, 14)],
        2003: [(1, 2, 3, 45), (2, 3, 10, 40), (3, 1, 49, 0)],
    }
    for year, rows in scores.items():
        for home, away, hp, ap in rows:
            game_id += 1
            _insert_game(conn, game_id, year, home, away, hp, ap)
    conn.commit()


def test_elo_career_loads_prior_seasons(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _seed_three_seasons(conn)

    assert compute_and_store(conn, 2002, "elo") == 3
    assert compute_and_store(conn, 2002, "elo_career") == 3

    isolated = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings WHERE year = 2002 AND method = 'elo'"
        ).fetchall()
    }
    career = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings WHERE year = 2002 AND method = 'elo_career'"
        ).fetchall()
    }
    assert career.keys() == isolated.keys() == {1, 2, 3}
    # 2001 carried forward, so the two must not agree.
    assert any(career[t] != isolated[t] for t in career)
    conn.close()


def test_elo_career_does_not_leak_future_seasons(tmp_path: Path) -> None:
    """`WHERE season <= ?`, not `!= ?`: 2003 exists in the db but must have
    no effect on the 2002 rating."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _seed_three_seasons(conn)

    compute_and_store(conn, 2002, "elo_career")
    with_2003 = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings WHERE year = 2002 AND method = 'elo_career'"
        ).fetchall()
    }
    conn.execute("DELETE FROM games WHERE season = 2003")
    conn.commit()

    compute_and_store(conn, 2002, "elo_career")
    without_2003 = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings WHERE year = 2002 AND method = 'elo_career'"
        ).fetchall()
    }
    assert with_2003 == without_2003
    conn.close()


def test_elo_career_records_are_target_season_only(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _seed_three_seasons(conn)

    compute_and_store(conn, 2002, "elo_career")
    rows = conn.execute(
        "SELECT team_id, wins, losses, ties FROM ratings "
        "WHERE year = 2002 AND method = 'elo_career'"
    ).fetchall()
    # Each team plays exactly two games in 2002; the rating carries across
    # seasons but the record does not.
    for row in rows:
        assert row["wins"] + row["losses"] + row["ties"] == 2
    conn.close()


@pytest.mark.parametrize("method", ["keener", "elo", "elo_career"])
def test_compute_and_store_writes_ties_column(tmp_path: Path, method: str) -> None:
    """Issue #83: a completed equal-score game is stored in `ratings.ties`,
    through `_rerank_for_display` (which rebuilds every `TeamRating`) and
    `_store`, for every registered method. Before #83 there was no column
    and the tie vanished from the stored record."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2016

    for tid in (101, 102, 103):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 1, year, 101, 102, 27, 27, sport="nfl")
    _insert_game(conn, 2, year, 102, 103, 24, 10, sport="nfl")
    _insert_game(conn, 3, year, 103, 101, 17, 20, sport="nfl")
    conn.commit()

    assert compute_and_store(conn, year, method, "nfl") == 3
    records = {
        r["team_id"]: (r["wins"], r["losses"], r["ties"])
        for r in conn.execute(
            "SELECT team_id, wins, losses, ties FROM ratings "
            "WHERE year = ? AND method = ? AND sport = 'nfl'",
            (year, method),
        ).fetchall()
    }
    assert records == {101: (1, 0, 1), 102: (1, 0, 1), 103: (0, 2, 0)}
    conn.close()


def test_cfb_fbs_display_filter_keeps_ties(tmp_path: Path) -> None:
    """The CFB branch of `_rerank_for_display` (FBS filter + re-rank) must
    carry `ties` too, including a tie against a non-displayed FCS team."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    _insert_team(conn, 1, "FBS A")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "FBS B")
    _insert_team_season(conn, 2, year, "fbs")
    _insert_team(conn, 3, "FCS C")
    _insert_team_season(conn, 3, year, "fcs")
    _insert_game(conn, 1, year, 1, 3, 14, 14)
    _insert_game(conn, 2, year, 1, 2, 30, 20)
    conn.commit()

    assert compute_and_store(conn, year, "keener") == 2
    records = {
        r["team_id"]: (r["wins"], r["losses"], r["ties"])
        for r in conn.execute(
            "SELECT team_id, wins, losses, ties FROM ratings WHERE year = ? AND method = 'keener'",
            (year,),
        ).fetchall()
    }
    assert records == {1: (1, 0, 1), 2: (0, 1, 0)}
    conn.close()


def test_elo_career_writes_rows_only_for_target_year_teams(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)

    for tid in (1, 2, 3):
        _insert_team(conn, tid, f"Team {tid}")
    for tid in (1, 2, 3):
        _insert_team_season(conn, tid, 2001, "fbs")
    for tid in (1, 2):
        _insert_team_season(conn, tid, 2002, "fbs")
    _insert_game(conn, 1, 2001, 1, 2, 28, 21)
    _insert_game(conn, 2, 2001, 2, 3, 35, 7)
    _insert_game(conn, 3, 2002, 1, 2, 24, 20)
    conn.commit()

    count = compute_and_store(conn, 2002, "elo_career")
    assert count == 2
    rows = conn.execute(
        "SELECT team_id FROM ratings WHERE year = 2002 AND method = 'elo_career'"
    ).fetchall()
    assert {r["team_id"] for r in rows} == {1, 2}
    conn.close()


def test_elo_and_keener_coexist_for_the_same_year_and_sport(tmp_path: Path) -> None:
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
    keener_before = conn.execute(
        "SELECT team_id, rating FROM ratings WHERE method = 'keener' ORDER BY team_id"
    ).fetchall()

    compute_and_store(conn, year, "elo")
    compute_and_store(conn, year, "elo")  # recompute: delete-then-insert

    keener_after = conn.execute(
        "SELECT team_id, rating FROM ratings WHERE method = 'keener' ORDER BY team_id"
    ).fetchall()
    assert [tuple(r) for r in keener_after] == [tuple(r) for r in keener_before]
    elo_rows = conn.execute("SELECT COUNT(*) AS c FROM ratings WHERE method = 'elo'").fetchone()[
        "c"
    ]
    assert elo_rows == 3
    conn.close()


def test_nfl_elo_uses_the_nfl_config(tmp_path: Path) -> None:
    """A wrong-but-plausible failure mode: rating NFL games at CFB's
    k=40/hfa=100. Same synthetic games under each sport must not produce
    the same rating."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2023

    for tid in (1, 2):
        _insert_team(conn, tid, f"CFB {tid}", sport="cfb")
        _insert_team_season(conn, tid, year, "fbs", sport="cfb")
    _insert_game(conn, 1, year, 1, 2, 28, 21, sport="cfb")

    for tid in (101, 102):
        _insert_team(conn, tid, f"NFL {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 28, 21, sport="nfl")
    conn.commit()

    compute_and_store(conn, year, "elo", "cfb")
    compute_and_store(conn, year, "elo", "nfl")

    cfb_top = conn.execute(
        "SELECT rating FROM ratings WHERE method='elo' AND sport='cfb' AND rank=1"
    ).fetchone()["rating"]
    nfl_top = conn.execute(
        "SELECT rating FROM ratings WHERE method='elo' AND sport='nfl' AND rank=1"
    ).fetchone()["rating"]
    assert cfb_top != nfl_top
    conn.close()


def test_load_games_ordering_is_a_total_order(tmp_path: Path) -> None:
    """NULL `week` / NULL `start_date` must sort *last* within their
    season/season-type group (sqlite sorts NULLs first by default, which
    would put an undated bowl ahead of that postseason's week 1), and
    repeated calls must return an identical list."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005

    for tid in (1, 2, 3, 4):
        _insert_team(conn, tid, f"Team {tid}")
        _insert_team_season(conn, tid, year, "fbs")

    _insert_game_full(conn, 10, year, 1, 2, 20, 10, week=None, start_date=None)
    _insert_game_full(conn, 11, year, 3, 4, 21, 14, week=2, start_date="2005-09-10")
    _insert_game_full(conn, 12, year, 1, 3, 30, 7, week=1, start_date="2005-09-03")
    _insert_game_full(
        conn, 13, year, 2, 4, 17, 14, week=1, start_date=None, season_type="postseason"
    )
    _insert_game_full(
        conn, 14, year, 1, 4, 24, 3, week=None, start_date=None, season_type="postseason"
    )
    conn.commit()

    first = _load_games(conn, year, "cfb")
    second = _load_games(conn, year, "cfb")
    assert first == second

    # Regular season before postseason; within each, NULL week last.
    assert [g.season_type for g in first] == [
        "regular",
        "regular",
        "regular",
        "postseason",
        "postseason",
    ]
    assert [g.week for g in first] == [1, 2, None, 1, None]
    assert first[0].season == year
    conn.close()


def test_load_games_history_spans_prior_seasons_in_order(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _seed_three_seasons(conn)

    scoped = _load_games(conn, 2002, "cfb")
    history = _load_games(conn, 2002, "cfb", history=True)
    assert {g.season for g in scoped} == {2002}
    seasons = [g.season for g in history if g.season is not None]
    assert len(seasons) == len(history)
    assert seasons == sorted(seasons)
    assert set(seasons) == {2001, 2002}
    conn.close()


def test_main_accepts_elo_and_elo_career(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _seed_three_seasons(conn)
    conn.close()

    monkeypatch.setattr(
        "cfb_strength.ratings.compute_ratings.get_conn",
        lambda: get_conn(db_path),
    )

    assert main(["--years", "2002", "--method", "elo"]) == 0
    assert main(["--years", "2002", "--method", "elo_career"]) == 0

    conn = get_conn(db_path)
    methods = {r["method"] for r in conn.execute("SELECT DISTINCT method FROM ratings").fetchall()}
    assert methods == {"elo", "elo_career"}
    conn.close()


def test_unknown_method_message_lists_every_registered_method(tmp_path: Path) -> None:
    """`test_unknown_method_raises` above is left untouched (it is one of
    the 14 pre-existing regression tests); this pins the message content
    now that the registry has three entries."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    with pytest.raises(ValueError) as exc:
        compute_and_store(conn, 2005, "not-a-real-method")
    message = str(exc.value)
    for method in ("keener", "elo", "elo_career"):
        assert method in message
    conn.close()


def test_franchise_successors_maps_source_ids_to_team_ids(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (?, ?, NULL, 'nfl', ?)",
        (201, "St. Louis Rams", "STL"),
    )
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (?, ?, NULL, 'nfl', ?)",
        (202, "Los Angeles Rams", "LA"),
    )
    conn.commit()

    successors = _franchise_successors(conn, "nfl")
    # SD/LAC and OAK/LV are absent from this db -- a fixture covering only
    # part of the league is legitimate, not an error, so they are skipped.
    assert successors == {201: 202}
    conn.close()


def test_franchise_successors_is_empty_for_cfb(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    _insert_team(conn, 1, "Texas")
    conn.commit()
    assert _franchise_successors(conn, "cfb") == {}
    conn.close()


def _insert_nfl_team(conn: sqlite3.Connection, team_id: int, school: str, source_id: str) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (?, ?, NULL, 'nfl', ?)",
        (team_id, school, source_id),
    )


def test_elo_career_carries_a_relocated_franchise_end_to_end(tmp_path: Path) -> None:
    """F5. The join between `_franchise_successors` and `EloCareerRating`,
    through `METHODS["elo_career"]`'s factory lambda, exercised for real.

    Both halves were unit-tested in isolation -- `_franchise_successors`
    against a `teams` fixture, and lineage carryover against a hand-built
    `{STL: LA}` map in `test_elo.py` -- but nothing ran the two together, so
    the factory lambda that wires them (the whole point of the lineage
    feature) was unverified end to end. A lambda that passed `{}`, or looked
    up the wrong sport, would have kept every existing test green.

    St. Louis plays 2015, Los Angeles plays 2016, and the stored 2016 rating
    for LA's team id must start from STL's reverted 2015 rating -- not from
    `EloConfig.initial`.
    """
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)

    stl, la, opponent = 201, 202, 203
    _insert_nfl_team(conn, stl, "St. Louis Rams", "STL")
    _insert_nfl_team(conn, la, "Los Angeles Rams", "LA")
    _insert_nfl_team(conn, opponent, "Chicago Bears", "CHI")
    _insert_game(conn, 1, 2015, stl, opponent, 28, 21, sport="nfl")
    _insert_game(conn, 2, 2016, la, opponent, 24, 20, sport="nfl")
    conn.commit()

    assert _franchise_successors(conn, "nfl") == {stl: la}
    assert compute_and_store(conn, 2016, "elo_career", "nfl") == 2

    stored = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings "
            "WHERE year = 2016 AND method = 'elo_career' AND sport = 'nfl'"
        ).fetchall()
    }
    # STL did not play 2016, so only LA and its opponent are emitted -- and
    # LA, not STL, is the key, because LA is the id that played 2016.
    assert set(stored) == {la, opponent}

    nfl = ELO_CONFIGS["nfl"]
    stl_end_2015 = nfl.initial + rating_shift(nfl.initial, nfl.initial, 28, 21, False, nfl)
    opponent_end_2015 = nfl.initial - (stl_end_2015 - nfl.initial)
    la_start_2016 = revert_between_seasons(stl_end_2015, nfl)
    opponent_start_2016 = revert_between_seasons(opponent_end_2015, nfl)
    shift = rating_shift(la_start_2016, opponent_start_2016, 24, 20, False, nfl)

    assert stored[la] == la_start_2016 + shift
    assert stored[opponent] == opponent_start_2016 - shift

    # The assertion that actually catches a broken wire-up: with no lineage
    # LA would have entered 2016 cold, at `initial`, and finished lower.
    no_carryover = nfl.initial + rating_shift(nfl.initial, opponent_start_2016, 24, 20, False, nfl)
    assert stored[la] != no_carryover
    assert stored[la] > no_carryover
    conn.close()


def test_elo_career_nfl_without_a_lineage_row_starts_cold(tmp_path: Path) -> None:
    """The matched negative of the test above: same games, but the 2015
    team carries a `source_id` that is not in `FRANCHISE_LINEAGE`, so no
    carryover happens and 2016's team starts at `initial`.

    Without this pair, a factory lambda that carried *every* team forward
    (or resolved the lineage too eagerly) would still satisfy the positive
    test.
    """
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)

    old_team, new_team, opponent = 301, 302, 303
    _insert_nfl_team(conn, old_team, "Not A Predecessor", "XXX")
    _insert_nfl_team(conn, new_team, "Not A Successor", "YYY")
    _insert_nfl_team(conn, opponent, "Chicago Bears", "CHI")
    _insert_game(conn, 1, 2015, old_team, opponent, 28, 21, sport="nfl")
    _insert_game(conn, 2, 2016, new_team, opponent, 24, 20, sport="nfl")
    conn.commit()

    assert _franchise_successors(conn, "nfl") == {}
    compute_and_store(conn, 2016, "elo_career", "nfl")
    stored = {
        r["team_id"]: r["rating"]
        for r in conn.execute(
            "SELECT team_id, rating FROM ratings "
            "WHERE year = 2016 AND method = 'elo_career' AND sport = 'nfl'"
        ).fetchall()
    }

    nfl = ELO_CONFIGS["nfl"]
    opponent_end_2015 = nfl.initial - rating_shift(nfl.initial, nfl.initial, 28, 21, False, nfl)
    opponent_start_2016 = revert_between_seasons(opponent_end_2015, nfl)
    shift = rating_shift(nfl.initial, opponent_start_2016, 24, 20, False, nfl)
    assert stored[new_team] == nfl.initial + shift
    conn.close()


# ---------------------------------------------------------------------------
# Issue #183: the Elo ledger, persisted to `elo_ledger_steps` and
# `elo_ledger_configs`. The real-season tests run against a tmp copy of the
# committed regression fixtures (games only, no ratings), so the chain is
# checked across a whole season of real schedules, neutral sites included.
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"

_STEP_COLUMNS = (
    "team_id, game_number, week, season_type, start_date, opponent_team_id, venue, "
    "team_points, opponent_points, result, rating_before, opponent_rating_before, "
    "home_field_adjustment, rating_gap, win_expectancy, mov_multiplier, shift, rating_after"
)


def _fixture_conn(tmp_path: Path, name: str) -> sqlite3.Connection:
    dest = tmp_path / name
    shutil.copy(_FIXTURES_DIR / name, dest)
    return get_conn(dest)


def _ledger_row_counts(
    conn: sqlite3.Connection, year: int, method: str, sport: str
) -> tuple[int, int]:
    steps = conn.execute(
        "SELECT COUNT(*) AS c FROM elo_ledger_steps WHERE year = ? AND method = ? AND sport = ?",
        (year, method, sport),
    ).fetchone()["c"]
    configs = conn.execute(
        "SELECT COUNT(*) AS c FROM elo_ledger_configs WHERE year = ? AND method = ? AND sport = ?",
        (year, method, sport),
    ).fetchone()["c"]
    return int(steps), int(configs)


def _assert_stored_ledger_matches_ratings(conn: sqlite3.Connection, year: int, sport: str) -> None:
    """The stored ledger for (year, 'elo', sport), against the stored
    ratings: one config row equal to the sport's EloConfig, steps for
    exactly the displayed teams, and an exact chain ending on each rating."""
    cfg = ELO_CONFIGS[sport]
    configs = conn.execute(
        "SELECT starting_rating, k, hfa, scale, mov_scale, mov_autocorr "
        "FROM elo_ledger_configs WHERE year = ? AND method = 'elo' AND sport = ?",
        (year, sport),
    ).fetchall()
    assert [tuple(r) for r in configs] == [
        (cfg.initial, cfg.k, cfg.hfa, cfg.scale, cfg.mov_scale, cfg.mov_autocorr)
    ]

    ratings = {
        r["team_id"]: r
        for r in conn.execute(
            "SELECT team_id, rating, wins, losses, ties FROM ratings "
            "WHERE year = ? AND method = 'elo' AND sport = ?",
            (year, sport),
        ).fetchall()
    }
    assert ratings
    steps_by_team: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute(
        f"SELECT {_STEP_COLUMNS} FROM elo_ledger_steps "
        "WHERE year = ? AND method = 'elo' AND sport = ? ORDER BY team_id, game_number",
        (year, sport),
    ).fetchall():
        steps_by_team.setdefault(row["team_id"], []).append(row)
    assert set(steps_by_team) == set(ratings)

    for team_id, steps in steps_by_team.items():
        rating = ratings[team_id]
        assert [s["game_number"] for s in steps] == list(range(1, len(steps) + 1))
        assert len(steps) == rating["wins"] + rating["losses"] + rating["ties"]
        assert steps[0]["rating_before"] == cfg.initial
        for before, after in zip(steps, steps[1:]):
            assert after["rating_before"] == before["rating_after"]
        for step in steps:
            assert step["rating_after"] == step["rating_before"] + step["shift"]
        assert steps[-1]["rating_after"] == rating["rating"]


@pytest.mark.parametrize(
    ("fixture", "year", "sport"),
    [("cfb_regression.sqlite3", 2005, "cfb"), ("nfl_regression.sqlite3", 2022, "nfl")],
)
def test_elo_ledger_is_stored_for_a_real_season(
    tmp_path: Path, fixture: str, year: int, sport: str
) -> None:
    conn = _fixture_conn(tmp_path, fixture)
    count = compute_and_store(conn, year, "elo", sport)
    assert count > 0
    _assert_stored_ledger_matches_ratings(conn, year, sport)

    venues = {
        r["venue"]
        for r in conn.execute(
            "SELECT DISTINCT venue FROM elo_ledger_steps WHERE year = ? AND sport = ?",
            (year, sport),
        ).fetchall()
    }
    assert venues == {"home", "away", "neutral"}
    conn.close()


def test_stored_elo_ledger_round_trips_the_in_memory_ledger(tmp_path: Path) -> None:
    """Every stored column is the in-memory step's field, in the right
    column: a transposed INSERT tuple would still satisfy the chain if it
    swapped two columns the chain does not read."""
    conn = _fixture_conn(tmp_path, "cfb_regression.sqlite3")
    compute_and_store(conn, 2005, "elo")
    expected = EloRating(ELO_CONFIGS["cfb"]).rate(_load_games(conn, 2005, "cfb"))

    stored = conn.execute(
        f"SELECT {_STEP_COLUMNS} FROM elo_ledger_steps "
        "WHERE year = 2005 AND method = 'elo' AND sport = 'cfb' ORDER BY team_id, game_number"
    ).fetchall()
    assert stored
    for row in stored:
        ledger = expected[row["team_id"]].elo_ledger
        assert ledger is not None
        step = ledger.steps[row["game_number"] - 1]
        assert tuple(row)[1:] == (
            step.game_number,
            step.week,
            step.season_type,
            step.start_date,
            step.opponent_team_id,
            step.venue,
            step.team_points,
            step.opponent_points,
            step.result,
            step.rating_before,
            step.opponent_rating_before,
            step.home_field_adjustment,
            step.rating_gap,
            step.win_expectancy,
            step.mov_multiplier,
            step.shift,
            step.rating_after,
        )
    conn.close()


def test_keener_and_elo_career_write_no_ledger_rows(tmp_path: Path) -> None:
    conn = _fixture_conn(tmp_path, "cfb_regression.sqlite3")
    assert compute_and_store(conn, 2005, "keener") > 0
    assert compute_and_store(conn, 2005, "elo_career") > 0
    assert conn.execute("SELECT COUNT(*) AS c FROM elo_ledger_steps").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM elo_ledger_configs").fetchone()["c"] == 0
    conn.close()


def test_rerunning_elo_replaces_the_ledger_without_duplicates(tmp_path: Path) -> None:
    conn = _fixture_conn(tmp_path, "cfb_regression.sqlite3")
    compute_and_store(conn, 2005, "elo")
    first = _ledger_row_counts(conn, 2005, "elo", "cfb")
    assert first[0] > 0 and first[1] == 1

    compute_and_store(conn, 2005, "elo")
    assert _ledger_row_counts(conn, 2005, "elo", "cfb") == first
    duplicates = conn.execute(
        "SELECT team_id, game_number FROM elo_ledger_steps "
        "GROUP BY year, method, sport, team_id, game_number HAVING COUNT(*) > 1"
    ).fetchall()
    assert duplicates == []
    _assert_stored_ledger_matches_ratings(conn, 2005, "cfb")
    conn.close()


def _seed_stale_ledger(conn: sqlite3.Connection, year: int, method: str, sport: str) -> None:
    """One junk config row and one junk step row for (year, method, sport)."""
    team_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM teams WHERE sport = ? ORDER BY id LIMIT 2", (sport,)
        ).fetchall()
    ]
    conn.execute(
        "INSERT INTO elo_ledger_configs (year, method, sport, starting_rating, k, hfa, "
        "scale, mov_scale, mov_autocorr, computed_at) "
        "VALUES (?, ?, ?, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 'stale')",
        (year, method, sport),
    )
    conn.execute(
        "INSERT INTO elo_ledger_steps (year, method, sport, team_id, game_number, week, "
        "season_type, start_date, opponent_team_id, venue, team_points, opponent_points, "
        "result, rating_before, opponent_rating_before, home_field_adjustment, rating_gap, "
        "win_expectancy, mov_multiplier, shift, rating_after, computed_at) "
        "VALUES (?, ?, ?, ?, 99, NULL, 'regular', NULL, ?, 'home', 1, 0, 'W', "
        "1.0, 1.0, 0.0, 0.0, 0.5, 1.0, 1.0, 2.0, 'stale')",
        (year, method, sport, team_ids[0], team_ids[1]),
    )
    conn.commit()


@pytest.mark.parametrize("method", ["keener", "elo_career"])
def test_a_method_without_a_ledger_clears_stale_ledger_rows(tmp_path: Path, method: str) -> None:
    """The DELETE is unconditional: a method that writes no ledger leaves
    none behind for its (year, method, sport)."""
    conn = _fixture_conn(tmp_path, "cfb_regression.sqlite3")
    _seed_stale_ledger(conn, 2005, method, "cfb")
    assert _ledger_row_counts(conn, 2005, method, "cfb") == (1, 1)
    compute_and_store(conn, 2005, method)
    assert _ledger_row_counts(conn, 2005, method, "cfb") == (0, 0)
    conn.close()


def test_elo_with_no_games_clears_its_ledger(tmp_path: Path) -> None:
    """The empty-ratings path deletes too, so a season whose games vanish
    does not keep serving the old ledger."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005
    for tid in (1, 2):
        _insert_team(conn, tid, f"Team {tid}")
        _insert_team_season(conn, tid, year, "fbs")
    _insert_game(conn, 1, year, 1, 2, 21, 14)
    conn.commit()

    compute_and_store(conn, year, "elo")
    assert _ledger_row_counts(conn, year, "elo", "cfb") == (2, 1)

    conn.execute("DELETE FROM games")
    conn.commit()
    assert compute_and_store(conn, year, "elo") == 0
    assert _ledger_row_counts(conn, year, "elo", "cfb") == (0, 0)
    conn.close()


def test_elo_ledger_rows_are_sport_scoped(tmp_path: Path) -> None:
    """An NFL Elo run, and a rerun of it, never touches CFB's ledger rows
    for the same year, and each sport's config row is its own."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2023
    for tid in (1, 2, 3):
        _insert_team(conn, tid, f"CFB Team {tid}", sport="cfb")
        _insert_team_season(conn, tid, year, "fbs", sport="cfb")
    _insert_game(conn, 1, year, 1, 2, 30, 10, sport="cfb")
    _insert_game(conn, 2, year, 2, 3, 20, 17, sport="cfb")
    for tid in (101, 102):
        _insert_team(conn, tid, f"NFL Team {tid}", sport="nfl")
        _insert_team_season(conn, tid, year, None, sport="nfl")
    _insert_game(conn, 101, year, 101, 102, 24, 20, sport="nfl")
    conn.commit()

    compute_and_store(conn, year, "elo", "cfb")
    cfb_rows = [
        tuple(r)
        for r in conn.execute(
            "SELECT * FROM elo_ledger_steps WHERE sport = 'cfb' ORDER BY id"
        ).fetchall()
    ]
    assert len(cfb_rows) == 4

    compute_and_store(conn, year, "elo", "nfl")
    compute_and_store(conn, year, "elo", "nfl")

    assert [
        tuple(r)
        for r in conn.execute(
            "SELECT * FROM elo_ledger_steps WHERE sport = 'cfb' ORDER BY id"
        ).fetchall()
    ] == cfb_rows
    assert _ledger_row_counts(conn, year, "elo", "cfb") == (4, 1)
    assert _ledger_row_counts(conn, year, "elo", "nfl") == (2, 1)
    _assert_stored_ledger_matches_ratings(conn, year, "cfb")
    _assert_stored_ledger_matches_ratings(conn, year, "nfl")
    conn.close()


def test_elo_ledger_is_stored_only_for_displayed_teams(tmp_path: Path) -> None:
    """The FBS display filter applies to the ledger like the ratings: an FCS
    team gets no steps, but still appears as a displayed team's opponent."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    year = 2005
    _insert_team(conn, 1, "FBS A")
    _insert_team_season(conn, 1, year, "fbs")
    _insert_team(conn, 2, "FBS B")
    _insert_team_season(conn, 2, year, "fbs")
    _insert_team(conn, 3, "FCS C")
    _insert_team_season(conn, 3, year, "fcs")
    _insert_game(conn, 1, year, 1, 3, 14, 14)
    _insert_game(conn, 2, year, 2, 1, 30, 20)
    conn.commit()

    assert compute_and_store(conn, year, "elo") == 2
    rows = conn.execute(
        "SELECT team_id, opponent_team_id, venue, result FROM elo_ledger_steps "
        "ORDER BY team_id, game_number"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (1, 3, "home", "T"),
        (1, 2, "away", "L"),
        (2, 1, "home", "W"),
    ]
    _assert_stored_ledger_matches_ratings(conn, year, "cfb")
    conn.close()


def test_rerank_for_display_carries_the_elo_ledger() -> None:
    games = [
        Game(home_team_id=1, away_team_id=2, home_points=28, away_points=21),
        Game(home_team_id=2, away_team_id=3, home_points=10, away_points=13),
    ]
    full = EloRating(ELO_CONFIGS["cfb"]).rate(games)
    displayed = _rerank_for_display(full, {1, 3})
    assert sorted(tr.team_id for tr in displayed) == [1, 3]
    for tr in displayed:
        assert tr.elo_ledger is not None
        assert tr.elo_ledger is full[tr.team_id].elo_ledger


def test_store_elo_ledgers_rejects_ledgers_with_different_constants(tmp_path: Path) -> None:
    """One config row per (year, method, sport) can only describe ledgers
    that share their constants; anything else would print a wrong tuning
    beside some team's path, so it raises instead of picking one."""
    db_path = _make_db(tmp_path)
    conn = get_conn(db_path)
    for tid in (1, 2):
        _insert_team(conn, tid, f"Team {tid}")
    conn.commit()
    games = [Game(home_team_id=1, away_team_id=2, home_points=28, away_points=21)]
    cfb = EloRating(ELO_CONFIGS["cfb"]).rate(games)
    nfl = EloRating(ELO_CONFIGS["nfl"]).rate(games)
    with pytest.raises(ValueError, match="constants"):
        _store_elo_ledgers(conn, 2005, "elo", [cfb[1], nfl[2]], "cfb")
    assert _ledger_row_counts(conn, 2005, "elo", "cfb") == (0, 0)
    conn.close()
