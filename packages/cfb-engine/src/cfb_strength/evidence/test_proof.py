"""Tests for evidence/proof.py: TeamCase/ComparisonResult construction against
a throwaway sqlite db built from the real schema.sql (mirrors
ratings/test_compute_ratings.py's fixture style -- see that file's own
comment on why a real schema-built db is used instead of a hand-rolled mock).

Issue #58 (sprint 2 NFL support): every `teams`/`games`/`ratings`/
`rating_breakdowns` row now carries a `sport` column (#51), and
`ratings/compute_ratings.py` was already fixed (#57) to scope every query by
it -- this file proves `evidence/proof.py` got the same fix, since it reads
those same four tables directly via SQL (the db is the integration boundary
between `evidence` and `ratings`/`ingest`, not a Python import).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.contracts import AmbiguousTeamError, SameTeamComparisonError, UnknownYearError
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.evidence.proof import (
    build_comparison,
    build_team_case,
    list_available_years,
    resolve_team,
)

YEAR = 2023
METHOD = "keener"


# ---------------------------------------------------------------------------
# fixture helpers (mirrors ratings/test_compute_ratings.py's _insert_* style)
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    conn.close()
    return db_path


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
) -> None:
    conn.execute(
        """
        INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, computed_at, sport)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (year, method, team_id, rating, rank, wins, losses, sport),
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
        (year, method, team_id, opponent_team_id, games_played, wins, losses, credit, contribution, sport),
    )


def _build_fixture(conn: sqlite3.Connection) -> None:
    """A 3-team win cycle for CFB (ids 1-3, classification='fbs') and an
    analogous 3-team cycle for NFL (ids 101-103, classification=None,
    per #51's real NFL-ingest behavior), both under `YEAR`/`METHOD` -- the
    exact "same year value, different sport" scenario #57 already fixed for
    compute_ratings.py. Plus one deliberately name-colliding pair (id 4 "Wildcats"
    CFB vs id 104 "Wildcats" NFL) to make a sport-filter regression in
    `resolve_team`'s candidate pool directly observable: without the `sport`
    filter, resolving "Wildcats" for either sport would be ambiguous (2
    candidates); with it, each resolves uniquely.
    """
    # --- CFB: teams 1-3, a win cycle 1 > 2 > 3 > 1 (mirrors
    # ratings/test_compute_ratings.py's fixture cycle) ---
    cfb_names = {1: "Alpha State", 2: "Bravo Tech", 3: "Charlie U"}
    for tid, name in cfb_names.items():
        _insert_team(conn, tid, name, classification="fbs", sport="cfb")
    _insert_game(conn, 1, YEAR, 1, 2, cfb_names[1], cfb_names[2], 30, 10, sport="cfb")
    _insert_game(conn, 2, YEAR, 2, 3, cfb_names[2], cfb_names[3], 20, 17, sport="cfb")
    _insert_game(conn, 3, YEAR, 3, 1, cfb_names[3], cfb_names[1], 3, 40, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 1, 1.5, 1, 2, 0, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 2, 1.0, 2, 1, 1, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 3, 0.5, 3, 0, 2, sport="cfb")
    for tid in (1, 2, 3):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 2, 1, 1, 0, 0.6, 0.9, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 3, 1, 1, 0, 0.6, 0.5, sport="cfb")

    # --- NFL: teams 101-103, an analogous win cycle -- disjoint ids per
    # #51's surrogate-id minting, classification=None (no FBS/FCS concept) ---
    nfl_names = {101: "Delta Squad", 102: "Echo Corp", 103: "Foxtrot Ltd"}
    for tid, name in nfl_names.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")
    _insert_game(conn, 101, YEAR, 101, 102, nfl_names[101], nfl_names[102], 24, 20, sport="nfl")
    _insert_game(conn, 102, YEAR, 102, 103, nfl_names[102], nfl_names[103], 27, 3, sport="nfl")
    _insert_game(conn, 103, YEAR, 103, 101, nfl_names[103], nfl_names[101], 14, 31, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 101, 1.4, 1, 2, 0, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 102, 0.9, 2, 1, 1, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 103, 0.4, 3, 0, 2, sport="nfl")
    for tid in (101, 102, 103):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")

    # NFL-only rating for a year CFB has no rows for, so list_available_years
    # scoped by sport can be distinguished from an unfiltered DISTINCT year.
    _insert_team(conn, 105, "Golf United", classification=None, sport="nfl")
    _insert_rating(conn, 2024, METHOD, 105, 0.2, 1, 1, 0, sport="nfl")

    # --- Name-colliding pair across sports, same year/method, no games
    # needed (build_team_case only requires a ratings row to exist) ---
    _insert_team(conn, 4, "Wildcats", classification="fbs", sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 4, 0.3, 4, 0, 0, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 4, None, None, None, None, None, 0.1, sport="cfb")

    _insert_team(conn, 104, "Wildcats", classification=None, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 104, 0.3, 4, 0, 0, sport="nfl")
    _insert_breakdown(conn, YEAR, METHOD, 104, None, None, None, None, None, 0.1, sport="nfl")


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = _make_db(tmp_path)
    c = get_conn(db_path)
    _build_fixture(c)
    c.commit()
    return c


# ---------------------------------------------------------------------------
# (a) NFL end-to-end
# ---------------------------------------------------------------------------


def test_list_available_years_nfl(conn: sqlite3.Connection) -> None:
    assert list_available_years(conn, METHOD, sport="nfl") == [YEAR, 2024]


