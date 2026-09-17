"""`cfb_strength.players.get_player_leaders` on a small synthetic db (#296)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PLAYER_LEADERS_MAX_LIMIT,
    PLAYER_STAT_MAX_FIELDS,
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
    # over his seasons is partial and must not read as a career. The MAX
    # columns are the deliberate exception (#334): a long is the best of the
    # seasons that have one, so an untracked season skips it instead of
    # erasing it.
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Gap Year")
    db.season(p, 2000, games=16, **full_stats(attempts=10, passing_yards=100, fg_long=49))
    g = db.game(2001, home, away, 10, 3)
    db.start(g, home, p)
    conn = conn_of(db)

    row = get_player_leaders(conn, sport="nfl").rows[0]

    summed = {f.name: getattr(row.stats, f.name) for f in fields(PlayerStats)}
    assert all(summed.pop(name) is not None for name in PLAYER_STAT_MAX_FIELDS)
    assert set(summed.values()) == {None}
    assert row.stats.fg_long == 49
    assert row.games is None
    assert (row.first_season, row.last_season) == (2000, 2001)


# --- the MAX columns (#334) -------------------------------------------------


def test_a_leaders_rows_long_is_the_max_of_the_season_longs_not_their_sum(db: PlayerDb) -> None:
    # `totals_select` is shared, so a leaders row combines the
    # `PLAYER_STAT_MAX_FIELDS` columns the same way a career page does.
    p = db.player("Kicker", position="K")
    for season, fg_long, pt_long in [(2000, 53, 61), (2001, 47, 58), (2002, 52, 62)]:
        db.season(p, season, games=16, **full_stats(fg_long=fg_long, pt_long=pt_long))
    q = db.player("Part Time Kicker")
    db.season(q, 2000, games=16, **full_stats(attempts=1, fg_long=None, pt_long=None))
    db.season(q, 2001, games=16, **full_stats(attempts=1, fg_long=48, pt_long=55))
    conn = conn_of(db)

    rows = {r.display_name: r for r in get_player_leaders(conn, sport="nfl").rows}

    assert rows["Kicker"].stats.fg_long == 53
    assert rows["Kicker"].stats.pt_long == 62
    # A NULL season skips the MAX rather than poisoning it.
    assert rows["Part Time Kicker"].stats.fg_long == 48
    assert rows["Part Time Kicker"].stats.pt_long == 55
    # The columns beside them keep the null-aware SUM rule.
    assert rows["Kicker"].stats.fg_made == 3


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


# --- the rushing category (#312) ----------------------------------------------

RUSHING_SORTS = ("rushing_yards", "rushing_tds", "carries")


def test_rushing_qualify_rule_one_carry_qualifies_attempts_or_a_start_without_carries_do_not(
    db: PlayerDb,
) -> None:
    home, away = db.team("Home"), db.team("Away")
    one_carry = db.player("One Carry", position="WR")
    db.season(one_carry, 2000, **full_stats(attempts=0, carries=0))
    db.season(one_carry, 2001, **full_stats(attempts=0, carries=1))
    scrambler = db.player("Scrambler", position="QB")
    db.season(scrambler, 2000, **full_stats(attempts=30, carries=4))
    passer = db.player("Pocket Passer", position="QB")
    db.season(passer, 2000, **full_stats(attempts=30, carries=0))
    starter = db.player("Starter", position="QB")
    db.start(db.game(2000, home, away, 10, 3), home, starter)
    db.season(starter, 2000, **full_stats(attempts=0, carries=0))
    starts_only = db.player("Starts Only", position="QB")
    db.start(db.game(2000, home, away, 10, 3, week=2), home, starts_only)
    no_position = db.player("No Position", position=None)
    db.season(no_position, 2000, **full_stats(attempts=0, carries=2))
    conn = conn_of(db)

    rushing = get_player_leaders(conn, sport="nfl", category="rushing")
    passing = get_player_leaders(conn, sport="nfl")

    assert sorted(_names(rushing.rows)) == ["No Position", "One Carry", "Scrambler"]
    assert rushing.total == 3
    assert sorted(_names(passing.rows)) == ["Pocket Passer", "Scrambler", "Starter", "Starts Only"]
    assert passing.total == 4


def test_rushing_qualify_rule_is_per_season_type(db: PlayerDb) -> None:
    p = db.player("Regular Carries", position="RB")
    db.season(p, 2000, **full_stats(attempts=0, carries=10))
    db.season(p, 2000, season_type="postseason", **full_stats(attempts=0, carries=0))
    q = db.player("Postseason Carries", position="RB")
    db.season(q, 2001, **full_stats(attempts=0, carries=0))
    db.season(q, 2001, season_type="postseason", **full_stats(attempts=0, carries=3))
    conn = conn_of(db)

    regular = get_player_leaders(conn, sport="nfl", category="rushing")
    post = get_player_leaders(conn, sport="nfl", category="rushing", season_type="postseason")

    assert (_names(regular.rows), regular.total) == (["Regular Carries"], 1)
    assert (_names(post.rows), post.total, post.season_type) == (
        ["Postseason Carries"],
        1,
        "postseason",
    )


@pytest.mark.parametrize("sort", RUSHING_SORTS)
def test_each_rushing_sort_orders_descending_with_competition_ranks_and_the_tiebreak(
    db: PlayerDb, sort: str
) -> None:
    # The sorted column is 30 / 20 / 20 / 20 / 10; the other two rushing
    # columns run the opposite way, so only the named column gives this order.
    values = [("Dan", 10), ("Same Name", 20), ("Bob", 20), ("Ann", 30), ("Same Name", 20)]
    ids = []
    for name, value in values:
        pid = db.player(name, position="RB")
        ids.append(pid)
        stats = {s: 100 - value for s in RUSHING_SORTS}
        stats[sort] = value
        db.season(pid, 2000, **full_stats(attempts=0, **stats))
    same_first, same_second = ids[1], ids[4]
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="rushing", sort=sort)  # type: ignore[arg-type]  # parametrized over the Literal's values

    assert [(r.rank, r.display_name, r.player_id) for r in board.rows] == [
        (1, "Ann", ids[3]),
        (2, "Bob", ids[2]),
        (2, "Same Name", same_first),
        (2, "Same Name", same_second),
        (5, "Dan", ids[0]),
    ]
    assert (board.category, board.sort) == ("rushing", sort)


def test_sort_none_resolves_to_the_categorys_first_sort_and_is_echoed(db: PlayerDb) -> None:
    # Most yards and fewest carries/passing yards, so each default is visible.
    big_yards = db.player("Big Yards", position="QB")
    db.season(
        big_yards, 2000, **full_stats(attempts=5, passing_yards=10, carries=5, rushing_yards=900)
    )
    many_carries = db.player("Many Carries", position="QB")
    db.season(
        many_carries,
        2000,
        **full_stats(attempts=5, passing_yards=500, carries=300, rushing_yards=100),
    )
    conn = conn_of(db)

    rushing = get_player_leaders(conn, sport="nfl", category="rushing")
    rushing_explicit_none = get_player_leaders(conn, sport="nfl", category="rushing", sort=None)
    passing = get_player_leaders(conn, sport="nfl")
    passing_explicit_none = get_player_leaders(conn, sport="nfl", category="passing", sort=None)

    for board in (rushing, rushing_explicit_none):
        assert (board.category, board.sort) == ("rushing", "rushing_yards")
        assert _names(board.rows) == ["Big Yards", "Many Carries"]
    for board in (passing, passing_explicit_none):
        assert (board.category, board.sort) == ("passing", "passing_yards")
        assert _names(board.rows) == ["Many Carries", "Big Yards"]


@pytest.mark.parametrize(
    ("category", "sort"),
    [
        ("rushing", "wins"),
        ("rushing", "passing_yards"),
        ("rushing", "passing_tds"),
        ("passing", "carries"),
        ("passing", "rushing_yards"),
        ("receiving", None),
        ("receiving", "passing_yards"),
        ("rushing", "yards_per_carry"),
    ],
)
def test_a_sort_outside_the_category_or_an_unknown_category_raises(
    db: PlayerDb, category: str, sort: str | None
) -> None:
    p = db.player("Anyone")
    db.season(p, 2000, **full_stats(attempts=5, carries=5))
    with pytest.raises(ValueError):
        get_player_leaders(
            conn_of(db),
            sport="nfl",
            category=category,  # type: ignore[arg-type]  # deliberately outside the Literal
            sort=sort,  # type: ignore[arg-type]  # deliberately outside the Literal
        )


def test_a_rusher_with_zero_or_negative_yards_still_qualifies_and_ranks(db: PlayerDb) -> None:
    for name, yards in [("Loss", -7), ("Gain", 12), ("Nothing", 0)]:
        db.season(
            db.player(name, position="RB"),
            2000,
            **full_stats(attempts=0, carries=3, rushing_yards=yards),
        )
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="rushing")

    assert [(r.rank, r.display_name, r.stats.rushing_yards) for r in board.rows] == [
        (1, "Gain", 12),
        (2, "Nothing", 0),
        (3, "Loss", -7),
    ]
    assert board.total == 3


def test_rushing_total_and_paging_count_the_rushing_population(db: PlayerDb) -> None:
    for name, yards in [("Dan", 200), ("Eve", 100), ("Bob", 400), ("Ann", 500), ("Cat", 300)]:
        db.season(
            db.player(name, position="RB"),
            2000,
            **full_stats(attempts=0, carries=10, rushing_yards=yards),
        )
    for name in ("Passer One", "Passer Two"):
        db.season(db.player(name), 2000, **full_stats(attempts=20, carries=0, rushing_yards=0))
    conn = conn_of(db)

    page = get_player_leaders(
        conn, sport="nfl", category="rushing", sort="rushing_yards", limit=2, offset=1
    )
    last = get_player_leaders(conn, sport="nfl", category="rushing", limit=2, offset=4)
    past_end = get_player_leaders(conn, sport="nfl", category="rushing", limit=2, offset=50)

    assert (page.sport, page.category, page.season_type, page.sort, page.limit, page.offset) == (
        "nfl",
        "rushing",
        "regular",
        "rushing_yards",
        2,
        1,
    )
    assert [(r.rank, r.display_name) for r in page.rows] == [(2, "Bob"), (3, "Cat")]
    assert [(r.rank, r.display_name) for r in last.rows] == [(5, "Eve")]
    assert page.total == last.total == 5
    assert past_end.rows == [] and past_end.total == 5
    assert past_end.category == "rushing"
    assert get_player_leaders(conn, sport="nfl").total == 2


def test_every_rushing_leaders_row_equals_that_players_career_totals(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    back = db.player("Back", position="RB")
    qb = db.player("Running QB", position="QB")
    fb = db.player("Fullback", position="FB")
    partial = db.player("Partial", position="RB")
    db.season(back, 2000, games=16, **full_stats(attempts=0, carries=250, rushing_yards=1100))
    db.season(back, 2001, games=14, **full_stats(attempts=0, carries=200, rushing_yards=900))
    db.season(back, 2001, season_type="postseason", games=2, **full_stats(attempts=0, carries=40))
    db.season(qb, 2001, games=12, **full_stats(attempts=300, carries=60, rushing_yards=400))
    db.season(qb, 2002, games=10, **full_stats(attempts=250, carries=0, rushing_yards=0))
    for week, (hp, ap) in enumerate([(20, 10), (10, 10), (3, 9)], 1):
        db.start(db.game(2001, home, away, hp, ap, week=week), home, qb)
    db.start(db.game(2001, home, away, 7, 0, season_type="postseason", week=19), away, qb)
    db.season(qb, 2001, season_type="postseason", games=1, **full_stats(attempts=20, carries=5))
    db.season(fb, 2002, games=16, **full_stats(attempts=0, carries=12, rushing_yards=-3))
    db.season(partial, 2000, games=None, **full_stats(attempts=0, carries=8, rushing_tds=None))
    db.season(partial, 2001, games=5, **full_stats(attempts=0, carries=9, rushing_tds=2))
    conn = conn_of(db)

    for season_type in ("regular", "postseason"):
        for sort in (None, *RUSHING_SORTS):
            board = get_player_leaders(
                conn,
                sport="nfl",
                category="rushing",
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
    regular = get_player_leaders(conn, sport="nfl", category="rushing")
    assert sorted(_names(regular.rows)) == ["Back", "Fullback", "Partial", "Running QB"]
    by_name = {r.display_name: r for r in regular.rows}
    assert by_name["Running QB"].record == StarterRecord(1, 1, 1)
    assert by_name["Partial"].stats.rushing_tds is None and by_name["Partial"].games is None
