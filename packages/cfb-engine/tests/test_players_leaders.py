"""`cfb_strength.players.get_player_leaders` on a small synthetic db (#296)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS,
    PLAYER_LEADER_SORTS_BY_CATEGORY,
    PLAYER_LEADERS_MAX_LIMIT,
    PLAYER_STAT_MAX_FIELDS,
    PLAYER_STAT_REAL_FIELDS,
    PlayerLeaderRow,
    PlayerLeaders,
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


def test_a_leaders_row_skips_a_null_epa_season_row_but_not_a_start_only_season(
    db: PlayerDb,
) -> None:
    # `totals_select` is shared, so a leaders row combines the
    # `PLAYER_STAT_SPARSE_FIELDS` columns the same way a career page does
    # (#354): a NULL on a season row is skipped, a start-only season is not.
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Receiver", position="WR")
    for season, epa in ((2000, 1.5), (2001, None), (2002, 2.0)):
        db.season(p, season, **full_stats(attempts=1, rushing_epa=epa))
    q = db.player("Gap Year")
    db.season(q, 2000, **full_stats(attempts=1, rushing_epa=4.0))
    db.start(db.game(2001, home, away, 10, 3), home, q)
    conn = conn_of(db)

    rows = {r.display_name: r for r in get_player_leaders(conn, sport="nfl").rows}

    assert rows["Receiver"].stats.rushing_epa == 3.5
    assert rows["Gap Year"].stats.rushing_epa is None


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
    # The REAL columns (#354) get a fraction, so a read that truncated them
    # to an int would show here; 1.0 == 1 would hide it.
    values = {
        f.name: i + 1.5 if f.name in PLAYER_STAT_REAL_FIELDS else i + 1
        for i, f in enumerate(fields(PlayerStats))
    }
    db.season(p, 2000, **values)
    row = get_player_leaders(conn_of(db), sport="nfl").rows[0]
    assert row.stats == PlayerStats(**values)
    assert row.stats.def_sacks is not None and row.stats.def_sacks % 1 == 0.5


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
        ("passing", "receptions"),
        ("rushing", "receiving_yards"),
        ("receiving", "passing_yards"),
        ("receiving", "carries"),
        ("rushing", "yards_per_carry"),
        # Kicking and punting sorts stay on their own boards (#315).
        ("kicking", "pt_yards"),
        ("kicking", "receptions"),
        ("punting", "fg_made"),
        ("punting", "fg_pct"),
        ("passing", "fg_pct"),
        ("receiving", "fg_made_50_plus"),
        ("rushing", "pt_net_yards"),
        ("kicking", "pat_pct"),
        # Defense sorts stay on their own board, and other boards' sorts off
        # it (#317).
        ("defense", "passing_yards"),
        ("defense", "fg_made"),
        ("defense", "def_qb_hits"),
        ("passing", "def_sacks"),
        ("rushing", "def_tackles_solo"),
        ("kicking", "def_interceptions"),
        # An unknown category, which `receiving` (#314), `kicking` (#315)
        # and then `defense` (#317) used to stand for here before each was
        # made real.
        ("special_teams", None),
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


# --- the receiving category (#314) ------------------------------------------

RECEIVING_SORTS = ("receiving_yards", "receiving_tds", "receptions")


def test_receiving_qualify_rule_one_target_qualifies_even_with_no_catches(db: PlayerDb) -> None:
    # The settled rule (#314) is `targets > 0`, not `receptions > 0`: on the
    # committed NFL fixture 24 players in 1999 and 18 in 2023 were thrown to
    # and caught nothing, and every one of them belongs on the board with 0
    # receptions rather than missing from it.
    home, away = db.team("Home"), db.team("Away")
    dropped = db.player("Caught Nothing", position="WR")
    db.season(dropped, 2000, **full_stats(attempts=0, carries=0, targets=3, receptions=0))
    caught = db.player("Caught Some", position="WR")
    db.season(caught, 2000, **full_stats(attempts=0, carries=0, targets=5, receptions=4))
    db.season(
        db.player("Runner Only", position="RB"),
        2000,
        **full_stats(attempts=0, carries=20, targets=0, receptions=0),
    )
    passer = db.player("Pocket Passer", position="QB")
    db.season(passer, 2000, **full_stats(attempts=30, carries=0, targets=0, receptions=0))
    starts_only = db.player("Starts Only", position="QB")
    db.start(db.game(2000, home, away, 10, 3), home, starts_only)
    later = db.player("Targeted Later", position="TE")
    db.season(later, 2000, **full_stats(attempts=0, carries=0, targets=0, receptions=0))
    db.season(later, 2001, **full_stats(attempts=0, carries=0, targets=1, receptions=0))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")

    assert sorted(_names(board.rows)) == ["Caught Nothing", "Caught Some", "Targeted Later"]
    assert board.total == 3
    by_name = {r.display_name: r for r in board.rows}
    assert by_name["Caught Nothing"].stats.receptions == 0
    assert by_name["Caught Nothing"].stats.targets == 3
    assert by_name["Targeted Later"].stats.receptions == 0
    # The other two boards are untouched by the receiving rule.
    assert sorted(_names(get_player_leaders(conn, sport="nfl").rows)) == [
        "Pocket Passer",
        "Starts Only",
    ]
    assert sorted(_names(get_player_leaders(conn, sport="nfl", category="rushing").rows)) == [
        "Runner Only"
    ]


def test_a_season_with_both_targets_and_receptions_null_never_qualifies(db: PlayerDb) -> None:
    # `NULL OR NULL` is NULL, not true, so a season the source tracked
    # neither column for keeps a player off the board however much other
    # receiving yardage the row carries. Either column on its own is enough,
    # which is what makes the rule survive an era that tracked only one.
    neither = db.player("Neither Tracked", position="WR")
    db.season(
        neither,
        2000,
        **full_stats(attempts=0, targets=None, receptions=None, receiving_yards=100),
    )
    no_targets = db.player("Receptions Only", position="WR")
    db.season(no_targets, 2000, **full_stats(attempts=0, targets=None, receptions=40))
    no_receptions = db.player("Targets Only", position="WR")
    db.season(no_receptions, 2000, **full_stats(attempts=0, targets=60, receptions=None))
    both = db.player("Both Tracked", position="WR")
    db.season(both, 2000, **full_stats(attempts=0, targets=60, receptions=40))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")

    assert sorted(_names(board.rows)) == ["Both Tracked", "Receptions Only", "Targets Only"]
    assert board.total == 3


def test_receiving_qualify_rule_is_per_season_type(db: PlayerDb) -> None:
    p = db.player("Regular Targets", position="WR")
    db.season(p, 2000, **full_stats(attempts=0, targets=10))
    db.season(p, 2000, season_type="postseason", **full_stats(attempts=0, targets=0, receptions=0))
    q = db.player("Postseason Targets", position="TE")
    db.season(q, 2001, **full_stats(attempts=0, targets=0, receptions=0))
    db.season(q, 2001, season_type="postseason", **full_stats(attempts=0, targets=2))
    conn = conn_of(db)

    regular = get_player_leaders(conn, sport="nfl", category="receiving")
    post = get_player_leaders(conn, sport="nfl", category="receiving", season_type="postseason")

    assert (_names(regular.rows), regular.total) == (["Regular Targets"], 1)
    assert (_names(post.rows), post.total, post.season_type) == (
        ["Postseason Targets"],
        1,
        "postseason",
    )


@pytest.mark.parametrize("sort", RECEIVING_SORTS)
def test_each_receiving_sort_orders_descending_with_competition_ranks_and_the_tiebreak(
    db: PlayerDb, sort: str
) -> None:
    # The sorted column is 30 / 20 / 20 / 20 / 10; the other two receiving
    # columns run the opposite way, so only the named column gives this order.
    values = [("Dan", 10), ("Same Name", 20), ("Bob", 20), ("Ann", 30), ("Same Name", 20)]
    ids = []
    for name, value in values:
        pid = db.player(name, position="WR")
        ids.append(pid)
        stats = {s: 100 - value for s in RECEIVING_SORTS}
        stats[sort] = value
        db.season(pid, 2000, **full_stats(attempts=0, targets=100, **stats))
    same_first, same_second = ids[1], ids[4]
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving", sort=sort)  # type: ignore[arg-type]  # parametrized over the Literal's values

    assert [(r.rank, r.display_name, r.player_id) for r in board.rows] == [
        (1, "Ann", ids[3]),
        (2, "Bob", ids[2]),
        (2, "Same Name", same_first),
        (2, "Same Name", same_second),
        (5, "Dan", ids[0]),
    ]
    assert (board.category, board.sort) == ("receiving", sort)


def test_receiving_yards_and_receptions_disagree_at_the_top_of_a_real_1999_board(
    db: PlayerDb,
) -> None:
    # 1999 NFL regular season, from the committed fixture: Jimmy Smith caught
    # more passes than Marvin Harrison (116 to 115) for fewer yards (1636 to
    # 1663), so yards and receptions genuinely give different boards.
    harrison = db.player("Marvin Harrison", position="WR")
    db.season(
        harrison,
        1999,
        games=16,
        **full_stats(
            attempts=0, targets=193, receptions=115, receiving_yards=1663, receiving_tds=12
        ),
    )
    smith = db.player("Jimmy Smith", position="WR")
    db.season(
        smith,
        1999,
        games=16,
        **full_stats(
            attempts=0, targets=177, receptions=116, receiving_yards=1636, receiving_tds=6
        ),
    )
    conn = conn_of(db)

    by_yards = get_player_leaders(conn, sport="nfl", category="receiving", sort="receiving_yards")
    by_receptions = get_player_leaders(conn, sport="nfl", category="receiving", sort="receptions")
    by_tds = get_player_leaders(conn, sport="nfl", category="receiving", sort="receiving_tds")

    assert _names(by_yards.rows) == ["Marvin Harrison", "Jimmy Smith"]
    assert _names(by_receptions.rows) == ["Jimmy Smith", "Marvin Harrison"]
    assert _names(by_tds.rows) == ["Marvin Harrison", "Jimmy Smith"]
    assert [r.stats.receiving_yards for r in by_yards.rows] == [1663, 1636]
    assert [r.stats.receptions for r in by_receptions.rows] == [116, 115]


def test_receiving_sort_none_resolves_to_receiving_yards_and_is_echoed(db: PlayerDb) -> None:
    # Most yards and fewest catches, so the default is visible in the order.
    big_yards = db.player("Big Yards", position="WR")
    db.season(
        big_yards,
        2000,
        **full_stats(attempts=0, targets=90, receptions=50, receiving_yards=1400),
    )
    many_catches = db.player("Many Catches", position="WR")
    db.season(
        many_catches,
        2000,
        **full_stats(attempts=0, targets=120, receptions=95, receiving_yards=800),
    )
    conn = conn_of(db)

    default = get_player_leaders(conn, sport="nfl", category="receiving")
    explicit_none = get_player_leaders(conn, sport="nfl", category="receiving", sort=None)

    for board in (default, explicit_none):
        assert (board.category, board.sort) == ("receiving", "receiving_yards")
        assert _names(board.rows) == ["Big Yards", "Many Catches"]


def test_the_receiving_board_ranks_every_position_and_reports_it(db: PlayerDb) -> None:
    # Epic #311 decision 1: a category, not a position. On the committed NFL
    # fixture, regular-season seasons with a catch are WR 364, RB 244, TE 204,
    # FB 39 and QB 13, so backs and quarterbacks are ordinary board entries.
    for name, position, yards in [
        ("Wideout", "WR", 1200),
        ("Back", "RB", 600),
        ("Tight End", "TE", 800),
        ("Fullback", "FB", 90),
        ("Quarterback", "QB", 30),
        ("No Position", None, 45),
    ]:
        pid = db.player(name, position=position)
        db.season(
            pid, 2000, **full_stats(attempts=0, targets=10, receptions=5, receiving_yards=yards)
        )
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")

    assert [(r.display_name, r.position) for r in board.rows] == [
        ("Wideout", "WR"),
        ("Tight End", "TE"),
        ("Back", "RB"),
        ("Fullback", "FB"),
        ("No Position", None),
        ("Quarterback", "QB"),
    ]
    assert board.total == 6


def test_a_receiving_row_is_a_career_aggregate_spanning_its_seasons(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    wr = db.player("Three Seasons", position="WR")
    for season, targets, receptions, yards, tds in [
        (2000, 90, 55, 700, 4),
        (2001, 120, 80, 1100, 9),
        (2002, 60, 40, 500, 2),
    ]:
        db.season(
            wr,
            season,
            games=16,
            **full_stats(
                attempts=0,
                targets=targets,
                receptions=receptions,
                receiving_yards=yards,
                receiving_tds=tds,
            ),
        )
    db.season(
        wr,
        2001,
        season_type="postseason",
        games=2,
        **full_stats(attempts=0, targets=12, receptions=9, receiving_yards=140, receiving_tds=1),
    )
    partial = db.player("Partial", position="TE")
    db.season(
        partial,
        2003,
        games=None,
        **full_stats(attempts=0, targets=20, receptions=12, receiving_yards=None),
    )
    db.season(
        partial,
        2004,
        games=9,
        **full_stats(attempts=0, targets=30, receptions=18, receiving_yards=210),
    )
    rb = db.player("Receiving Back", position="RB")
    db.season(
        rb,
        2002,
        games=15,
        **full_stats(
            attempts=0,
            carries=200,
            targets=40,
            receptions=31,
            receiving_yards=280,
            receiving_tds=1,
        ),
    )
    db.start(db.game(2002, home, away, 20, 10), home, rb)
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")
    by_name = {r.display_name: r for r in board.rows}

    career = by_name["Three Seasons"]
    assert (career.first_season, career.last_season) == (2000, 2002)
    assert career.stats.targets == 270
    assert career.stats.receptions == 175
    assert career.stats.receiving_yards == 2300
    assert career.stats.receiving_tds == 15
    assert career.games == 48
    # A QB starter record, 0-0-0, exactly as on the rushing board.
    assert career.record == StarterRecord(0, 0, 0)
    # An untracked season leaves the total None rather than a partial career.
    assert by_name["Partial"].stats.receiving_yards is None
    assert by_name["Partial"].stats.receptions == 30
    assert by_name["Partial"].games is None
    # The same aggregate the career page reads.
    for row in board.rows:
        totals = get_player_career(conn, sport="nfl", player_id=row.player_id).regular_season
        assert totals is not None
        assert row.stats == totals.stats
        assert row.games == totals.games
        assert row.record == totals.record


def test_a_2003_2008_shaped_season_with_catches_but_no_targets_still_qualifies(
    db: PlayerDb,
) -> None:
    # nflverse writes `targets` as a literal 0 for 2003-2008 -- 3,528 to 3,647
    # players a year caught a pass with targets 0, and there is no blank cell
    # anywhere in 1999-2025 to tell "not tracked" from "never thrown to".
    # Measured on the full 1999-2025 build, a bare `targets > 0` drops 303
    # careers with a reception (5,426 catches, 54,465 yards), the largest
    # being Shaun McDonald's, whose whole career sits inside the gap.
    mcdonald = db.player("Shaun McDonald", position="WR")
    for season, receptions, yards, tds in [
        (2003, 15, 168, 1),
        (2007, 79, 943, 6),
        (2008, 46, 511, 1),
    ]:
        db.season(
            mcdonald,
            season,
            games=16,
            **full_stats(
                attempts=0,
                carries=0,
                targets=0,
                receptions=receptions,
                receiving_yards=yards,
                receiving_tds=tds,
            ),
        )
    tracked_era = db.player("Tracked Era", position="WR")
    db.season(
        tracked_era,
        2010,
        games=16,
        **full_stats(attempts=0, carries=0, targets=120, receptions=80, receiving_yards=1000),
    )
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")
    by_name = {r.display_name: r for r in board.rows}

    assert sorted(_names(board.rows)) == ["Shaun McDonald", "Tracked Era"]
    assert board.total == 2
    row = by_name["Shaun McDonald"]
    assert (row.first_season, row.last_season) == (2003, 2008)
    assert (row.stats.receptions, row.stats.receiving_yards, row.stats.receiving_tds) == (
        140,
        1622,
        8,
    )
    # The upstream zero is reported as it was ingested, not invented.
    assert row.stats.targets == 0
    assert row.rank == 1
    # Every sort reaches him, not just the default.
    for sort in RECEIVING_SORTS:
        board_by_sort = get_player_leaders(
            conn,
            sport="nfl",
            category="receiving",
            sort=sort,  # type: ignore[arg-type]  # loop over the Literal's values
        )
        assert "Shaun McDonald" in _names(board_by_sort.rows)


def test_a_player_never_thrown_to_is_off_the_receiving_board_whatever_else_he_did(
    db: PlayerDb,
) -> None:
    # The negative side of the rule, which is what keeps `targets > 0 OR
    # receptions > 0` from drifting into "every player": neither column
    # positive means no board, however full the rest of the stat line is.
    home, away = db.team("Home"), db.team("Away")
    db.season(
        db.player("Pure Runner", position="RB"),
        2000,
        **full_stats(attempts=0, carries=300, rushing_yards=1400, targets=0, receptions=0),
    )
    db.season(
        db.player("Pocket Passer", position="QB"),
        2000,
        **full_stats(attempts=500, passing_yards=4000, carries=10, targets=0, receptions=0),
    )
    db.season(
        db.player("Kicker", position="K"),
        2000,
        **full_stats(attempts=0, carries=0, fg_made=30, fg_att=35, targets=0, receptions=0),
    )
    starts_only = db.player("Starts Only", position="QB")
    db.start(db.game(2000, home, away, 20, 10), home, starts_only)
    receiver = db.player("One Catch", position="TE")
    db.season(receiver, 2000, **full_stats(attempts=0, carries=0, targets=0, receptions=1))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="receiving")

    assert _names(board.rows) == ["One Catch"]
    assert board.total == 1


# --- the kicking and punting categories (#315) --------------------------------

KICKING_SORTS = ("fg_made", "fg_pct", "fg_made_50_plus", "fg_long", "fg_att", "pat_made")
PUNTING_SORTS = ("pt_yards", "pt_net_yards", "pt_att", "pt_inside_20")
# The kicking sorts that are the `PlayerStats` column of the same name.
_KICKING_COLUMN_SORTS = ("fg_made", "fg_long", "fg_att", "pat_made")


def _no_kicks(**overrides: int | None) -> dict[str, int | None]:
    """`full_stats` with every kicking and punting column a real zero (and the
    longs blank, as nflverse leaves them with nothing made), so a line is on
    the kicking or punting board only when a test puts it there."""
    stats = full_stats(
        fg_made=0,
        fg_att=0,
        fg_long=None,
        fg_made_0_19=0,
        fg_made_20_29=0,
        fg_made_30_39=0,
        fg_made_40_49=0,
        fg_made_50_59=0,
        fg_made_60_=0,
        pat_made=0,
        pat_att=0,
        pt_att=0,
        pt_yards=0,
        pt_net_yards=0,
        pt_long=None,
        pt_inside_20=0,
    )
    stats.update(overrides)
    return stats


def _kicker(db: PlayerDb, name: str, made: int, att: int, *, season_type: str = "regular") -> int:
    pid = db.player(name, position="K")
    db.season(
        pid,
        2000,
        season_type=season_type,
        **_no_kicks(fg_made=made, fg_att=att, fg_made_30_39=made, fg_long=40 if made else None),
    )
    return pid


def test_kicking_qualifies_a_pat_only_and_a_fg_only_kicker_punting_one_punt(
    db: PlayerDb,
) -> None:
    pat_only = db.player("PAT Only", position="K")
    db.season(pat_only, 2000, **_no_kicks(pat_made=3, pat_att=3))
    fg_only = db.player("FG Only", position="K")
    db.season(fg_only, 2000, **_no_kicks(fg_made=0, fg_att=2))
    # A make-less PAT try still qualifies: the attempt is the rule.
    missed_pat = db.player("Missed PAT", position="P")
    db.season(missed_pat, 2000, **_no_kicks(pat_made=0, pat_att=1))
    punter = db.player("One Punt", position="P")
    db.season(punter, 2000, **_no_kicks(pt_att=1, pt_yards=40, pt_net_yards=35))
    neither = db.player("Neither", position="RB")
    db.season(neither, 2000, **_no_kicks(carries=200, rushing_yards=900))
    untracked = db.player("Untracked", position="K")
    db.season(untracked, 2000, **_no_kicks(fg_att=None, pat_att=None, pt_att=None))
    conn = conn_of(db)

    kicking = get_player_leaders(conn, sport="nfl", category="kicking")
    punting = get_player_leaders(conn, sport="nfl", category="punting")

    assert sorted(_names(kicking.rows)) == ["FG Only", "Missed PAT", "PAT Only"]
    assert kicking.total == 3
    assert (_names(punting.rows), punting.total) == (["One Punt"], 1)


def test_kicking_and_punting_qualify_per_season_type(db: PlayerDb) -> None:
    k = db.player("Regular Kicker", position="K")
    db.season(k, 2000, **_no_kicks(fg_made=1, fg_att=1))
    db.season(k, 2000, season_type="postseason", **_no_kicks())
    p = db.player("Playoff Punter", position="P")
    db.season(p, 2000, **_no_kicks())
    db.season(p, 2000, season_type="postseason", **_no_kicks(pt_att=4, pt_yards=170))
    conn = conn_of(db)

    def board(category: str, season_type: str) -> list[str]:
        return _names(
            get_player_leaders(
                conn,
                sport="nfl",
                category=category,  # type: ignore[arg-type]  # the Literal's values
                season_type=season_type,  # type: ignore[arg-type]  # the Literal's values
            ).rows
        )

    assert board("kicking", "regular") == ["Regular Kicker"]
    assert board("kicking", "postseason") == []
    assert board("punting", "regular") == []
    assert board("punting", "postseason") == ["Playoff Punter"]


def test_fg_pct_ranks_by_the_exact_ratio(db: PlayerDb) -> None:
    # 90/100 and 180/200 are the same ratio (the issue's 9/10 at a qualifying
    # volume), so they tie; 178/198 is 89/99, just below it.
    _kicker(db, "Ninety Of Hundred", 90, 100)
    _kicker(db, "Double", 180, 200)
    _kicker(db, "Eighty Nine Of Ninety Nine", 178, 198)
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_pct")

    assert [(r.rank, r.display_name) for r in board.rows] == [
        (1, "Double"),
        (1, "Ninety Of Hundred"),
        (3, "Eighty Nine Of Ninety Nine"),
    ]
    assert board.sort == "fg_pct"


def test_fg_pct_is_not_rounded_before_ranking(db: PlayerDb) -> None:
    # 200/201 = 0.99502... and 199/200 = 0.995 are both 0.995 at three
    # decimals; only the exact ratio puts Zed above Abe.
    _kicker(db, "Zed", 200, 201)
    _kicker(db, "Abe", 199, 200)
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_pct")

    assert [(r.rank, r.display_name) for r in board.rows] == [(1, "Zed"), (2, "Abe")]


@pytest.mark.parametrize(("season_type", "minimum"), [("regular", 100), ("postseason", 15)])
def test_fg_pct_board_needs_the_attempts_minimum_inclusive(
    db: PlayerDb, season_type: str, minimum: int
) -> None:
    assert PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS[season_type] == minimum  # type: ignore[index]  # the Literal's values
    # Perfect but one attempt short: it would top the board if it were on it.
    _kicker(db, "Just Short", minimum - 1, minimum - 1, season_type=season_type)
    _kicker(db, "Exactly Enough", minimum // 2, minimum, season_type=season_type)
    _kicker(db, "Volume", minimum // 4, minimum + 50, season_type=season_type)
    pat_only = db.player("PAT Only", position="K")
    db.season(pat_only, 2000, season_type=season_type, **_no_kicks(pat_made=40, pat_att=40))
    conn = conn_of(db)

    def board(sort: str, offset: int = 0) -> PlayerLeaders:
        return get_player_leaders(
            conn,
            sport="nfl",
            category="kicking",
            season_type=season_type,  # type: ignore[arg-type]  # parametrized over the Literal
            sort=sort,  # type: ignore[arg-type]  # the Literal's values
            offset=offset,
        )

    pct = board("fg_pct")
    assert [(r.rank, r.display_name) for r in pct.rows] == [(1, "Exactly Enough"), (2, "Volume")]
    assert pct.total == 2
    # A page past the end still counts only the kickers who meet it.
    past_end = board("fg_pct", offset=10)
    assert (past_end.rows, past_end.total) == ([], 2)
    # Every other kicking sort keeps the one-attempt rule.
    for sort in KICKING_SORTS:
        if sort != "fg_pct":
            assert board(sort).total == 4, sort


def test_the_fg_pct_minimum_counts_career_attempts_across_seasons(db: PlayerDb) -> None:
    pid = db.player("Two Seasons", position="K")
    db.season(pid, 2000, **_no_kicks(fg_made=50, fg_att=60))
    db.season(pid, 2001, **_no_kicks(fg_made=35, fg_att=40))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_pct")

    assert [(r.rank, r.display_name, r.stats.fg_made, r.stats.fg_att) for r in board.rows] == [
        (1, "Two Seasons", 85, 100)
    ]


def test_fg_made_50_plus_sums_both_long_buckets(db: PlayerDb) -> None:
    sixty_only = db.player("Sixty Only", position="K")
    db.season(sixty_only, 2000, **_no_kicks(fg_made=1, fg_att=1, fg_made_60_=1, fg_long=61))
    fifties = db.player("Fifties", position="K")
    db.season(fifties, 2000, **_no_kicks(fg_made=1, fg_att=1, fg_made_50_59=1, fg_long=52))
    db.season(fifties, 2001, **_no_kicks(fg_made=1, fg_att=1, fg_made_50_59=1, fg_long=55))
    both = db.player("Both", position="K")
    db.season(both, 2000, **_no_kicks(fg_made=1, fg_att=1, fg_made_50_59=1, fg_long=50))
    db.season(both, 2001, **_no_kicks(fg_made=1, fg_att=1, fg_made_60_=1, fg_long=63))
    short = db.player("Short", position="K")
    db.season(short, 2000, **_no_kicks(fg_made=5, fg_att=5, fg_made_40_49=5, fg_long=49))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_made_50_plus")

    assert [(r.rank, r.display_name) for r in board.rows] == [
        (1, "Both"),
        (1, "Fifties"),
        (3, "Sixty Only"),
        (4, "Short"),
    ]
    both_stats = board.rows[0].stats
    assert (both_stats.fg_made_50_59, both_stats.fg_made_60_) == (1, 1)


def test_a_null_long_bucket_makes_fg_made_50_plus_unranked(db: PlayerDb) -> None:
    known = db.player("Known", position="K")
    db.season(known, 2000, **_no_kicks(fg_made=1, fg_att=1, fg_made_50_59=1, fg_long=51))
    blank = db.player("Blank Sixty", position="K")
    db.season(blank, 2000, **_no_kicks(fg_made=3, fg_att=3, fg_made_50_59=3, fg_made_60_=None))
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_made_50_plus").rows

    assert [(r.rank, r.display_name) for r in rows] == [(1, "Known"), (None, "Blank Sixty")]
    assert rows[1].stats.fg_made_60_ is None


def test_a_kicker_with_no_make_has_no_long_is_unranked_and_sorts_last(db: PlayerDb) -> None:
    missed = db.player("Aaron Missed", position="K")
    db.season(missed, 2000, **_no_kicks(fg_made=0, fg_att=3))
    pat_only = db.player("Abe PAT Only", position="K")
    db.season(pat_only, 2000, **_no_kicks(pat_made=2, pat_att=2))
    long = db.player("Zed Long", position="K")
    db.season(long, 2000, **_no_kicks(fg_made=2, fg_att=2, fg_long=47))
    db.season(long, 2001, **_no_kicks(fg_made=0, fg_att=1))
    db.season(long, 2002, **_no_kicks(fg_made=1, fg_att=1, fg_long=52))
    conn = conn_of(db)

    rows = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_long").rows

    assert [(r.rank, r.display_name, r.stats.fg_long) for r in rows] == [
        (1, "Zed Long", 52),
        (None, "Aaron Missed", None),
        (None, "Abe PAT Only", None),
    ]


@pytest.mark.parametrize(
    ("category", "sort"),
    [("kicking", s) for s in _KICKING_COLUMN_SORTS] + [("punting", s) for s in PUNTING_SORTS],
)
def test_each_kicking_and_punting_column_sort_orders_descending_with_the_tiebreak(
    db: PlayerDb, category: str, sort: str
) -> None:
    # The sorted column is 30 / 20 / 20 / 20 / 10; every other column sort of
    # the category runs the opposite way, so only the named one gives this order.
    columns = _KICKING_COLUMN_SORTS if category == "kicking" else PUNTING_SORTS
    values = [("Dan", 10), ("Same Name", 20), ("Bob", 20), ("Ann", 30), ("Same Name", 20)]
    ids = []
    for name, value in values:
        pid = db.player(name, position="K")
        ids.append(pid)
        stats: dict[str, int | None] = {c: 100 - value for c in columns}
        stats[sort] = value
        db.season(pid, 2000, **_no_kicks(**stats))
    conn = conn_of(db)

    board = get_player_leaders(conn, sport="nfl", category=category, sort=sort)  # type: ignore[arg-type]  # parametrized over the Literal's values

    assert [(r.rank, r.display_name, r.player_id) for r in board.rows] == [
        (1, "Ann", ids[3]),
        (2, "Bob", ids[2]),
        (2, "Same Name", ids[1]),
        (2, "Same Name", ids[4]),
        (5, "Dan", ids[0]),
    ]
    assert (board.category, board.sort, board.total) == (category, sort, 5)


def test_every_kicking_and_punting_sort_resolves(db: PlayerDb) -> None:
    _kicker(db, "Kicker", 90, 100)
    punter = db.player("Punter", position="P")
    db.season(punter, 2000, **_no_kicks(pt_att=5, pt_yards=200, pt_net_yards=180))
    conn = conn_of(db)

    for category, sorts in (("kicking", KICKING_SORTS), ("punting", PUNTING_SORTS)):
        assert PLAYER_LEADER_SORTS_BY_CATEGORY[category] == sorts  # type: ignore[index]  # the Literal's values
        for sort in sorts:
            board = get_player_leaders(
                conn,
                sport="nfl",
                category=category,  # type: ignore[arg-type]  # the Literal's values
                sort=sort,  # type: ignore[arg-type]  # the Literal's values
            )
            assert (board.category, board.sort, board.total) == (category, sort, 1)
            assert board.rows[0].rank == 1


def test_kicking_and_punting_default_sorts_are_fg_made_and_pt_yards(db: PlayerDb) -> None:
    # Most makes but fewest attempts; most yards but fewest punts.
    _kicker(db, "Accurate", 30, 30)
    _kicker(db, "Busy", 20, 40)
    db.season(db.player("Long Leg", position="P"), 2000, **_no_kicks(pt_att=10, pt_yards=600))
    db.season(db.player("Many Punts", position="P"), 2000, **_no_kicks(pt_att=20, pt_yards=500))
    conn = conn_of(db)

    kicking = get_player_leaders(conn, sport="nfl", category="kicking")
    punting = get_player_leaders(conn, sport="nfl", category="punting", sort=None)

    assert (kicking.sort, _names(kicking.rows)) == ("fg_made", ["Accurate", "Busy"])
    assert (punting.sort, _names(punting.rows)) == ("pt_yards", ["Long Leg", "Many Punts"])


def test_every_kicking_and_punting_leaders_row_equals_that_players_career_totals(
    db: PlayerDb,
) -> None:
    kicker = db.player("Kicker", position="K")
    db.season(
        kicker,
        2000,
        games=16,
        **_no_kicks(fg_made=25, fg_att=30, fg_long=51, fg_made_50_59=1, pat_made=30, pat_att=31),
    )
    db.season(
        kicker,
        2001,
        games=16,
        **_no_kicks(fg_made=80, fg_att=90, fg_long=62, fg_made_60_=1, pat_made=40, pat_att=40),
    )
    db.season(
        kicker,
        2001,
        season_type="postseason",
        games=2,
        **_no_kicks(fg_made=15, fg_att=15, fg_long=44, pat_made=4, pat_att=4),
    )
    punter = db.player("Punter", position="P")
    db.season(
        punter,
        2000,
        games=16,
        **_no_kicks(pt_att=70, pt_yards=3100, pt_net_yards=2700, pt_long=66),
    )
    db.season(
        punter,
        2001,
        games=None,
        **_no_kicks(pt_att=60, pt_yards=2600, pt_net_yards=None, pt_long=58, pt_inside_20=20),
    )
    db.season(
        punter,
        2001,
        season_type="postseason",
        games=1,
        **_no_kicks(pt_att=4, pt_yards=170, pt_net_yards=150, pt_long=50, pt_inside_20=2),
    )
    conn = conn_of(db)

    checked = 0
    for season_type in ("regular", "postseason"):
        for category, sorts in (("kicking", KICKING_SORTS), ("punting", PUNTING_SORTS)):
            for sort in (None, *sorts):
                board = get_player_leaders(
                    conn,
                    sport="nfl",
                    category=category,  # type: ignore[arg-type]  # the Literal's values
                    season_type=season_type,  # type: ignore[arg-type]  # the Literal's values
                    sort=sort,  # type: ignore[arg-type]  # the Literal's values
                )
                for row in board.rows:
                    career = get_player_career(conn, sport="nfl", player_id=row.player_id)
                    totals = (
                        career.regular_season if season_type == "regular" else career.postseason
                    )
                    assert totals is not None
                    assert row.games == totals.games
                    assert row.stats == totals.stats
                    checked += 1
    assert checked == 2 * (len(KICKING_SORTS) + 1 + len(PUNTING_SORTS) + 1)
    (kick,) = get_player_leaders(conn, sport="nfl", category="kicking", sort="fg_pct").rows
    assert (kick.stats.fg_made, kick.stats.fg_att, kick.stats.fg_long) == (105, 120, 62)
    (punt,) = get_player_leaders(conn, sport="nfl", category="punting").rows
    # A NULL season stays NULL in the total; the long is a MAX, not a sum.
    assert (punt.stats.pt_yards, punt.stats.pt_net_yards, punt.stats.pt_long) == (5700, None, 66)
    assert punt.games is None


# --- defense board (#317) -----------------------------------------------------

DEFENSE_SORTS = (
    "def_sacks",
    "def_interceptions",
    "def_tackles_solo",
    "def_fumbles_forced",
    "def_pass_defended",
)


def _no_defense(**overrides: float | None) -> dict[str, float | None]:
    """`full_stats` with every defense column a real zero, so a line is on
    the defense board only when a test puts it there."""
    stats = full_stats(**dict.fromkeys(DEFENSE_SORTS, 0))
    stats.update(overrides)
    return stats


def _defense_board(
    conn: sqlite3.Connection, sort: str | None = None, season_type: str = "regular"
) -> PlayerLeaders:
    return get_player_leaders(
        conn,
        sport="nfl",
        category="defense",
        season_type=season_type,  # type: ignore[arg-type]  # the Literal's values
        sort=sort,  # type: ignore[arg-type]  # the Literal's values
    )


def test_defense_sorts_are_the_contracts_and_def_sacks_is_real() -> None:
    assert PLAYER_LEADER_SORTS_BY_CATEGORY["defense"] == DEFENSE_SORTS
    assert "def_sacks" in PLAYER_STAT_REAL_FIELDS


@pytest.mark.parametrize("season_type", ["regular", "postseason"])
def test_defense_qualifies_more_than_zero_in_any_column_whatever_the_position(
    db: PlayerDb, season_type: str
) -> None:
    de = db.player("Half Sack DE", position="DE")
    db.season(de, 2000, season_type=season_type, **_no_defense(def_sacks=0.5))
    cb = db.player("One PD CB", position="CB")
    db.season(cb, 2000, season_type=season_type, **_no_defense(def_pass_defended=1))
    wr = db.player("One Tackle WR", position="WR")
    db.season(wr, 2000, season_type=season_type, **_no_defense(def_tackles_solo=1))
    lb = db.player("One Pick LB", position="LB")
    db.season(lb, 2000, season_type=season_type, **_no_defense(def_interceptions=1))
    s = db.player("One FF S", position="S")
    db.season(s, 2000, season_type=season_type, **_no_defense(def_fumbles_forced=1))
    dt = db.player("All Zero DT", position="DT")
    db.season(dt, 2000, season_type=season_type, **_no_defense())
    blank = db.player("All Null LB", position="LB")
    db.season(blank, 2000, season_type=season_type, **_no_defense(**dict.fromkeys(DEFENSE_SORTS)))
    conn = conn_of(db)

    board = _defense_board(conn, season_type=season_type)

    assert sorted(_names(board.rows)) == [
        "Half Sack DE",
        "One FF S",
        "One PD CB",
        "One Pick LB",
        "One Tackle WR",
    ]
    assert board.total == 5
    assert (board.category, board.season_type) == ("defense", season_type)
    assert {r.display_name: r.position for r in board.rows}["One Tackle WR"] == "WR"


def test_defense_qualifies_on_any_season_line_not_the_career_total(db: PlayerDb) -> None:
    # A 0 season and a 3 season: the 3 season qualifies the career.
    p = db.player("Late Bloomer", position="LB")
    db.season(p, 2000, **_no_defense())
    db.season(p, 2001, **_no_defense(def_tackles_solo=3))
    # A NULL season next to a 0 season: neither qualifies.
    q = db.player("Never Counted", position="LB")
    db.season(q, 2000, **_no_defense())
    db.season(q, 2001, **_no_defense(**dict.fromkeys(DEFENSE_SORTS)))
    conn = conn_of(db)

    board = _defense_board(conn)

    assert (_names(board.rows), board.total) == (["Late Bloomer"], 1)


def test_defense_qualifies_per_season_type(db: PlayerDb) -> None:
    reg = db.player("Regular Rusher", position="DE")
    db.season(reg, 2000, **_no_defense(def_sacks=4.0))
    db.season(reg, 2000, season_type="postseason", **_no_defense())
    playoff = db.player("Playoff Only", position="CB")
    db.season(playoff, 2000, season_type="postseason", **_no_defense(def_interceptions=2))
    conn = conn_of(db)

    assert _names(_defense_board(conn).rows) == ["Regular Rusher"]
    assert _names(_defense_board(conn, season_type="postseason").rows) == ["Playoff Only"]


def test_def_sacks_ranks_half_sacks_exactly_with_the_tiebreak(db: PlayerDb) -> None:
    for name, sacks in [
        ("Ten", 10.0),
        ("Zed Seven Half", 7.5),
        ("Ten Half", 10.5),
        ("Abe Seven Half", 7.5),
        ("Seven", 7.0),
    ]:
        db.season(db.player(name, position="DE"), 2000, **_no_defense(def_sacks=sacks))
    conn = conn_of(db)

    board = _defense_board(conn, "def_sacks")

    assert [(r.rank, r.display_name, r.stats.def_sacks) for r in board.rows] == [
        (1, "Ten Half", 10.5),
        (2, "Ten", 10.0),
        (3, "Abe Seven Half", 7.5),
        (3, "Zed Seven Half", 7.5),
        (5, "Seven", 7.0),
    ]


def test_def_sacks_career_total_adds_half_sacks_across_seasons(db: PlayerDb) -> None:
    p = db.player("Two Halves", position="DE")
    db.season(p, 2000, **_no_defense(def_sacks=3.5))
    db.season(p, 2001, **_no_defense(def_sacks=4.5))
    q = db.player("Seven Half", position="DE")
    db.season(q, 2000, **_no_defense(def_sacks=7.5))
    conn = conn_of(db)

    rows = _defense_board(conn).rows

    assert [(r.rank, r.display_name, r.stats.def_sacks) for r in rows] == [
        (1, "Two Halves", 8.0),
        (2, "Seven Half", 7.5),
    ]


@pytest.mark.parametrize("sort", DEFENSE_SORTS)
def test_each_defense_sort_reads_its_own_column_with_the_tiebreak(db: PlayerDb, sort: str) -> None:
    # The sorted column is 30 / 20 / 20 / 20 / 10; every other defense column
    # runs the opposite way, so only the named one gives this order.
    values = [("Dan", 10), ("Same Name", 20), ("Bob", 20), ("Ann", 30), ("Same Name", 20)]
    ids = []
    for name, value in values:
        pid = db.player(name, position="LB")
        ids.append(pid)
        stats: dict[str, float | None] = {c: 100 - value for c in DEFENSE_SORTS}
        stats[sort] = value
        db.season(pid, 2000, **_no_defense(**stats))
    conn = conn_of(db)

    board = _defense_board(conn, sort)

    assert [(r.rank, r.display_name, r.player_id) for r in board.rows] == [
        (1, "Ann", ids[3]),
        (2, "Bob", ids[2]),
        (2, "Same Name", ids[1]),
        (2, "Same Name", ids[4]),
        (5, "Dan", ids[0]),
    ]
    assert [getattr(r.stats, sort) for r in board.rows] == [30, 20, 20, 20, 10]
    assert (board.category, board.sort, board.total) == ("defense", sort, 5)


def test_defense_default_sort_is_def_sacks(db: PlayerDb) -> None:
    # Most sacks but least of everything else.
    rusher = db.player("Rusher", position="DE")
    db.season(rusher, 2000, **_no_defense(def_sacks=12.0, def_tackles_solo=20))
    tackler = db.player("Tackler", position="LB")
    db.season(
        tackler,
        2000,
        **_no_defense(
            def_sacks=1.0,
            def_interceptions=3,
            def_tackles_solo=120,
            def_fumbles_forced=4,
            def_pass_defended=9,
        ),
    )
    conn = conn_of(db)

    for board in (get_player_leaders(conn, sport="nfl", category="defense"), _defense_board(conn)):
        assert (board.category, board.sort) == ("defense", "def_sacks")
        assert _names(board.rows) == ["Rusher", "Tackler"]


def test_a_null_defense_season_makes_that_total_none_and_unranked(db: PlayerDb) -> None:
    known = db.player("Zed Known", position="LB")
    db.season(known, 2000, **_no_defense(def_sacks=1.0, def_tackles_solo=5))
    gap = db.player("Abe Gap", position="LB")
    db.season(gap, 2000, **_no_defense(def_sacks=9.0, def_tackles_solo=50))
    db.season(gap, 2001, **_no_defense(def_sacks=None, def_tackles_solo=40))
    conn = conn_of(db)

    rows = _defense_board(conn).rows

    # SQL's own SUM would say 9.0 and put him first; the untracked season
    # makes the career total None, unranked and last.
    assert [(r.rank, r.display_name, r.stats.def_sacks) for r in rows] == [
        (1, "Zed Known", 1.0),
        (None, "Abe Gap", None),
    ]
    assert rows[1].stats.def_tackles_solo == 90


def test_every_defense_leaders_row_equals_that_players_career_totals(db: PlayerDb) -> None:
    end = db.player("End", position="DE")
    db.season(end, 2000, games=16, **_no_defense(def_sacks=11.5, def_fumbles_forced=3))
    db.season(end, 2001, games=15, **_no_defense(def_sacks=8.0, def_tackles_solo=30))
    db.season(end, 2001, season_type="postseason", games=2, **_no_defense(def_sacks=1.5))
    corner = db.player("Corner", position="CB")
    db.season(corner, 2000, games=16, **_no_defense(def_interceptions=6, def_pass_defended=18))
    db.season(corner, 2001, games=None, **_no_defense(def_interceptions=None, def_pass_defended=12))
    conn = conn_of(db)

    checked = 0
    for season_type in ("regular", "postseason"):
        for sort in (None, *DEFENSE_SORTS):
            for row in _defense_board(conn, sort, season_type).rows:
                career = get_player_career(conn, sport="nfl", player_id=row.player_id)
                totals = career.regular_season if season_type == "regular" else career.postseason
                assert totals is not None
                assert row.games == totals.games
                assert row.stats == totals.stats
                checked += 1
    # Two regular rows and one postseason row, on each of the six boards.
    assert checked == 3 * (len(DEFENSE_SORTS) + 1)
    by_name = {r.display_name: r for r in _defense_board(conn).rows}
    e, c = by_name["End"].stats, by_name["Corner"]
    assert (e.def_sacks, e.def_fumbles_forced, e.def_tackles_solo) == (19.5, 3, 30)
    assert (c.stats.def_interceptions, c.stats.def_pass_defended, c.games) == (None, 30, None)
