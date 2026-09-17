"""`cfb_strength.players.get_player_career` on a small synthetic db (#296)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    PLAYER_STAT_MAX_FIELDS,
    PlayerCareer,
    PlayerCareerTotals,
    PlayerSeasonLine,
    PlayerStats,
    StarterRecord,
    UnknownPlayerError,
)
from cfb_strength.players import get_player_career
from tests.test_players_support import PlayerDb, conn_of, full_stats


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "players.sqlite3")
    try:
        yield d
    finally:
        d.close()


def _line(career: PlayerCareer, season: int, season_type: str = "regular") -> PlayerSeasonLine:
    matches = [s for s in career.seasons if (s.season, s.season_type) == (season, season_type)]
    assert len(matches) == 1
    return matches[0]


# --- identity and unknown players -------------------------------------------


def test_career_carries_the_players_identity(db: PlayerDb) -> None:
    p = db.player("Kurt", position="QB")
    db.season(p, 2000, **full_stats())
    career = get_player_career(conn_of(db), sport="nfl", player_id=p)
    assert (career.sport, career.player_id, career.display_name, career.position) == (
        "nfl",
        p,
        "Kurt",
        "QB",
    )


def test_unknown_player_raises(db: PlayerDb) -> None:
    with pytest.raises(UnknownPlayerError) as exc:
        get_player_career(conn_of(db), sport="nfl", player_id=999_999)
    assert (exc.value.player_id, exc.value.sport) == (999_999, "nfl")


def test_a_real_player_asked_for_under_the_wrong_sport_raises(db: PlayerDb) -> None:
    p = db.player("Pro")
    db.season(p, 2000, **full_stats())
    conn = conn_of(db)
    with pytest.raises(UnknownPlayerError) as exc:
        get_player_career(conn, sport="cfb", player_id=p)
    assert (exc.value.player_id, exc.value.sport) == (p, "cfb")


def test_a_player_with_no_lines_has_empty_career(db: PlayerDb) -> None:
    p = db.player("Never Played")
    career = get_player_career(conn_of(db), sport="nfl", player_id=p)
    assert (career.seasons, career.regular_season, career.postseason) == ([], None, None)


# --- lines ------------------------------------------------------------------


def test_lines_are_chronological_with_regular_before_postseason(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("P")
    db.season(p, 2002, **full_stats())
    db.season(p, 2001, season_type="postseason", **full_stats())
    db.season(p, 2001, **full_stats())
    # 2000 postseason exists only as a start; 2000 regular not at all.
    db.start(db.game(2000, home, away, 10, 3, season_type="postseason", week=19), home, p)
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    assert [(s.season, s.season_type) for s in career.seasons] == [
        (2000, "postseason"),
        (2001, "regular"),
        (2001, "postseason"),
        (2002, "regular"),
    ]


def test_a_start_with_no_season_row_gives_a_line_with_all_none_stats(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("Starter")
    db.start(db.game(2000, home, away, 10, 3), home, p)
    conn = conn_of(db)

    line = _line(get_player_career(conn, sport="nfl", player_id=p), 2000)

    assert line.stats == PlayerStats()
    assert line.games is None
    assert line.record == StarterRecord(1, 0, 0)
    assert line.teams == ["Home"]


def test_line_stats_games_and_record_come_from_their_own_rows(db: PlayerDb) -> None:
    home, away = db.team("Home"), db.team("Away")
    p = db.player("P")
    db.season(p, 2000, team=home, games=2, **full_stats(passing_yards=321, sacks_suffered=None))
    g1 = db.game(2000, home, away, 20, 10, week=1)
    g2 = db.game(2000, away, home, 14, 14, week=2)
    db.start(g1, home, p)
    db.start(g2, home, p)
    conn = conn_of(db)

    line = _line(get_player_career(conn, sport="nfl", player_id=p), 2000)

    assert line.games == 2
    assert line.stats == PlayerStats(**full_stats(passing_yards=321, sacks_suffered=None))
    assert line.record == StarterRecord(1, 0, 1)


# --- teams ------------------------------------------------------------------


def test_teams_are_every_team_with_a_game_row_or_start_in_order_of_first_game(
    db: PlayerDb,
) -> None:
    zeta, alpha, mid, opp = db.team("Zeta"), db.team("Alpha"), db.team("Mid"), db.team("Opp")
    p = db.player("Traded Twice")
    db.season(p, 2011, team=None, **full_stats())
    # Zeta first (week 1, stat line), Alpha next (week 5, a start with no line),
    # Mid last (week 9), then Zeta again (week 12): Zeta keeps its first slot.
    g1 = db.game(2011, zeta, opp, 1, 0, week=1)
    g5 = db.game(2011, opp, alpha, 1, 0, week=5)
    g9 = db.game(2011, mid, opp, 1, 0, week=9)
    g12 = db.game(2011, zeta, opp, 1, 0, week=12)
    db.game_line(p, g1, zeta, **full_stats())
    db.start(g5, alpha, p)
    db.game_line(p, g9, mid, **full_stats())
    db.game_line(p, g12, zeta, **full_stats())
    # A postseason game for Mid does not change the regular line's teams.
    db.season(p, 2011, season_type="postseason", team=None, **full_stats())
    db.game_line(p, db.game(2011, opp, mid, 1, 0, season_type="postseason", week=19), mid)
    # A stat line alone (no season row, no start) creates no line.
    db.game_line(p, db.game(2012, zeta, opp, 1, 0, week=1), zeta)
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    assert _line(career, 2011).teams == ["Zeta", "Alpha", "Mid"]
    assert _line(career, 2011, "postseason").teams == ["Mid"]
    assert [(s.season, s.season_type) for s in career.seasons] == [
        (2011, "regular"),
        (2011, "postseason"),
    ]


def test_teams_fall_back_to_the_season_rows_team_and_else_are_empty(db: PlayerDb) -> None:
    home = db.team("Home")
    p = db.player("Old Timer")
    db.season(p, 2000, team=home, **full_stats())
    db.season(p, 2001, team=None, **full_stats())
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    assert _line(career, 2000).teams == ["Home"]
    assert _line(career, 2001).teams == []


# --- games_without_stat_lines -----------------------------------------------


def test_games_without_stat_lines_counts_completed_games_of_the_lines_teams_with_no_rows(
    db: PlayerDb,
) -> None:
    mine, other_team, opp, bystander = (
        db.team("Mine"),
        db.team("Other"),
        db.team("Opp"),
        db.team("Bystander"),
    )
    p = db.player("P")
    teammate = db.player("Teammate", position="WR")
    db.season(p, 2000, team=mine, **full_stats())

    played = db.game(2000, mine, opp, 10, 3, week=1)
    db.game_line(p, played, mine, **full_stats())
    # Counted: completed, one of his teams, no player_game_stats rows at all.
    db.game(2000, opp, mine, 10, 3, week=2)
    db.game(2000, mine, opp, 10, 3, week=3)
    # Not counted: a teammate's line exists; someone else's game; incomplete;
    # other season; other season type.
    has_teammate_line = db.game(2000, mine, opp, 10, 3, week=4)
    db.game_line(teammate, has_teammate_line, mine, **full_stats())
    db.game(2000, other_team, bystander, 10, 3, week=5)
    db.game(2000, mine, opp, None, None, week=6, completed=False)
    db.game(2001, mine, opp, 10, 3, week=1)
    db.game(2000, mine, opp, 10, 3, week=19, season_type="postseason")
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    assert _line(career, 2000).games_without_stat_lines == 2
    assert not any(s.season == 2001 for s in career.seasons)


def test_games_without_stat_lines_is_zero_when_the_line_names_no_team(db: PlayerDb) -> None:
    mine, opp = db.team("Mine"), db.team("Opp")
    p = db.player("P")
    db.season(p, 2000, team=None, **full_stats())
    db.game(2000, mine, opp, 10, 3)
    conn = conn_of(db)
    assert (
        _line(get_player_career(conn, sport="nfl", player_id=p), 2000).games_without_stat_lines == 0
    )


# --- totals -----------------------------------------------------------------


def test_regular_season_and_postseason_totals_are_none_without_a_line_of_that_type(
    db: PlayerDb,
) -> None:
    home, away = db.team("Home"), db.team("Away")
    reg = db.player("Regular Only")
    db.season(reg, 2000, **full_stats())
    post = db.player("Postseason Start Only")
    db.start(db.game(2000, home, away, 1, 0, season_type="postseason", week=19), home, post)
    conn = conn_of(db)

    reg_career = get_player_career(conn, sport="nfl", player_id=reg)
    post_career = get_player_career(conn, sport="nfl", player_id=post)

    assert reg_career.regular_season is not None and reg_career.postseason is None
    assert post_career.regular_season is None
    assert post_career.postseason == PlayerCareerTotals(
        season_type="postseason",
        seasons=1,
        games=None,
        record=StarterRecord(1, 0, 0),
        stats=PlayerStats(),
    )


def test_totals_apply_the_null_rule(db: PlayerDb) -> None:
    p = db.player("P")
    db.season(p, 2000, games=10, **full_stats(passing_yards=100, carries=5))
    db.season(p, 2001, games=11, **full_stats(passing_yards=200, carries=None))
    conn = conn_of(db)

    totals = get_player_career(conn, sport="nfl", player_id=p).regular_season

    assert totals is not None
    assert (totals.seasons, totals.games) == (2, 21)
    assert totals.stats.passing_yards == 300
    assert totals.stats.carries is None


def test_career_is_scoped_by_sport(db: PlayerDb) -> None:
    nfl_home, nfl_away = db.team("NFL Home"), db.team("NFL Away")
    cfb_home, cfb_away = db.team("CFB Home", sport="cfb"), db.team("CFB Away", sport="cfb")
    p = db.player("Pro")
    g = db.game(2000, nfl_home, nfl_away, 10, 3)
    db.season(p, 2000, team=nfl_home, **full_stats(passing_yards=100))
    db.game_line(p, g, nfl_home, **full_stats())
    db.start(g, nfl_home, p)
    # Same id space, another sport: none of it is this NFL player's career.
    cg = db.game(2000, cfb_home, cfb_away, 50, 0, week=2, sport="cfb")
    db.season(p, 2001, team=cfb_home, sport="cfb", **full_stats(passing_yards=999))
    db.game_line(p, cg, cfb_home, sport="cfb", **full_stats())
    db.start(cg, cfb_home, p, sport="cfb")
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    assert [(s.season, s.season_type) for s in career.seasons] == [(2000, "regular")]
    line = career.seasons[0]
    assert line.teams == ["NFL Home"]
    assert line.record == StarterRecord(1, 0, 0)
    assert career.regular_season is not None
    assert career.regular_season.stats.passing_yards == 100


# --- the seam invariant -----------------------------------------------------


def _null_aware_sum(values: list[int | None]) -> int | None:
    if not values or any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def _max_skipping_nulls(values: list[int | None]) -> int | None:
    """SQL's MAX: NULL seasons are skipped, and an all-NULL group is None."""
    present = [v for v in values if v is not None]
    return max(present) if present else None


