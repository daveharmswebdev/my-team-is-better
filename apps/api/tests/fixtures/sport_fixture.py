"""Throwaway sqlite db builder for sport-threading tests (GitHub issue #59).

Mirrors `cfb_strength.evidence.test_proof`'s `_build_fixture` almost exactly
(same insert helpers, same CFB win-cycle/NFL win-cycle/"Wildcats" name-
collision shape) rather than reusing the committed
`cfb_verdict_fixture.sqlite3`, which predates NFL support and has no
`sport='nfl'` rows at all. This is the one place in `apps/api` that needs a
hand-built db instead of the real-engine-computed fixture, since exercising
sport threading through the HTTP layer requires NFL rows to exist somewhere,
and building a second real-engine-computed fixture is unnecessary weight for
what's ultimately a plumbing test (the engine layer's own real-ratings
integration test already lives in `cfb_verdict_fixture.sqlite3` / this
module's own `test_proof.py` counterpart).

Not part of the pytest suite itself (doesn't match `test_*.py`) -- imported
by `test_verdict_sport.py`, `test_catalog_sport.py`, and `test_deps.py`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn

YEAR = 2023
METHOD = "keener"

# CFB team ids/names (a 3-team win cycle 1 > 2 > 3 > 1).
CFB_TEAM_NAMES = {1: "Alpha State", 2: "Bravo Tech", 3: "Charlie U"}
# NFL team ids/names (an analogous, disjoint-id 3-team win cycle).
NFL_TEAM_NAMES = {101: "Delta Squad", 102: "Echo Corp", 103: "Foxtrot Ltd"}
# Name-colliding pair across sports, same year/method -- proves a CFB/NFL
# team-name collision (e.g. shared city/mascot names) doesn't cross-
# contaminate `resolve_team`'s candidate pool or `list_all_team_names`'s
# grounding-check universe.
CFB_COLLISION_TEAM_ID = 4
NFL_COLLISION_TEAM_ID = 104
COLLISION_NAME = "Wildcats"


def _insert_team(
    conn: sqlite3.Connection,
    team_id: int,
    school: str,
    classification: str | None = None,
    sport: str = "cfb",
) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport) VALUES (?, ?, ?, ?)",
        (team_id, school, classification, sport),
    )


def _insert_game(
    conn: sqlite3.Connection,
    game_id: int,
    year: int,
    home_id: int,
    away_id: int,
    home_team: str,
    away_team: str,
    home_points: int,
    away_points: int,
    week: int = 1,
    season_type: str = "regular",
    completed: bool = True,
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, ?, ?, ?, NULL, 0, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', ?)
        """,
        (
            game_id,
            year,
            week,
            season_type,
            1 if completed else 0,
            home_id,
            away_id,
            home_team,
            away_team,
            home_points,
            away_points,
            sport,
        ),
    )


