"""`PlayerCoverage` on careers, leaders rows and search rows (#446, epic #443)
on a small synthetic db: how much of a player's career the db holds."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import PlayerCoverage
from cfb_strength.players import (
    get_player_career,
    get_player_comparison,
    get_player_leaders,
    search_players,
)
from tests.test_players_support import PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _floor(db: PlayerDb, first: int = 1999, last: int = 2003) -> None:
    """Another player whose regular-season rows set the db's data span."""
    p = db.player("Span Setter", position="WR")
    db.season(p, first, **full_stats())
    db.season(p, last, **full_stats())


def _coverage(db: PlayerDb, player_id: int) -> PlayerCoverage:
    return get_player_career(conn_of(db), sport="nfl", player_id=player_id).coverage


def test_a_career_begun_before_the_data_is_cut_off_before(db: PlayerDb) -> None:
    _floor(db)
    # His own lines start a year after the data does (1999 missed), so the
    # data span can only be the db's, not his.
    p = db.player("Old Timer", career=(1990, 2002))
    for season in (2000, 2001, 2002):
        db.season(p, season, **full_stats())

    cov = _coverage(db, p)

    assert cov == PlayerCoverage(
        career_first_season=1990,
        career_last_season=2002,
        data_first_season=1999,
        data_last_season=2003,
        covered_first_season=2000,
        covered_last_season=2002,
        covered_seasons=3,
    )
    assert cov.career_seasons == 13
    assert cov.cut_off_before is True
    assert cov.cut_off_after is False
    assert cov.cut_off is True


def test_a_career_inside_the_data_span_is_not_cut_off(db: PlayerDb) -> None:
    _floor(db)
    # A rookie season with no stat line and a final one the data ends before
    # the source does not: both ends sit inside the db's 1999-2003, so the
    # career is whole even though his own lines are 2001-2002.
    p = db.player("Whole Career", career=(2000, 2003))
    db.season(p, 2001, **full_stats())
    db.season(p, 2002, **full_stats())

    cov = _coverage(db, p)

    assert (cov.data_first_season, cov.data_last_season) == (1999, 2003)
    assert (cov.covered_first_season, cov.covered_last_season, cov.covered_seasons) == (
        2001,
        2002,
        2,
    )
    assert cov.career_seasons == 4
    assert cov.cut_off_before is False
    assert cov.cut_off_after is False
    assert cov.cut_off is False


def test_a_null_source_span_claims_nothing(db: PlayerDb) -> None:
    _floor(db)
    p = db.player("No Span")
    db.season(p, 1999, **full_stats())

    cov = _coverage(db, p)

    assert (cov.career_first_season, cov.career_last_season) == (None, None)
    assert cov.career_seasons is None
    assert (cov.data_first_season, cov.data_last_season) == (1999, 2003)
    assert cov.cut_off_before is False
    assert cov.cut_off_after is False
    assert cov.cut_off is False


def test_a_career_running_past_the_data_is_cut_off_after(db: PlayerDb) -> None:
    _floor(db)
    p = db.player("Still Active", career=(2002, 2010))
    db.season(p, 2002, **full_stats())
    db.season(p, 2003, **full_stats())

    cov = _coverage(db, p)

    assert cov.cut_off_before is False
    assert cov.cut_off_after is True
    assert cov.cut_off is True
    assert cov.career_seasons == 9
    assert cov.covered_seasons == 2