def test_career_totals_combine_the_season_lines_by_the_contracts_rule(db: PlayerDb) -> None:
    """Every stat column is the null-aware sum of its season lines, except
    `PLAYER_STAT_MAX_FIELDS`, which are the max (#334). The split is read
    from the contract, so a MAX column added there later is checked here
    rather than silently re-entering the sum loop."""
    home, away = db.team("Home"), db.team("Away")
    p = db.player("P")
    db.season(p, 2000, games=16, **full_stats(passing_yards=4000, carries=30, fg_long=53))
    db.season(p, 2001, games=15, **full_stats(passing_yards=3500, carries=None, fg_long=47))
    db.season(p, 2002, games=None, **full_stats(passing_yards=0, fg_long=52, pt_long=None))
    db.season(
        p,
        2001,
        season_type="postseason",
        games=2,
        **full_stats(passing_yards=500, fg_long=44, pt_long=None),
    )
    for week, (hp, ap) in enumerate([(20, 10), (10, 10), (3, 9)], 1):
        db.start(db.game(2001, home, away, hp, ap, week=week), home, p)
    db.start(db.game(2003, home, away, 1, 0), away, p)
    db.start(db.game(2001, home, away, 1, 0, season_type="postseason", week=19), home, p)
    conn = conn_of(db)

    career = get_player_career(conn, sport="nfl", player_id=p)

    for season_type, totals in (
        ("regular", career.regular_season),
        ("postseason", career.postseason),
    ):
        lines = [s for s in career.seasons if s.season_type == season_type]
        assert totals is not None
        assert totals.season_type == season_type
        assert totals.seasons == len(lines)
        assert totals.games == _null_aware_sum([s.games for s in lines])
        assert totals.record == StarterRecord(
            sum(s.record.wins for s in lines),
            sum(s.record.losses for s in lines),
            sum(s.record.ties for s in lines),
        )
        for f in fields(PlayerStats):
            values = [getattr(s.stats, f.name) for s in lines]
            combine = _max_skipping_nulls if f.name in PLAYER_STAT_MAX_FIELDS else _null_aware_sum
            assert getattr(totals.stats, f.name) == combine(values), (season_type, f.name)
    # The rule actually differs on this fixture: the regular-season longs are
    # 53, 47 and 52 plus a start-only line with none, so the sum rule would
    # give None and a plain SUM 152.
    assert career.regular_season is not None
    assert career.regular_season.stats.fg_long == 53