def _insert_rating(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    rating: float,
    rank: int,
    wins: int,
    losses: int,
    sport: str = "cfb",
    ties: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO ratings (
            year, method, team_id, rating, rank, wins, losses, ties, computed_at, sport
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (year, method, team_id, rating, rank, wins, losses, ties, sport),
    )


def _insert_breakdown(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    opponent_team_id: int | None,
    games_played: int | None,
    wins: int | None,
    losses: int | None,
    credit: float | None,
    contribution: float,
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO rating_breakdowns (
            year, method, team_id, opponent_team_id, games_played, wins, losses,
            credit, contribution, computed_at, sport
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (
            year,
            method,
            team_id,
            opponent_team_id,
            games_played,
            wins,
            losses,
            credit,
            contribution,
            sport,
        ),
    )


def build_sport_fixture(conn: sqlite3.Connection) -> None:
    """Populate `conn` (an already-`ensure_schema`'d connection) with a CFB
    win cycle, an NFL win cycle, and a cross-sport name collision."""
    for tid, name in CFB_TEAM_NAMES.items():
        _insert_team(conn, tid, name, classification="fbs", sport="cfb")
    _insert_game(conn, 1, YEAR, 1, 2, CFB_TEAM_NAMES[1], CFB_TEAM_NAMES[2], 30, 10, sport="cfb")
    _insert_game(conn, 2, YEAR, 2, 3, CFB_TEAM_NAMES[2], CFB_TEAM_NAMES[3], 20, 17, sport="cfb")
    _insert_game(conn, 3, YEAR, 3, 1, CFB_TEAM_NAMES[3], CFB_TEAM_NAMES[1], 3, 40, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 1, 1.5, 1, 2, 0, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 2, 1.0, 2, 1, 1, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 3, 0.5, 3, 0, 2, sport="cfb")
    for tid in (1, 2, 3):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 2, 1, 1, 0, 0.6, 0.9, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 3, 1, 1, 0, 0.6, 0.5, sport="cfb")

    for tid, name in NFL_TEAM_NAMES.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")
    _insert_game(
        conn, 101, YEAR, 101, 102, NFL_TEAM_NAMES[101], NFL_TEAM_NAMES[102], 24, 20, sport="nfl"
    )
    _insert_game(
        conn, 102, YEAR, 102, 103, NFL_TEAM_NAMES[102], NFL_TEAM_NAMES[103], 27, 3, sport="nfl"
    )
    _insert_game(
        conn, 103, YEAR, 103, 101, NFL_TEAM_NAMES[103], NFL_TEAM_NAMES[101], 14, 31, sport="nfl"
    )
    _insert_rating(conn, YEAR, METHOD, 101, 1.4, 1, 2, 0, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 102, 0.9, 2, 1, 1, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 103, 0.4, 3, 0, 2, sport="nfl")
    for tid in (101, 102, 103):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")

    # NFL-only rating for a year CFB has no rows for, so a sport-scoped
    # "unknown year" 404 for CFB never accidentally reports the NFL list.
    _insert_team(conn, 105, "Golf United", classification=None, sport="nfl")
    _insert_rating(conn, 2024, METHOD, 105, 0.2, 1, 1, 0, sport="nfl")

    # Cross-sport name collision, same year/method, no games needed
    # (build_team_case only requires a ratings row to exist).
    _insert_team(conn, CFB_COLLISION_TEAM_ID, COLLISION_NAME, classification="fbs", sport="cfb")
    _insert_rating(conn, YEAR, METHOD, CFB_COLLISION_TEAM_ID, 0.3, 4, 0, 0, sport="cfb")
    _insert_breakdown(
        conn, YEAR, METHOD, CFB_COLLISION_TEAM_ID, None, None, None, None, None, 0.1, sport="cfb"
    )

    _insert_team(conn, NFL_COLLISION_TEAM_ID, COLLISION_NAME, classification=None, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, NFL_COLLISION_TEAM_ID, 0.3, 4, 0, 0, sport="nfl")
    _insert_breakdown(
        conn, YEAR, METHOD, NFL_COLLISION_TEAM_ID, None, None, None, None, None, 0.1, sport="nfl"
    )

    build_tie_cluster(conn)


# Issue #83: a synthetic NFL tie. No committed apps/api fixture had a single
# equal-score game (the CFB fixture's real 2001/2005/2013 data and the win
# cycles above are all decisive), so nothing could prove a tie survives the
# HTTP layer. Kept disjoint from the win cycle above -- separate ids, ranks
# below every existing NFL row -- so no pre-existing assertion moves.
#
#   Lima Lions   20-13 Kilo Kings      (Kilo's only loss, to rank 5)
#   Kilo Kings   17-17 Mike Mustangs   (the tie, against rank 8)
#   Kilo Kings   24-7  November Nomads (Kilo's only win, over rank 9)
#   Lima Lions   27-10 Mike Mustangs   (so Mike is a common opponent)
#
# The ranks are chosen so a tie mistaken for a loss would *become*
# `worst_loss` (rank 8 is worse than rank 5), and a tie mistaken for a win
# would join `quality_wins` (rank 8 is inside the top-25 threshold).
TIE_TEAM_ID = 106
TIE_TEAM = "Kilo Kings"
TIE_RIVAL_ID = 107
TIE_RIVAL = "Lima Lions"
TIE_OPPONENT_ID = 108
TIE_OPPONENT = "Mike Mustangs"
TIE_WIN_OPPONENT_ID = 109
TIE_WIN_OPPONENT = "November Nomads"


def build_tie_cluster(conn: sqlite3.Connection) -> None:
    names = {
        TIE_TEAM_ID: TIE_TEAM,
        TIE_RIVAL_ID: TIE_RIVAL,
        TIE_OPPONENT_ID: TIE_OPPONENT,
        TIE_WIN_OPPONENT_ID: TIE_WIN_OPPONENT,
    }
    for tid, name in names.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")

    _insert_game(
        conn, 104, YEAR, TIE_RIVAL_ID, TIE_TEAM_ID, TIE_RIVAL, TIE_TEAM, 20, 13, sport="nfl"
    )
    _insert_game(
        conn,
        105,
        YEAR,
        TIE_TEAM_ID,
        TIE_OPPONENT_ID,
        TIE_TEAM,
        TIE_OPPONENT,
        17,
        17,
        week=2,
        sport="nfl",
    )
    _insert_game(
        conn,
        106,
        YEAR,
        TIE_TEAM_ID,
        TIE_WIN_OPPONENT_ID,
        TIE_TEAM,
        TIE_WIN_OPPONENT,
        24,
        7,
        week=3,
        sport="nfl",
    )
    _insert_game(
        conn,
        107,
        YEAR,
        TIE_RIVAL_ID,
        TIE_OPPONENT_ID,
        TIE_RIVAL,
        TIE_OPPONENT,
        27,
        10,
        week=2,
        sport="nfl",
    )

    _insert_rating(conn, YEAR, METHOD, TIE_RIVAL_ID, 0.35, 5, 2, 0, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, TIE_TEAM_ID, 0.25, 6, 1, 1, sport="nfl", ties=1)
    _insert_rating(conn, YEAR, METHOD, TIE_OPPONENT_ID, 0.15, 8, 0, 1, sport="nfl", ties=1)
    _insert_rating(conn, YEAR, METHOD, TIE_WIN_OPPONENT_ID, 0.05, 9, 0, 1, sport="nfl")
    for tid in names:
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")


def make_sport_fixture_db(tmp_path: Path) -> Path:
    """Build a fresh schema-only db at `tmp_path / "sport_fixture.sqlite3"`,
    populate it via `build_sport_fixture`, and return its path."""
    db_path = tmp_path / "sport_fixture.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    build_sport_fixture(conn)
    conn.commit()
    conn.close()
    return db_path