def test_the_data_span_is_none_without_regular_season_rows(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Playoff Only", career=(1990, 2001))
    db.season(p, 2000, season_type="postseason", **full_stats())
    db.start(db.game(2001, home, away, 7, 3), home, p)

    cov = _coverage(db, p)

    assert (cov.data_first_season, cov.data_last_season) == (None, None)
    assert cov.cut_off is False
    assert (cov.covered_first_season, cov.covered_last_season, cov.covered_seasons) == (
        2000,
        2001,
        2,
    )


def test_the_data_span_is_the_sports_regular_season_rows_only(db: PlayerDb) -> None:
    _floor(db, 1999, 2003)
    # A later postseason row and another sport's rows don't move the span.
    late = db.player("Late Playoff", position="RB")
    db.season(late, 2004, season_type="postseason", **full_stats())
    college = db.player("College Guy", sport="cfb")
    db.season(college, 1950, sport="cfb", **full_stats())
    db.season(college, 2030, sport="cfb", **full_stats())
    p = db.player("Measured", career=(1998, 2000))
    db.season(p, 1999, **full_stats())

    cov = _coverage(db, p)

    assert (cov.data_first_season, cov.data_last_season) == (1999, 2003)


def test_a_postseason_only_season_and_a_start_only_season_count_as_covered(
    db: PlayerDb,
) -> None:
    _floor(db)
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Mixed Lines", career=(1999, 2002))
    db.season(p, 1999, **full_stats())
    db.season(p, 1999, season_type="postseason", **full_stats())
    db.season(p, 2000, season_type="postseason", **full_stats())
    db.start(db.game(2002, home, away, 7, 3, season_type="postseason", week=19), home, p)

    cov = _coverage(db, p)

    assert (cov.covered_first_season, cov.covered_last_season, cov.covered_seasons) == (
        1999,
        2002,
        3,
    )


def test_a_player_with_no_lines_has_no_covered_span(db: PlayerDb) -> None:
    _floor(db)
    p = db.player("Never Played", career=(1995, 1996))

    cov = _coverage(db, p)

    assert (cov.covered_first_season, cov.covered_last_season, cov.covered_seasons) == (
        None,
        None,
        0,
    )
    assert cov.cut_off_before is True


def test_coverage_is_the_same_on_career_leaders_search_and_comparison(db: PlayerDb) -> None:
    _floor(db)
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Same Everywhere", career=(1995, 2003))
    db.season(p, 1999, **full_stats())
    db.season(p, 2001, **full_stats())
    # A postseason-only season: on the regular board the row's own span stops
    # at 2001, but its coverage is the whole player's.
    db.season(p, 2002, season_type="postseason", **full_stats())
    db.start(db.game(2003, home, away, 7, 3), home, p)
    other = db.player("Same Other", career=(2000, 2000))
    db.season(other, 2000, **full_stats())
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p).coverage
    assert career == PlayerCoverage(1995, 2003, 1999, 2003, 1999, 2003, 4)

    for season_type in ("regular", "postseason"):
        leaders = get_player_leaders(conn, sport="nfl", season_type=season_type, limit=100)
        by_id = {r.player_id: r for r in leaders.rows}
        assert by_id[p].coverage == career

    regular_row = next(
        r for r in get_player_leaders(conn, sport="nfl", limit=100).rows if r.player_id == p
    )
    assert (regular_row.first_season, regular_row.last_season) == (1999, 2003)

    (search_row,) = search_players(conn, sport="nfl", query="same every").rows
    assert search_row.coverage == career
    assert (search_row.first_season, search_row.last_season) == (
        career.covered_first_season,
        career.covered_last_season,
    )

    comparison = get_player_comparison(conn, sport="nfl", a=p, b=other)
    assert comparison.a.coverage == career


def test_every_leaders_row_carries_its_own_players_coverage(db: PlayerDb) -> None:
    _floor(db)
    ids = []
    for i, span in enumerate([(1990, 2000), (2000, 2001), (None, None), (2001, 2012)]):
        pid = db.player(f"Board {i}", career=span)
        db.season(pid, 2000 if i != 3 else 2001, **full_stats(passing_yards=100 * (i + 1)))
        ids.append(pid)
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", limit=100).rows

    for row in rows:
        assert (
            row.coverage == get_player_career(conn, sport="nfl", player_id=row.player_id).coverage
        )
    by_id = {r.player_id: r.coverage for r in rows}
    assert [by_id[pid].cut_off for pid in ids] == [True, False, False, True]


def test_leaders_carry_the_data_span_even_on_an_empty_board(db: PlayerDb) -> None:
    _floor(db, 1999, 2003)
    conn = conn_of(db)
    # Nobody punted, so the punting board is empty; the span is the db's.
    board = get_player_leaders(conn, sport="nfl", category="punting", season_type="postseason")

    assert board.rows == []
    assert (board.data_first_season, board.data_last_season) == (1999, 2003)


def test_leaders_data_span_is_none_on_an_empty_db(db: PlayerDb) -> None:
    board = get_player_leaders(conn_of(db), sport="nfl")

    assert board.rows == []
    assert board.total == 0
    assert (board.data_first_season, board.data_last_season) == (None, None)