# --- the MAX columns (#334) -------------------------------------------------
#
# `contracts.PLAYER_STAT_MAX_FIELDS` names the columns a career combines with
# MAX, not SUM: the longest field goal of three seasons is the longest of the
# three, never their sum. Their NULL rule differs from `null_aware_sum`
# deliberately -- MAX skips NULL seasons, so a player's one kicking season
# survives the seasons he never kicked in instead of being erased by them.


def test_career_long_is_the_max_of_the_season_longs_not_their_sum(db: PlayerDb) -> None:
    p = db.player("Kicker", position="K")
    for season, fg_long, pt_long in [(2000, 53, 61), (2001, 47, 58), (2002, 52, 62)]:
        db.season(p, season, games=16, **full_stats(fg_long=fg_long, pt_long=pt_long))
    conn = conn_of(db)

    totals = get_player_career(conn, sport="nfl", player_id=p).regular_season

    assert totals is not None
    assert totals.stats.fg_long == 53
    assert totals.stats.pt_long == 62
    # 152 and 53 are both non-null; only one of them is a field goal.
    assert totals.stats.fg_long is not None and totals.stats.fg_long < 70
    assert totals.stats.pt_long is not None and totals.stats.pt_long < 100
    # The columns beside them still add up.
    assert totals.stats.fg_made == 3


def test_a_null_season_long_does_not_erase_the_seasons_that_have_one(db: PlayerDb) -> None:
    p = db.player("Part Time Kicker")
    db.season(p, 2000, games=16, **full_stats(fg_long=None, pt_long=None))
    db.season(p, 2001, games=16, **full_stats(fg_long=48, pt_long=55))
    db.season(p, 2002, games=16, **full_stats(fg_long=41, pt_long=None))
    conn = conn_of(db)

    totals = get_player_career(conn, sport="nfl", player_id=p).regular_season

    assert totals is not None
    assert totals.stats.fg_long == 48
    assert totals.stats.pt_long == 55
    # The null-aware SUM rule is untouched for the columns beside them.
    assert totals.stats.fg_made == 3


def test_a_long_null_in_every_season_stays_none(db: PlayerDb) -> None:
    p = db.player("Never Kicked")
    db.season(p, 2000, games=16, **full_stats(fg_long=None, pt_long=None))
    db.season(p, 2001, games=16, **full_stats(fg_long=None, pt_long=None))
    conn = conn_of(db)

    totals = get_player_career(conn, sport="nfl", player_id=p).regular_season

    assert totals is not None
    assert totals.stats.fg_long is None
    assert totals.stats.pt_long is None
