"""`cfb_strength.players.get_player_comparison` on a small synthetic db (#301)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PlayerHeadToHead,
    PlayerHeadToHeadGame,
    PlayerStats,
    StarterRecord,
    UnknownPlayerError,
)
from cfb_strength.players import get_player_career, get_player_comparison
from tests.test_players_support import PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _swapped(game: PlayerHeadToHeadGame) -> PlayerHeadToHeadGame:
    return PlayerHeadToHeadGame(
        season=game.season,
        season_type=game.season_type,
        week=game.week,
        start_date=game.start_date,
        source_id=game.source_id,
        a_team=game.b_team,
        b_team=game.a_team,
        a_points=game.b_points,
        b_points=game.a_points,
        a_stats=game.b_stats,
        b_stats=game.a_stats,
    )


# --- arguments and unknown players --------------------------------------------


def test_comparing_a_player_with_the_same_player_raises(db: PlayerDb) -> None:
    p = db.player("Solo")
    with pytest.raises(ValueError):
        get_player_comparison(conn_of(db), sport="nfl", a=p, b=p)


def test_unknown_a_raises_for_a_even_when_b_is_unknown_too(db: PlayerDb) -> None:
    with pytest.raises(UnknownPlayerError) as exc:
        get_player_comparison(conn_of(db), sport="nfl", a=111_111, b=222_222)
    assert (exc.value.player_id, exc.value.sport) == (111_111, "nfl")


def test_unknown_b_raises_for_b(db: PlayerDb) -> None:
    a = db.player("Known")
    with pytest.raises(UnknownPlayerError) as exc:
        get_player_comparison(conn_of(db), sport="nfl", a=a, b=222_222)
    assert (exc.value.player_id, exc.value.sport) == (222_222, "nfl")


def test_a_player_from_another_sport_is_unknown(db: PlayerDb) -> None:
    a = db.player("Pro")
    college = db.player("College", sport="cfb")
    with pytest.raises(UnknownPlayerError) as exc:
        get_player_comparison(conn_of(db), sport="nfl", a=a, b=college)
    assert (exc.value.player_id, exc.value.sport) == (college, "nfl")


# --- careers ------------------------------------------------------------------


def test_a_and_b_are_exactly_their_careers(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    db.season(a, 2000, team=home, **full_stats(passing_yards=300, sacks_suffered=None))
    db.season(b, 2000, team=away, **full_stats(passing_yards=200))
    db.season(b, 2000, season_type="postseason", team=away, **full_stats())
    g = db.game(2000, home, away, 21, 17)
    db.start(g, home, a)
    db.start(g, away, b)
    conn = conn_of(db)

    c = get_player_comparison(conn, sport="nfl", a=a, b=b)

    assert c.sport == "nfl"
    assert c.a == get_player_career(conn, sport="nfl", player_id=a)
    assert c.b == get_player_career(conn, sport="nfl", player_id=b)


# --- which games are head-to-head -----------------------------------------------


def test_a_game_both_started_for_opposite_teams_is_head_to_head(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    g = db.game(2000, home, away, 21, 17, week=3, start_date="2000-09-17")
    db.start(g, home, a)
    db.start(g, away, b)
    db.game_line(a, g, home, **full_stats(passing_yards=250))
    db.game_line(b, g, away, **full_stats(passing_yards=190))
    conn = conn_of(db)

    h2h = get_player_comparison(conn, sport="nfl", a=a, b=b).regular_season_head_to_head

    assert h2h == PlayerHeadToHead(
        season_type="regular",
        record=StarterRecord(1, 0, 0),
        games=[
            PlayerHeadToHeadGame(
                season=2000,
                season_type="regular",
                week=3,
                start_date="2000-09-17",
                source_id=f"g{g}",
                a_team="Home",
                b_team="Away",
                a_points=21,
                b_points=17,
                a_stats=PlayerStats(**full_stats(passing_yards=250)),
                b_stats=PlayerStats(**full_stats(passing_yards=190)),
            )
        ],
    )


def test_a_relief_appearance_is_not_head_to_head(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    starter, reliever, opponent = db.player("Starter"), db.player("Reliever"), db.player("Opp")
    g = db.game(2001, home, away, 17, 24, season_type="postseason", week=20)
    db.start(g, away, starter)
    db.start(g, home, opponent)
    # The reliever threw passes for the same team but is not the listed starter.
    db.game_line(starter, g, away, **full_stats(attempts=18))
    db.game_line(reliever, g, away, **full_stats(attempts=21))
    db.game_line(opponent, g, home, **full_stats(attempts=42))
    conn = conn_of(db)

    relief = get_player_comparison(conn, sport="nfl", a=reliever, b=opponent)
    listed = get_player_comparison(conn, sport="nfl", a=starter, b=opponent)

    assert relief.postseason_head_to_head == PlayerHeadToHead(
        "postseason", StarterRecord(0, 0, 0), []
    )
    assert listed.postseason_head_to_head.record == StarterRecord(1, 0, 0)
    assert len(listed.postseason_head_to_head.games) == 1


def test_a_listed_replacement_owns_the_game(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    regular, replacement, opponent = db.player("Regular"), db.player("Sub"), db.player("Opp")
    # Regular started week 1; the source lists the replacement for week 17,
    # in which Regular still threw two passes.
    g1 = db.game(2004, home, away, 14, 33, week=1)
    db.start(g1, away, regular)
    db.start(g1, home, opponent)
    g17 = db.game(2004, home, away, 33, 14, week=17)
    db.start(g17, away, replacement)
    db.start(g17, home, opponent)
    db.game_line(regular, g17, away, **full_stats(attempts=2))
    db.game_line(replacement, g17, away, **full_stats(attempts=25))
    conn = conn_of(db)

    reg = get_player_comparison(conn, sport="nfl", a=regular, b=opponent)
    sub = get_player_comparison(conn, sport="nfl", a=replacement, b=opponent)

    assert [g.week for g in reg.regular_season_head_to_head.games] == [1]
    assert reg.regular_season_head_to_head.record == StarterRecord(1, 0, 0)
    assert [g.week for g in sub.regular_season_head_to_head.games] == [17]
    assert sub.regular_season_head_to_head.record == StarterRecord(0, 1, 0)


@pytest.mark.parametrize(
    ("home_points", "away_points", "completed"),
    [(21, 17, False), (None, 17, True), (21, None, True)],
    ids=["not-completed", "no-home-score", "no-away-score"],
)
def test_an_incomplete_game_is_not_head_to_head_but_is_still_a_career_start(
    db: PlayerDb, home_points: int | None, away_points: int | None, completed: bool
) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    counted = db.game(2000, home, away, 21, 17, week=1)
    db.start(counted, home, a)
    db.start(counted, away, b)
    # The open game is the only 2001 start of either player.
    open_game = db.game(2001, home, away, home_points, away_points, week=2, completed=completed)
    db.start(open_game, home, a)
    db.start(open_game, away, b)
    conn = conn_of(db)

    c = get_player_comparison(conn, sport="nfl", a=a, b=b)

    assert [(g.season, g.week) for g in c.regular_season_head_to_head.games] == [(2000, 1)]
    assert c.regular_season_head_to_head.record == StarterRecord(1, 0, 0)
    # Per the career rules, the start still makes a 2001 line, with no W-L-T.
    for career, record_2000 in ((c.a, StarterRecord(1, 0, 0)), (c.b, StarterRecord(0, 1, 0))):
        assert [(s.season, s.record) for s in career.seasons] == [
            (2000, record_2000),
            (2001, StarterRecord(0, 0, 0)),
        ]


def test_a_tie_counts_as_a_tie(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    g = db.game(2002, home, away, 34, 34, week=10)
    db.start(g, home, a)
    db.start(g, away, b)
    conn = conn_of(db)

    for x, y in ((a, b), (b, a)):
        h2h = get_player_comparison(conn, sport="nfl", a=x, b=y).regular_season_head_to_head
        assert h2h.record == StarterRecord(0, 0, 1)
        assert (h2h.games[0].a_points, h2h.games[0].b_points) == (34, 34)


# --- record, symmetry and order -------------------------------------------------


@pytest.fixture
def rivalry(db: PlayerDb) -> tuple[int, int]:
    """Two players who met five times across two seasons and both season types,
    inserted out of chronological order."""
    east, west, bye = db.team("East"), db.team("West"), db.team("Bye")
    a, b = db.player("A"), db.player("B")

    def meet(
        season: int,
        week: int,
        date: str,
        a_home: bool,
        a_pts: int,
        b_pts: int,
        season_type: str = "regular",
    ) -> int:
        a_team, b_team = (east, west) if a_home else (west, east)
        home, away = (a_team, b_team) if a_home else (b_team, a_team)
        hp, ap = (a_pts, b_pts) if a_home else (b_pts, a_pts)
        g = db.game(season, home, away, hp, ap, week=week, start_date=date, season_type=season_type)
        db.start(g, a_team, a)
        db.start(g, b_team, b)
        return g

    meet(2001, 9, "2001-11-04", False, 10, 30)
    meet(2000, 20, "2001-01-14", True, 24, 21, season_type="postseason")
    meet(2000, 3, "2000-09-17", True, 28, 14)
    # Same date, weeks out of order: week breaks the tie.
    meet(2000, 12, "2000-11-26", False, 17, 17)
    meet(2000, 11, "2000-11-26", True, 31, 3)
    # Unrelated start by a against someone else.
    other = db.game(2000, east, bye, 7, 0, week=4, start_date="2000-09-24")
    db.start(other, east, a)
    return a, b


def test_record_is_as_wins_losses_ties_and_starts_equals_games(
    db: PlayerDb, rivalry: tuple[int, int]
) -> None:
    a, b = rivalry
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    reg, post = c.regular_season_head_to_head, c.postseason_head_to_head
    assert (reg.season_type, post.season_type) == ("regular", "postseason")
    assert reg.record == StarterRecord(2, 1, 1)
    assert post.record == StarterRecord(1, 0, 0)
    assert reg.record.starts == len(reg.games)
    assert post.record.starts == len(post.games)


def test_games_are_chronological_and_split_by_season_type(
    db: PlayerDb, rivalry: tuple[int, int]
) -> None:
    a, b = rivalry
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    assert [(g.season, g.week, g.start_date) for g in c.regular_season_head_to_head.games] == [
        (2000, 3, "2000-09-17"),
        (2000, 11, "2000-11-26"),
        (2000, 12, "2000-11-26"),
        (2001, 9, "2001-11-04"),
    ]
    assert {g.season_type for g in c.regular_season_head_to_head.games} == {"regular"}
    assert [(g.season, g.season_type) for g in c.postseason_head_to_head.games] == [
        (2000, "postseason")
    ]


def test_same_date_and_week_orders_by_game_id(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    first = db.game(2000, away, home, 3, 0, week=1, start_date="2000-09-03")
    second = db.game(2000, home, away, 0, 3, week=1, start_date="2000-09-03")
    for g in (second, first):
        db.start(g, home, a)
        db.start(g, away, b)
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    assert [g.source_id for g in c.regular_season_head_to_head.games] == [f"g{first}", f"g{second}"]


def test_swapping_a_and_b_swaps_wins_and_losses_and_the_game_sides(
    db: PlayerDb, rivalry: tuple[int, int]
) -> None:
    a, b = rivalry
    conn = conn_of(db)
    ab = get_player_comparison(conn, sport="nfl", a=a, b=b)
    ba = get_player_comparison(conn, sport="nfl", a=b, b=a)

    assert (ba.a, ba.b) == (ab.b, ab.a)
    for mine, theirs in (
        (ab.regular_season_head_to_head, ba.regular_season_head_to_head),
        (ab.postseason_head_to_head, ba.postseason_head_to_head),
    ):
        r = mine.record
        assert theirs.record == StarterRecord(r.losses, r.wins, r.ties)
        assert theirs.games == [_swapped(g) for g in mine.games]


def test_every_head_to_head_game_is_in_both_careers_records(
    db: PlayerDb, rivalry: tuple[int, int]
) -> None:
    a, b = rivalry
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    for career in (c.a, c.b):
        for h2h in (c.regular_season_head_to_head, c.postseason_head_to_head):
            starts = sum(
                s.record.starts for s in career.seasons if s.season_type == h2h.season_type
            )
            assert starts >= h2h.record.starts
    # a's only other start is a regular-season win, so a's regular record is h2h + 1-0-0.
    assert c.a.regular_season is not None
    assert c.a.regular_season.record == StarterRecord(3, 1, 1)


def test_players_who_never_met_get_empty_head_to_heads(db: PlayerDb) -> None:
    home, away, other = db.team("Home"), db.team("Away"), db.team("Other")
    a, b = db.player("A"), db.player("B")
    g1 = db.game(2000, home, other, 1, 0)
    db.start(g1, home, a)
    g2 = db.game(2000, other, away, 1, 0)
    db.start(g2, away, b)
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    assert c.regular_season_head_to_head == PlayerHeadToHead("regular", StarterRecord(0, 0, 0), [])
    assert c.postseason_head_to_head == PlayerHeadToHead("postseason", StarterRecord(0, 0, 0), [])


def test_a_game_from_another_sport_is_not_head_to_head(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    g = db.game(2000, home, away, 21, 17, sport="cfb")
    db.start(g, home, a, sport="cfb")
    db.start(g, away, b, sport="cfb")
    c = get_player_comparison(conn_of(db), sport="nfl", a=a, b=b)
    assert c.regular_season_head_to_head.games == []


# --- per-game stat lines --------------------------------------------------------


def test_stats_are_none_without_a_game_row_and_a_null_stat_stays_none(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    a, b = db.player("A"), db.player("B")
    g = db.game(1999, home, away, 27, 10)
    db.start(g, home, a)
    db.start(g, away, b)
    db.game_line(a, g, home, **full_stats(passing_yards=0, sacks_suffered=None))
    empty = db.game(1999, away, home, 10, 27, week=2)
    db.start(empty, home, a)
    db.start(empty, away, b)
    conn = conn_of(db)

    games = get_player_comparison(conn, sport="nfl", a=a, b=b).regular_season_head_to_head.games

    first, second = games
    assert first.a_stats == PlayerStats(**full_stats(passing_yards=0, sacks_suffered=None))
    assert first.a_stats is not None and first.a_stats.sacks_suffered is None
    assert first.a_stats.passing_yards == 0
    assert first.b_stats is None
    assert (second.a_stats, second.b_stats) == (None, None)
