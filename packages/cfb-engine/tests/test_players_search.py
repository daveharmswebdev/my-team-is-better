"""`cfb_strength.players.search_players` on a small synthetic db (#301)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PLAYER_SEARCH_MAX_LIMIT,
    PlayerCareer,
    PlayerPositionGroup,
    PlayerSearchRow,
    position_group,
)
from cfb_strength.players import search_players
from tests.test_players_support import STAT_COLUMNS, PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _passer(
    db: PlayerDb, name: str, yards: int | None = 100, season: int = 2000, games: int | None = 1
) -> int:
    p = db.player(name)
    db.season(p, season, games=games, **full_stats(passing_yards=yards))
    return p


def _only(**stats: float | None) -> dict[str, float | None]:
    """A season line with every stat None except `stats`, so it qualifies for
    exactly the categories those stats satisfy."""
    line: dict[str, float | None] = dict.fromkeys(STAT_COLUMNS, None)
    line.update(stats)
    return line


def _names(db: PlayerDb, query: str, limit: int = 10) -> list[str]:
    return [
        r.display_name
        for r in search_players(conn_of(db), sport="nfl", query=query, limit=limit).rows
    ]


# --- matching -----------------------------------------------------------------


def test_matching_is_a_case_insensitive_substring(db: PlayerDb) -> None:
    _passer(db, "Peyton Manning", games=300)
    _passer(db, "Eli Manning", games=200)
    _passer(db, "Tom Brady", games=400)
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


# --- position group (#428) ----------------------------------------------------

# Every label measured over the committed raw cache (players.csv, 24,824 rows).
_MEASURED_LABELS = [
    "WR", "LB", "RB", "DB", "DE", "OT", "TE", "G", "DT", "CB", "QB", "C", "OLB",
    "K", "P", "SAF", "S", "FS", "NT", "FB", "ILB", "MLB", "LS", "OL", "DL",
]  # fmt: skip
_GROUPED = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}


@pytest.mark.parametrize("label", [*_MEASURED_LABELS, None])
def test_position_group_maps_every_measured_label(label: str | None) -> None:
    expected = _GROUPED.get(label) if label is not None else None
    assert position_group(label) == expected
    assert PlayerSearchRow(1, "X", label, 2000, 2000).group == expected
    career = PlayerCareer("nfl", 1, "X", label, [], None, None)
    assert career.group == expected


def _one_of_each_position(db: PlayerDb) -> dict[str | None, int]:
    """A qualifying "Pos <label>" player for every measured label and None,
    all with the same games, so the unfiltered order is by name."""
    ids: dict[str | None, int] = {}
    for label in [*_MEASURED_LABELS, None]:
        p = db.player(f"Pos {label or 'none'}", position=label)
        db.season(p, 2000, games=5, **_only(carries=1))
        ids[label] = p
    return ids


@pytest.mark.parametrize("group", ["QB", "RB", "WR", "TE"])
def test_a_group_keeps_exactly_the_players_whose_label_maps_to_it(
    db: PlayerDb, group: PlayerPositionGroup
) -> None:
    ids = _one_of_each_position(db)
    result = search_players(
        conn_of(db), sport="nfl", query="pos", limit=PLAYER_SEARCH_MAX_LIMIT, group=group
    )
    labels = sorted((label for label, g in _GROUPED.items() if g == group), key="Pos {}".format)
    expected = [ids[label] for label in labels]
    assert [r.player_id for r in result.rows] == expected
    assert all(r.group == group for r in result.rows)


def test_rb_includes_fb_and_excludes_every_other_label(db: PlayerDb) -> None:
    ids = _one_of_each_position(db)
    rows = search_players(
        conn_of(db), sport="nfl", query="pos", limit=PLAYER_SEARCH_MAX_LIMIT, group="RB"
    ).rows
    assert [r.player_id for r in rows] == [ids["FB"], ids["RB"]]


def test_the_group_filter_applies_before_the_limit(db: PlayerDb) -> None:
    # The ten most-played matches are all QBs, so a filter applied to the
    # first `limit` rows would find no RB at all.
    for i in range(10):
        _passer(db, f"Lim Qb {i}", games=100 + i)
    rbs = []
    for i in range(3):
        p = db.player(f"Lim Rb {i}", position="RB")
        db.season(p, 2000, games=10 - i, **_only(carries=5))
        rbs.append(p)
    conn = conn_of(db)
    assert all(r.position == "QB" for r in search_players(conn, sport="nfl", query="lim").rows)
    rows = search_players(conn, sport="nfl", query="lim", limit=2, group="RB").rows
    assert [r.player_id for r in rows] == rbs[:2]
    rows = search_players(conn, sport="nfl", query="lim", limit=10, group="RB").rows
    assert [r.player_id for r in rows] == rbs


def test_no_group_is_the_unfiltered_result(db: PlayerDb) -> None:
    _one_of_each_position(db)
    conn = conn_of(db)
    default = search_players(conn, sport="nfl", query="pos", limit=PLAYER_SEARCH_MAX_LIMIT)
    explicit = search_players(
        conn, sport="nfl", query="pos", limit=PLAYER_SEARCH_MAX_LIMIT, group=None
    )
    assert default == explicit
    # The first page of every label, by name, whatever its group.
    expected = sorted(f"Pos {label or 'none'}" for label in [*_MEASURED_LABELS, None])
    assert [r.display_name for r in default.rows] == expected[:PLAYER_SEARCH_MAX_LIMIT]


@pytest.mark.parametrize("group", ["", "qb", "FB", "K", "HB", "QB ", 1])
def test_an_invalid_group_raises(db: PlayerDb, group: object) -> None:
    with pytest.raises(ValueError):
        search_players(conn_of(db), sport="nfl", query="ab", group=group)  # type: ignore[arg-type]  # deliberately not a PlayerPositionGroup


def test_a_nul_query_with_a_group_finds_nobody(db: PlayerDb) -> None:
    result = search_players(conn_of(db), sport="nfl", query="a\x00b", group="TE")
    assert result.rows == []


# --- who qualifies ------------------------------------------------------------


# One line per category, each qualifying for that category alone (#371).
_CATEGORY_ONLY = {
    "rushing": _only(carries=3, rushing_yards=10),
    "receiving": _only(targets=2),
    "receiving_without_targets": _only(receptions=1, targets=0),
    "kicking": _only(fg_att=1),
    "kicking_pat_only": _only(pat_att=2),
    "punting": _only(pt_att=4),
    "defense": _only(def_tackles_solo=1),
    "defense_half_sack": _only(def_sacks=0.5),
}


@pytest.mark.parametrize("line", _CATEGORY_ONLY.values(), ids=_CATEGORY_ONLY.keys())
@pytest.mark.parametrize("season_type", ["regular", "postseason"])
def test_a_player_qualifying_for_any_one_category_is_found(
    db: PlayerDb, line: dict[str, float | None], season_type: str
) -> None:
    # #371: search found only passers, so typing "gore" missed Frank Gore.
    p = db.player("Gore Nonpasser", position="RB")
    db.season(p, 2005, season_type=season_type, **line)
    rows = search_players(conn_of(db), sport="nfl", query="gore").rows
    assert [r.player_id for r in rows] == [p]


def test_passers_and_qb_starters_still_qualify(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    playoff_only = db.player("Smith Playoff Starter")
    db.start(db.game(2003, home, away, 7, 3, season_type="postseason", week=19), home, playoff_only)
    postseason_passer = db.player("Smith Postseason Passer")
    db.season(postseason_passer, 2003, season_type="postseason", **_only(attempts=1))
    assert _names(db, "smith") == ["Smith Playoff Starter", "Smith Postseason Passer"]


def test_a_player_qualifying_for_no_category_is_not_found(db: PlayerDb) -> None:
    # Every stat a real 0, every stat untracked, or no rows at all: on no board.
    zeros = db.player("Smith All Zeros")
    db.season(zeros, 2003, games=16, **dict.fromkeys(STAT_COLUMNS, 0))
    db.season(zeros, 2004, season_type="postseason", **dict.fromkeys(STAT_COLUMNS, 0))
    untracked = db.player("Smith Untracked")
    db.season(untracked, 2003, games=16, **_only())
    db.player("Smith No Rows")
    kicker = db.player("Smith Kicker", position="K")
    db.season(kicker, 2003, games=1, **_only(fg_att=0, pat_att=1))
    assert _names(db, "smith") == ["Smith Kicker"]


def test_order_is_regular_games_desc_none_last_then_name_then_id(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    # A non-QB with more regular-season games ranks above a QB with fewer,
    # however many yards the QB threw for (#371). Games add up across seasons.
    rusher = db.player("Ord Rusher", position="RB")
    db.season(rusher, 2000, games=8, **_only(carries=100))
    db.season(rusher, 2001, games=8, **_only(carries=100))
    db.season(rusher, 2001, season_type="postseason", games=3, **_only(carries=10))
    qb = _passer(db, "Ord Qb", 9_000, games=3)
    # Postseason games don't count toward the order.
    db.season(qb, 2000, season_type="postseason", games=20, **full_stats(passing_yards=900))
    # Same games: display_name breaks the tie.
    zed = db.player("Ord Mid Zed", position="P")
    db.season(zed, 2000, games=5, **_only(pt_att=40))
    abe = db.player("Ord Mid Abe", position="LB")
    db.season(abe, 2000, games=5, **_only(def_sacks=2))
    # Same name and games: player_id breaks it (inserted high id first).
    twin_high = db.player("Ord Twin", position="WR", player_id=9_002)
    db.season(twin_high, 2000, games=5, **_only(targets=9))
    twin_low = db.player("Ord Twin", position="K", player_id=9_001)
    db.season(twin_low, 2000, games=5, **_only(fg_att=9))
    # A zero is a number, not None: it sorts above the None rows.
    zero = _passer(db, "Ord Zero", 50, games=0)
    # No regular-season games total: postseason only, a regular start without
    # a season row, and a regular season row whose games weren't tracked.
    playoff = db.player("Ord Aaa Playoff", position="RB")
    db.season(playoff, 2000, season_type="postseason", games=4, **_only(carries=50))
    starter = db.player("Ord Bbb Starter")
    db.start(db.game(2000, home, away, 1, 0), home, starter)
    untracked = db.player("Ord Ccc Untracked", position="DE")
    db.season(untracked, 2000, games=None, **_only(def_tackles_solo=30))

    rows = search_players(conn_of(db), sport="nfl", query="ord", limit=20).rows

    assert [r.player_id for r in rows] == [
        rusher,
        abe,
        zed,
        9_001,
        9_002,
        qb,
        zero,
        playoff,
        starter,
        untracked,
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


# --- cost ---------------------------------------------------------------------

# A substring LIKE can use no index, so finding who matches reads every name in
# the sport once. That scan is the floor; the cost above it is what #368 is about.
_NAME_SCAN = (
    "SELECT id FROM players WHERE sport = 'nfl'"
    " AND lower(display_name) LIKE lower('%needle%') ESCAPE '\\'"
)


def _steps(conn: sqlite3.Connection, run: Callable[[], object]) -> int:
    """SQLite VM steps (in tens) `run` takes: a deterministic stand-in for
    its cost, so the test asserts no wall-clock time (#368)."""
    steps = 0

    def tick() -> int:
        nonlocal steps
        steps += 1
        return 0

    conn.set_progress_handler(tick, 10)
    try:
        run()
    finally:
        conn.set_progress_handler(None, 0)
    return steps


def _cost_above_name_scan(db: PlayerDb) -> int:
    conn = conn_of(db)
    search = _steps(conn, lambda: search_players(conn, sport="nfl", query="needle"))
    scan = _steps(conn, lambda: conn.execute(_NAME_SCAN).fetchall())
    return search - scan


def _db_with_bystanders(path: Path, bystanders: int) -> PlayerDb:
    d = PlayerDb(path)
    home, away = d.team("Home"), d.team("Away")
    for i in range(3):
        _passer(d, f"Needle {i}", 100, games=10 + i)
    for i in range(bystanders):
        # A qualifying player who doesn't match: a passing season and a QB start.
        p = _passer(d, f"Bystander {i:04d}", 50)
        d.start(d.game(2000 + i % 20, home, away, 7, 3, week=1 + i // 20), home, p)
    return d


def test_search_cost_does_not_scale_with_players_who_do_not_match(tmp_path: Path) -> None:
    # #368: search aggregated every player's career before applying the name
    # filter, so each keystroke cost a whole leaderboard. Beyond the one scan
    # of names, its work must scale with the players who match, not with the
    # size of the table: 20x the non-matching players, well under 2x the work.
    small = _db_with_bystanders(tmp_path / "small.sqlite3", 20)
    large = _db_with_bystanders(tmp_path / "large.sqlite3", 400)
    try:
        expected = ["Needle 2", "Needle 1", "Needle 0"]
        assert _names(small, "needle") == _names(large, "needle") == expected
        small_cost = _cost_above_name_scan(small)
        large_cost = _cost_above_name_scan(large)
    finally:
        small.close()
        large.close()
    assert 0 < small_cost
    assert large_cost < 2 * small_cost, (small_cost, large_cost)
