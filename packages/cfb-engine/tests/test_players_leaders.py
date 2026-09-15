"""`cfb_strength.players.get_player_leaders` on a small synthetic db (#296)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PLAYER_LEADERS_MAX_LIMIT,
    PlayerLeaderRow,
    PlayerStats,
    StarterRecord,
)
from cfb_strength.players import get_player_career, get_player_leaders
from tests.test_players_support import PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _names(rows: list[PlayerLeaderRow]) -> list[str]:
    return [r.display_name for r in rows]


# --- ranking, ties, paging --------------------------------------------------


def _tied_board(db: PlayerDb) -> dict[str, int]:
    """Yards: Ann 300, Bob 200, Cat 200, Dan 200, Eve 100. Bob/Cat/Dan tie."""
    ids = {}
    for name, yards in [("Dan", 200), ("Eve", 100), ("Bob", 200), ("Ann", 300), ("Cat", 200)]:
        ids[name] = db.player(name)
        db.season(ids[name], 2000, **full_stats(attempts=10, passing_yards=yards))
    return ids


def test_competition_rank_with_ties_across_a_page_boundary(db: PlayerDb) -> None:
    _tied_board(db)
    conn = conn_of(db)

    first = get_player_leaders(conn, sport="nfl", limit=2, offset=0)
    second = get_player_leaders(conn, sport="nfl", limit=2, offset=2)
    third = get_player_leaders(conn, sport="nfl", limit=2, offset=4)

    assert [(r.rank, r.display_name) for r in first.rows] == [(1, "Ann"), (2, "Bob")]
    # Cat and Dan share Bob's rank even though Bob is on the previous page.
    assert [(r.rank, r.display_name) for r in second.rows] == [(2, "Cat"), (2, "Dan")]
    assert [(r.rank, r.display_name) for r in third.rows] == [(5, "Eve")]
    assert first.total == second.total == third.total == 5


def test_ties_break_by_display_name_then_player_id(db: PlayerDb) -> None:
    b1 = db.player("Same Name")
    a = db.player("Aaron")
    b2 = db.player("Same Name")
    for pid in (b2, a, b1):
        db.season(pid, 2000, **full_stats(attempts=5, passing_tds=7))
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", sort="passing_tds").rows

    assert [(r.player_id, r.rank) for r in rows] == [(a, 1), (b1, 1), (b2, 1)]


def test_none_sort_values_sort_last_and_are_unranked(db: PlayerDb) -> None:
    known = db.player("Zed")
    db.season(known, 2000, **full_stats(attempts=5, passing_yards=10))
    untracked = db.player("Abe")
    db.season(untracked, 2000, **full_stats(attempts=5, passing_yards=None))
    starter_only = db.player("Al")
    home, away = db.team("Home"), db.team("Away")
    game = db.game(2000, home, away, 10, 3)
    db.start(game, home, starter_only)
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", sort="passing_yards").rows

    assert [(r.display_name, r.rank) for r in rows] == [("Zed", 1), ("Abe", None), ("Al", None)]
    assert rows[1].stats.passing_yards is None


def test_wins_board_sorts_by_starter_wins(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    two = db.player("Two Wins")
    one = db.player("One Win")
    for week, (starter, hp, ap) in enumerate([(two, 20, 10), (two, 21, 10), (one, 30, 0)], 1):
        g = db.game(2000, home, away, hp, ap, week=week)
        db.start(g, home, starter)
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", sort="wins").rows

    assert [(r.display_name, r.rank, r.record) for r in rows] == [
        ("Two Wins", 1, StarterRecord(2, 0, 0)),
        ("One Win", 2, StarterRecord(1, 0, 0)),
    ]


def test_qualify_rule_a_starter_with_no_attempts_qualifies_a_zero_attempt_player_does_not(
    db: PlayerDb,
) -> None:
    home, away = db.team("Home"), db.team("Away")
    starter = db.player("Starter")
    game = db.game(2000, home, away, 10, 3)
    db.start(game, home, starter)
    db.season(starter, 2000, **full_stats(attempts=0, passing_yards=0))
    zero = db.player("Zero Attempts", position="RB")
    db.season(zero, 2000, **full_stats(attempts=0, carries=20))
    db.season(zero, 2001, **full_stats(attempts=0, carries=20))
    passer = db.player("Passer")
    db.season(passer, 2000, **full_stats(attempts=0))
    db.season(passer, 2001, **full_stats(attempts=1))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl")

    assert sorted(_names(board.rows)) == ["Passer", "Starter"]
    assert board.total == 2


def test_qualify_rule_is_per_season_type(db: PlayerDb) -> None:
    p = db.player("Regular Only")
    db.season(p, 2000, **full_stats(attempts=10))
    db.season(p, 2000, season_type="postseason", **full_stats(attempts=0))
    conn = conn_of(db)

    assert _names(get_player_leaders(conn, sport="nfl").rows) == ["Regular Only"]
    post = get_player_leaders(conn, sport="nfl", season_type="postseason")
    assert (post.rows, post.total, post.season_type) == ([], 0, "postseason")


def test_total_and_paging_echo_the_request(db: PlayerDb) -> None:
    _tied_board(db)
    conn = conn_of(db)

    page = get_player_leaders(conn, sport="nfl", sort="passing_yards", limit=3, offset=1)
    past_end = get_player_leaders(conn, sport="nfl", limit=3, offset=50)

    assert (page.sport, page.season_type, page.sort, page.limit, page.offset) == (
        "nfl",
        "regular",
        "passing_yards",
        3,
        1,
    )
    assert _names(page.rows) == ["Bob", "Cat", "Dan"]
    assert page.total == 5
    assert past_end.rows == [] and past_end.total == 5


@pytest.mark.parametrize(
    ("limit", "offset"), [(0, 0), (-1, 0), (PLAYER_LEADERS_MAX_LIMIT + 1, 0), (10, -1)]
)
def test_limit_and_offset_out_of_range_raise(db: PlayerDb, limit: int, offset: int) -> None:
    with pytest.raises(ValueError):
        get_player_leaders(conn_of(db), sport="nfl", limit=limit, offset=offset)


def test_limit_bounds_are_inclusive(db: PlayerDb) -> None:
    conn = conn_of(db)
    assert get_player_leaders(conn, sport="nfl", limit=1).limit == 1
    assert get_player_leaders(conn, sport="nfl", limit=PLAYER_LEADERS_MAX_LIMIT).limit == 100


# --- sport scoping ----------------------------------------------------------


def test_rows_from_another_sport_never_leak_into_the_board(db: PlayerDb) -> None:
    nfl_home, nfl_away = db.team("NFL Home"), db.team("NFL Away")
    cfb_home, cfb_away = db.team("CFB Home", sport="cfb"), db.team("CFB Away", sport="cfb")
    pro = db.player("Pro")
    db.season(pro, 2000, team=nfl_home, **full_stats(attempts=10, passing_yards=100))
    g = db.game(2000, nfl_home, nfl_away, 10, 3)
    db.start(g, nfl_home, pro)
    # Rows in the same id space written under another sport: a cfb season row
    # and a cfb start carrying the NFL player's id, and a cfb-only player.
    db.season(pro, 2001, team=cfb_home, sport="cfb", **full_stats(attempts=50, passing_yards=900))
    cg = db.game(2001, cfb_home, cfb_away, 40, 0, sport="cfb")
    db.start(cg, cfb_home, pro, sport="cfb")
    college = db.player("College", sport="cfb")
    db.season(college, 2001, sport="cfb", **full_stats(attempts=50, passing_yards=5000))
    conn = conn_of(db)

    nfl = get_player_leaders(conn, sport="nfl")
    cfb = get_player_leaders(conn, sport="cfb")

    assert _names(nfl.rows) == ["Pro"] and nfl.total == 1
    row = nfl.rows[0]
    assert row.stats.passing_yards == 100
    assert (row.first_season, row.last_season, row.games) == (2000, 2000, 1)
    assert row.record == StarterRecord(1, 0, 0)
    assert _names(cfb.rows) == ["College"]


# --- the NULL rule ----------------------------------------------------------


def test_one_null_season_makes_that_total_none_and_leaves_the_others(db: PlayerDb) -> None:
    p = db.player("Partial")
    db.season(p, 2000, games=16, **full_stats(attempts=10, passing_yards=100, sacks_suffered=3))
    db.season(p, 2001, games=None, **full_stats(attempts=10, passing_yards=50, sacks_suffered=None))
    conn = conn_of(db)

    row = get_player_leaders(conn, sport="nfl").rows[0]

    assert row.stats.sacks_suffered is None
    assert row.games is None
    assert row.stats.passing_yards == 150
    assert row.stats.attempts == 20


def test_all_zero_stat_stays_zero(db: PlayerDb) -> None:
    p = db.player("Zeroes")
    db.season(p, 2000, **full_stats(attempts=1, rushing_tds=0))
    db.season(p, 2001, **full_stats(attempts=1, rushing_tds=0))
    row = get_player_leaders(conn_of(db), sport="nfl").rows[0]
    assert row.stats.rushing_tds == 0


def test_no_season_rows_makes_every_total_and_games_none(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Starts Only")
    g = db.game(2000, home, away, 10, 3)
    db.start(g, home, p)
    conn = conn_of(db)

    row = get_player_leaders(conn, sport="nfl").rows[0]

    assert row.stats == PlayerStats()
    assert row.games is None
    assert row.record == StarterRecord(1, 0, 0)
    assert (row.first_season, row.last_season) == (2000, 2000)


def test_a_start_only_season_makes_the_career_total_none(db: PlayerDb) -> None:
    # A season he started but has no stat row for is untracked, so a total
    # over his seasons is partial and must not read as a career.
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Gap Year")
    db.season(p, 2000, games=16, **full_stats(attempts=10, passing_yards=100))
    g = db.game(2001, home, away, 10, 3)
    db.start(g, home, p)
    conn = conn_of(db)

    row = get_player_leaders(conn, sport="nfl").rows[0]

    assert row.stats == PlayerStats()
    assert row.games is None
    assert (row.first_season, row.last_season) == (2000, 2001)


# --- W-L-T ------------------------------------------------------------------


def test_record_counts_a_tie_from_either_side_and_skips_incomplete_and_null_scores(
    db: PlayerDb,
) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Starter")
    q = db.player("Other Side")
    results = [
        (20, 10, True),  # p wins at home
        (10, 20, True),  # p loses at home
        (17, 17, True),  # tie
        (24, 3, False),  # not completed, though scored: excluded
        (None, None, True),  # completed with no scores: excluded
        (7, None, True),  # one score missing: excluded
    ]
    for week, (hp, ap, completed) in enumerate(results, 1):
        g = db.game(2000, home, away, hp, ap, week=week, completed=completed)
        db.start(g, home, p)
        db.start(g, away, q)
    conn = conn_of(db)

    rows = {r.display_name: r for r in get_player_leaders(conn, sport="nfl", sort="wins").rows}

    assert rows["Starter"].record == StarterRecord(wins=1, losses=1, ties=1)
    assert rows["Other Side"].record == StarterRecord(wins=1, losses=1, ties=1)
    assert rows["Starter"].record.starts == 3


def test_record_is_per_season_type(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Starter")
    db.start(db.game(2000, home, away, 20, 10), home, p)
    db.start(db.game(2000, home, away, 20, 10, season_type="postseason", week=19), away, p)
    conn = conn_of(db)

    regular = get_player_leaders(conn, sport="nfl", sort="wins").rows[0]
    post = get_player_leaders(conn, sport="nfl", sort="wins", season_type="postseason").rows[0]

    assert regular.record == StarterRecord(1, 0, 0)
    assert post.record == StarterRecord(0, 1, 0)


# --- the seam with get_player_career ----------------------------------------


def test_every_leaders_row_equals_that_players_career_totals(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a = db.player("Alpha")
    b = db.player("Bravo")
    c = db.player("Charlie")
    db.season(a, 2000, games=16, **full_stats(attempts=100, passing_yards=900, carries=None))
    db.season(a, 2001, games=15, **full_stats(attempts=90, passing_yards=800))
    db.season(a, 2001, season_type="postseason", games=2, **full_stats(attempts=40))
    db.season(b, 2001, games=12, **full_stats(attempts=10, passing_yards=80))
    for week, (hp, ap) in enumerate([(20, 10), (10, 10), (3, 9)], 1):
        g = db.game(2001, home, away, hp, ap, week=week)
        db.start(g, home, a)
        db.start(g, away, b)
    db.start(db.game(2002, home, away, 7, 0, week=1), home, c)
    db.start(db.game(2001, home, away, 7, 0, season_type="postseason", week=19), home, a)
    conn = conn_of(db)

    for season_type in ("regular", "postseason"):
        for sort in ("passing_yards", "passing_tds", "wins"):
            board = get_player_leaders(
                conn,
                sport="nfl",
                season_type=season_type,  # type: ignore[arg-type]  # loop over the Literal's values
                sort=sort,  # type: ignore[arg-type]  # loop over the Literal's values
            )
            assert board.rows
            for row in board.rows:
                career = get_player_career(conn, sport="nfl", player_id=row.player_id)
                totals = career.regular_season if season_type == "regular" else career.postseason
                assert totals is not None
                assert (row.display_name, row.position) == (career.display_name, career.position)
                assert row.games == totals.games
                assert row.record == totals.record
                assert row.stats == totals.stats
                lines = [s for s in career.seasons if s.season_type == season_type]
                assert (row.first_season, row.last_season) == (lines[0].season, lines[-1].season)


def test_player_leader_row_stats_are_a_full_player_stats(db: PlayerDb) -> None:
    p = db.player("All Columns")
    values = {f.name: i + 1 for i, f in enumerate(fields(PlayerStats))}
    db.season(p, 2000, **values)
    row = get_player_leaders(conn_of(db), sport="nfl").rows[0]
    assert row.stats == PlayerStats(**values)