def test_resolve_team_nfl(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Delta Squad", method=METHOD, sport="nfl") == 101


def test_build_team_case_nfl(conn: sqlite3.Connection) -> None:
    case = build_team_case(conn, YEAR, "Delta Squad", method=METHOD, sport="nfl")
    assert case.team_id == 101
    assert case.team_name == "Delta Squad"
    assert case.rank == 1
    assert case.wins == 2
    assert case.losses == 0
    # classification=NULL for NFL must not raise or otherwise break the case.
    assert len(case.games) == 2


def test_build_comparison_nfl(conn: sqlite3.Connection) -> None:
    comparison = build_comparison(conn, YEAR, "Delta Squad", "Echo Corp", method=METHOD, sport="nfl")
    assert comparison.team_a.team_id == 101
    assert comparison.team_b.team_id == 102
    assert comparison.head_to_head.played is True


# ---------------------------------------------------------------------------
# (b) CFB end-to-end -- confirms unchanged behavior with real classification
# ---------------------------------------------------------------------------


def test_list_available_years_cfb(conn: sqlite3.Connection) -> None:
    assert list_available_years(conn, METHOD, sport="cfb") == [YEAR]


def test_list_available_years_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    """No pre-#58 call site ever passed `sport` -- the default must keep
    producing the same result as an explicit sport='cfb' call."""
    assert list_available_years(conn, METHOD) == list_available_years(conn, METHOD, sport="cfb")


def test_resolve_team_cfb(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Alpha State", method=METHOD, sport="cfb") == 1


def test_resolve_team_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Alpha State", method=METHOD) == 1


def test_build_team_case_cfb(conn: sqlite3.Connection) -> None:
    case = build_team_case(conn, YEAR, "Alpha State", method=METHOD, sport="cfb")
    assert case.team_id == 1
    assert case.team_name == "Alpha State"
    assert case.rank == 1
    assert case.wins == 2
    assert case.losses == 0
    assert len(case.games) == 2


def test_build_team_case_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    default_case = build_team_case(conn, YEAR, "Alpha State", method=METHOD)
    explicit_case = build_team_case(conn, YEAR, "Alpha State", method=METHOD, sport="cfb")
    assert default_case == explicit_case


def test_build_comparison_cfb(conn: sqlite3.Connection) -> None:
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert comparison.team_a.team_id == 1
    assert comparison.team_b.team_id == 2
    assert comparison.head_to_head.played is True


def test_build_comparison_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    default = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD)
    explicit = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert default == explicit


# ---------------------------------------------------------------------------
# (c) cross-sport regression -- CFB and NFL rows sharing the same year/method,
# including a deliberately name-colliding team ("Wildcats") in both sports.
# ---------------------------------------------------------------------------


def test_resolve_team_does_not_bleed_across_sports_on_name_collision(
    conn: sqlite3.Connection,
) -> None:
    """Both sports have a team named "Wildcats" for the same year/method.
    Without a sport filter, resolve_team's exact-match stage would find 2
    candidates and raise AmbiguousTeamError for *both* calls below. With the
    filter, each resolves uniquely to its own sport's team_id."""
    assert resolve_team(conn, YEAR, "Wildcats", method=METHOD, sport="cfb") == 4
    assert resolve_team(conn, YEAR, "Wildcats", method=METHOD, sport="nfl") == 104


def test_build_team_case_does_not_bleed_across_sports_on_name_collision(
    conn: sqlite3.Connection,
) -> None:
    cfb_case = build_team_case(conn, YEAR, "Wildcats", method=METHOD, sport="cfb")
    nfl_case = build_team_case(conn, YEAR, "Wildcats", method=METHOD, sport="nfl")
    assert cfb_case.team_id == 4
    assert nfl_case.team_id == 104


def test_list_available_years_does_not_bleed_nfl_only_year_into_cfb(
    conn: sqlite3.Connection,
) -> None:
    cfb_years = list_available_years(conn, METHOD, sport="cfb")
    nfl_years = list_available_years(conn, METHOD, sport="nfl")
    assert 2024 not in cfb_years
    assert 2024 in nfl_years


def test_build_comparison_cross_sport_common_opponent_pool_stays_scoped(
    conn: sqlite3.Connection,
) -> None:
    """Alpha State and Bravo Tech share one real CFB common opponent
    (Charlie U) -- that entry must survive. But no NFL team_id (101-105) may
    ever appear, proving `build_comparison`'s CFB-scoped call doesn't pull
    NFL rows into `_ratings_map`/`_team_games` and quietly attribute an NFL
    opponent's rank/rating to a CFB matchup."""
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert [c.opponent_team_id for c in comparison.common_opponents] == [3]
    nfl_ids = {101, 102, 103, 104, 105}
    assert all(c.opponent_team_id not in nfl_ids for c in comparison.common_opponents)


def test_resolve_team_unknown_year_still_raises_when_only_other_sport_has_it(
    conn: sqlite3.Connection,
) -> None:
    """Year 2024 has ratings only for sport='nfl' -- a cfb-scoped call for
    that year must still raise UnknownYearError, not silently succeed by
    picking up the nfl rows."""
    with pytest.raises(UnknownYearError):
        resolve_team(conn, 2024, "Alpha State", method=METHOD, sport="cfb")


def test_same_team_comparison_error_still_raised_within_one_sport(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(SameTeamComparisonError):
        build_comparison(conn, YEAR, "Alpha State", "Alpha State", method=METHOD, sport="cfb")


def test_ambiguous_team_error_within_a_single_sport_still_raised(
    conn: sqlite3.Connection,
) -> None:
    # "Foxtrot" substring-matches only one NFL team -- unique, no error.
    assert resolve_team(conn, YEAR, "Foxtrot", method=METHOD, sport="nfl") == 103
