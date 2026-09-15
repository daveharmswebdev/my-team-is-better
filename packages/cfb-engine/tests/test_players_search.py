"""`cfb_strength.players.search_players` on a small synthetic db (#301)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import PLAYER_SEARCH_MAX_LIMIT, PlayerSearchRow
from cfb_strength.players import search_players
from tests.test_players_support import PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _passer(db: PlayerDb, name: str, yards: int | None = 100, season: int = 2000) -> int:
    p = db.player(name)
    db.season(p, season, **full_stats(passing_yards=yards))
    return p


def _names(db: PlayerDb, query: str, limit: int = 10) -> list[str]:
    return [
        r.display_name
        for r in search_players(conn_of(db), sport="nfl", query=query, limit=limit).rows
    ]


# --- matching -----------------------------------------------------------------


def test_matching_is_a_case_insensitive_substring(db: PlayerDb) -> None:
    _passer(db, "Peyton Manning", 300)
    _passer(db, "Eli Manning", 200)
    _passer(db, "Tom Brady", 400)
    assert _names(db, "MANN") == ["Peyton Manning", "Eli Manning"]
    assert _names(db, "ning") == ["Peyton Manning", "Eli Manning"]
    assert _names(db, "tOm b") == ["Tom Brady"]
    assert _names(db, "zz") == []


def test_the_stripped_query_and_limit_are_echoed(db: PlayerDb) -> None:
    _passer(db, "Eli Manning")
    result = search_players(conn_of(db), sport="nfl", query="  eli \t", limit=5)
    assert (result.sport, result.query, result.limit) == ("nfl", "eli", 5)
    assert [r.display_name for r in result.rows] == ["Eli Manning"]


@pytest.mark.parametrize("query", ["", " ", "a", "  a  ", "\tb\n"])
def test_a_query_shorter_than_two_characters_after_stripping_raises(
    db: PlayerDb, query: str
) -> None:
    with pytest.raises(ValueError):
        search_players(conn_of(db), sport="nfl", query=query)


@pytest.mark.parametrize("limit", [0, -1, PLAYER_SEARCH_MAX_LIMIT + 1])
def test_a_limit_out_of_range_raises(db: PlayerDb, limit: int) -> None:
    with pytest.raises(ValueError):
        search_players(conn_of(db), sport="nfl", query="ab", limit=limit)


def test_limit_bounds_the_rows_and_the_maximum_works(db: PlayerDb) -> None:
    for i in range(PLAYER_SEARCH_MAX_LIMIT + 3):
        _passer(db, f"Passer {i:02d}", 1000 - i)
    assert len(_names(db, "passer", limit=3)) == 3
    rows = _names(db, "passer", limit=PLAYER_SEARCH_MAX_LIMIT)
    assert rows == [f"Passer {i:02d}" for i in range(PLAYER_SEARCH_MAX_LIMIT)]
    assert len(_names(db, "passer")) == 10


def test_percent_and_underscore_in_the_query_match_literally(db: PlayerDb) -> None:
    _passer(db, "Joe 100% Real", 500)
    _passer(db, "Joe 1000 Real", 400)
    _passer(db, "Al_Bo Guy", 300)
    _passer(db, "AlxBo Guy", 200)
    _passer(db, "Back\\Slash", 100)
    _passer(db, "Backslash", 50)
    assert _names(db, "0%") == ["Joe 100% Real"]
    assert _names(db, "l_b") == ["Al_Bo Guy"]
    assert _names(db, "__") == []
    assert _names(db, "%%") == []
    assert _names(db, "k\\s") == ["Back\\Slash"]


def test_a_nul_in_the_query_matches_literally_so_nothing(db: PlayerDb) -> None:
    # SQLite's LIKE stops reading its pattern at a NUL, so unguarded 'a\0b'
    # would search '%a' (names ending in 'a') and '\0\0' would search '%'
    # (everyone). No name contains a NUL (#301 review).
    _passer(db, "Tua Tagovailoa", 300)
    _passer(db, "Josh Allen", 200)
    assert _names(db, "a\x00b") == []
    assert _names(db, "\x00\x00") == []


# --- who qualifies ------------------------------------------------------------


def test_only_passers_and_qb_starters_qualify(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    playoff_only = db.player("Smith Playoff Starter")
    db.start(db.game(2003, home, away, 7, 3, season_type="postseason", week=19), home, playoff_only)
    zero_attempts = db.player("Smith No Attempts")
    db.season(zero_attempts, 2003, **full_stats(attempts=0, passing_yards=0))
    db.season(zero_attempts, 2004, season_type="postseason", **full_stats(attempts=0))
    db.player("Smith No Rows")
    postseason_passer = db.player("Smith Postseason Passer")
    db.season(postseason_passer, 2003, season_type="postseason", **full_stats(attempts=1))
    assert _names(db, "smith") == ["Smith Playoff Starter", "Smith Postseason Passer"]


def test_order_is_regular_yards_desc_none_last_then_name_then_id(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    _passer(db, "Qb Low", 10)
    _passer(db, "Qb High", 900)
    # Same yards: display_name breaks the tie.
    _passer(db, "Qb Mid Zed", 500)
    _passer(db, "Qb Mid Abe", 500)
    # Same name and yards: player_id breaks it (inserted high id first).
    twin_high = db.player("Qb Twin", player_id=9_002)
    db.season(twin_high, 2000, **full_stats(passing_yards=500))
    twin_low = db.player("Qb Twin", player_id=9_001)
    db.season(twin_low, 2000, **full_stats(passing_yards=500))
    # No regular-season yards at all: postseason only, a regular start without a
    # season row, and a regular season row whose yards weren't tracked.
    playoff = db.player("Qb Aaa Playoff")
    db.season(playoff, 2000, season_type="postseason", **full_stats(passing_yards=5000))
    starter = db.player("Qb Bbb Starter")
    db.start(db.game(2000, home, away, 1, 0), home, starter)
    untracked = _passer(db, "Qb Ccc Untracked", None)
    # A zero is a number, not None: it sorts above the None rows.
    _passer(db, "Qb Zero", 0)

    rows = search_players(conn_of(db), sport="nfl", query="qb", limit=20).rows

    assert [(r.display_name, r.player_id) for r in rows] == [
        ("Qb High", rows[0].player_id),
        ("Qb Mid Abe", rows[1].player_id),
        ("Qb Mid Zed", rows[2].player_id),
        ("Qb Twin", 9_001),
        ("Qb Twin", 9_002),
        ("Qb Low", rows[5].player_id),
        ("Qb Zero", rows[6].player_id),
        ("Qb Aaa Playoff", playoff),
        ("Qb Bbb Starter", starter),
        ("Qb Ccc Untracked", untracked),
    ]


def test_a_row_carries_identity_and_the_season_span_across_season_types(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Span Guy", position="QB")
    db.season(p, 2003, **full_stats())
    db.season(p, 2005, season_type="postseason", **full_stats())
    # Earliest season is a postseason start with no season row.
    db.start(db.game(2001, home, away, 3, 7, season_type="postseason", week=19), away, p)
    other = db.player("Span Other", position=None)
    db.season(other, 2010, **full_stats())

    rows = search_players(conn_of(db), sport="nfl", query="span").rows

    assert rows == [
        PlayerSearchRow(p, "Span Guy", "QB", 2001, 2005),
        PlayerSearchRow(other, "Span Other", None, 2010, 2010),
    ]


def test_results_are_scoped_to_the_sport(db: PlayerDb) -> None:
    home, away = db.team("Home", sport="cfb"), db.team("Away", sport="cfb")
    pro = _passer(db, "Shared Name Pro", 100)
    college = db.player("Shared Name College", sport="cfb")
    db.season(college, 2000, sport="cfb", **full_stats(passing_yards=9999))
    college_starter = db.player("Shared Name Cfb Starter", sport="cfb")
    db.start(db.game(2000, home, away, 1, 0, sport="cfb"), home, college_starter, sport="cfb")
    conn = conn_of(db)

    assert [r.player_id for r in search_players(conn, sport="nfl", query="shared").rows] == [pro]
    assert [r.display_name for r in search_players(conn, sport="cfb", query="shared").rows] == [
        "Shared Name College",
        "Shared Name Cfb Starter",
    ]
