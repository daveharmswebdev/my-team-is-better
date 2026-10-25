"""`cfb_strength.players`' era-adjusted QB score (#440, epic #439 step 1) on a
tiny synthetic league, every number in an assertion worked out by hand (or
with `statistics` from the raw values) here, not read back from the code."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    QB_SCORE_PEAK_SEASONS,
    QB_SCORE_VERSION,
    QB_SCORE_WEIGHTS,
    NotAQuarterbackError,
    QbScore,
    QbScoreSeason,
    UnknownPlayerError,
)
from cfb_strength.players import (
    fit_qb_score_weights,
    get_qb_score,
    get_qb_score_comparison,
)
from tests.test_players_support import PlayerDb, conn_of

W_EPA = QB_SCORE_WEIGHTS["epa_per_dropback"]
W_RUSH = QB_SCORE_WEIGHTS["rush_epa_per_play"]


@pytest.fixture
def db(tmp_path: Path) -> Iterator[PlayerDb]:
    d = PlayerDb(tmp_path / "qb.sqlite3")
    try:
        yield d
    finally:
        d.close()


def qb_season(
    db: PlayerDb,
    player: int,
    season: int,
    *,
    attempts: int | None = 280,
    sacks: int | None = 20,
    carries: int | None = 0,
    passing_epa: float | None = 0.0,
    rushing_epa: float | None = 0.0,
    passing_yards: int | None = 2000,
    passing_tds: int | None = 10,
    passing_interceptions: int | None = 10,
    sack_yards_lost: int | None = 100,
    season_type: str = "regular",
    team: int | None = None,
    sport: str | None = None,
) -> None:
    db.season(
        player,
        season,
        season_type=season_type,
        team=team,
        sport=sport,
        attempts=attempts,
        sacks_suffered=sacks,
        carries=carries,
        passing_epa=passing_epa,
        rushing_epa=rushing_epa,
        passing_yards=passing_yards,
        passing_tds=passing_tds,
        passing_interceptions=passing_interceptions,
        sack_yards_lost=sack_yards_lost,
    )


def three_qb_league(db: PlayerDb, season: int = 2010) -> tuple[int, int, int]:
    """Three qualifying QBs, 300 dropbacks each and no carries: EPA/dropback
    0.1, 0.2, 0.3 and rush EPA/play 0.0, 0.05, 0.1."""
    ids = []
    for i, name in enumerate(["Low", "Mid", "High"]):
        p = db.player(f"{name} {season}")
        qb_season(db, p, season, passing_epa=30.0 * (i + 1), rushing_epa=15.0 * i)
        ids.append(p)
    return ids[0], ids[1], ids[2]


def only_season(score: QbScore, season: int) -> QbScoreSeason:
    matches = [s for s in score.seasons if s.season == season]
    assert len(matches) == 1
    return matches[0]


# --- the era z-score --------------------------------------------------------


def test_z_scores_use_the_seasons_mean_and_population_sd(db: PlayerDb) -> None:
    low, mid, high = three_qb_league(db)
    conn = conn_of(db)
    # mean 0.2; population sd sqrt(((0.1)^2 + 0 + (0.1)^2) / 3) = 0.0816497
    # (the sample sd would be 0.1 and every z would be +-1).
    pop_sd = math.sqrt(0.02 / 3)
    s = only_season(get_qb_score(conn, sport="nfl", player_id=high), 2010)
    assert s.qualifies and s.dropbacks == 300
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.value == pytest.approx(0.3)
    assert s.epa_per_dropback.season_mean == pytest.approx(0.2)
    assert s.epa_per_dropback.season_sd == pytest.approx(pop_sd)
    assert s.epa_per_dropback.z == pytest.approx(0.1 / pop_sd)
    assert s.rush_epa_per_play is not None
    assert s.rush_epa_per_play.value == pytest.approx(0.1)
    assert s.rush_epa_per_play.season_mean == pytest.approx(0.05)
    assert s.rush_epa_per_play.season_sd == pytest.approx(math.sqrt(0.005 / 3))
    assert s.rush_epa_per_play.z == pytest.approx(0.1 / pop_sd)
    assert s.composite == pytest.approx((W_EPA + W_RUSH) * 0.1 / pop_sd)

    m = only_season(get_qb_score(conn, sport="nfl", player_id=mid), 2010)
    assert m.composite == pytest.approx(0.0, abs=1e-12)
    lo = only_season(get_qb_score(conn, sport="nfl", player_id=low), 2010)
    assert lo.composite == pytest.approx(-(W_EPA + W_RUSH) * 0.1 / pop_sd)


def test_rush_epa_per_play_counts_carries_in_the_denominator(db: PlayerDb) -> None:
    three_qb_league(db)
    runner = db.player("Runner")
    qb_season(db, runner, 2010, carries=100, passing_epa=60.0, rushing_epa=40.0)
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=runner), 2010)
    assert s.rush_epa_per_play is not None
    assert s.rush_epa_per_play.value == pytest.approx(40.0 / 400)
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.value == pytest.approx(60.0 / 300)


def test_the_qualifying_line_is_224_dropbacks(db: PlayerDb) -> None:
    three_qb_league(db)
    at_line = db.player("At Line")
    qb_season(db, at_line, 2010, attempts=200, sacks=24, passing_epa=50.0)
    under = db.player("Under")
    # A wild season one dropback short is not judged, and is not in anyone's
    # baseline either.
    qb_season(db, under, 2010, attempts=200, sacks=23, passing_epa=900.0)
    conn = conn_of(db)

    s = only_season(get_qb_score(conn, sport="nfl", player_id=at_line), 2010)
    assert (s.dropbacks, s.qualifies) == (224, True)
    values = [0.1, 0.2, 0.3, 50.0 / 224]
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.season_mean == pytest.approx(statistics.fmean(values))
    assert s.epa_per_dropback.season_sd == pytest.approx(statistics.pstdev(values))

    u_score = get_qb_score(conn, sport="nfl", player_id=under)
    u = only_season(u_score, 2010)
    assert (u.dropbacks, u.qualifies, u.composite, u.in_peak) == (223, False, None, False)
    assert u.epa_per_dropback is not None
    assert u.epa_per_dropback.value == pytest.approx(900.0 / 223)
    assert (u.epa_per_dropback.season_mean, u.epa_per_dropback.season_sd) == (None, None)
    assert u.epa_per_dropback.z is None
    assert (u_score.qualifying_seasons, u_score.career, u_score.peak) == (0, None, None)
    assert u_score.first_scored_season is None


def test_null_attempts_or_sacks_count_as_zero_for_dropbacks(db: PlayerDb) -> None:
    three_qb_league(db)
    p = db.player("No Sacks Tracked")
    qb_season(db, p, 2010, attempts=224, sacks=None, carries=None, passing_epa=10.0)
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=p), 2010)
    assert (s.dropbacks, s.qualifies) == (224, True)


def test_a_traded_season_with_no_team_qualifies_on_its_own_row(db: PlayerDb) -> None:
    three_qb_league(db)
    traded = db.player("Traded")
    # One whole-season row (team_id NULL): nothing to sum.
    qb_season(db, traded, 2010, team=None, attempts=250, sacks=10, passing_epa=52.0)
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=traded), 2010)
    assert (s.dropbacks, s.qualifies) == (260, True)
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.value == pytest.approx(0.2)


def test_rates_are_none_when_their_denominator_is_zero(db: PlayerDb) -> None:
    p = db.player("Never Threw")
    qb_season(db, p, 2010, attempts=0, sacks=0, carries=0, passing_epa=None, rushing_epa=None)
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=p), 2010)
    assert (s.dropbacks, s.qualifies) == (0, False)
    assert (s.epa_per_dropback, s.rush_epa_per_play, s.any_a) == (None, None, None)


# --- ANY/A is shown, never scored ------------------------------------------


def test_any_a_is_computed_and_z_scored_but_never_moves_the_composite(tmp_path: Path) -> None:
    composites = []
    for i, yards in enumerate([1000, 4000]):
        d = PlayerDb(tmp_path / f"anya{i}.sqlite3")
        try:
            low, _, high = three_qb_league(d)
            # Only `high`'s ANY/A differs between the two leagues.
            d.conn.execute(
                "UPDATE player_season_stats SET passing_yards = ? WHERE player_id = ?",
                (yards, high),
            )
            s = only_season(get_qb_score(conn_of(d), sport="nfl", player_id=high), 2010)
            assert s.any_a is not None
            # (yards + 20*10 - 45*10 - 100) / 300
            assert s.any_a.value == pytest.approx((yards + 200 - 450 - 100) / 300)
            assert s.any_a.z is not None
            composites.append(s.composite)
        finally:
            d.close()
    assert composites[0] == composites[1]


def test_a_null_any_a_input_leaves_any_a_none(db: PlayerDb) -> None:
    _, _, high = three_qb_league(db)
    db.conn.execute(
        "UPDATE player_season_stats SET sack_yards_lost = NULL WHERE player_id = ?", (high,)
    )
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=high), 2010)
    assert s.any_a is None
    assert s.composite is not None


# --- NULL EPA ---------------------------------------------------------------


def test_null_passing_epa_in_a_qualifying_season_raises(db: PlayerDb) -> None:
    _, _, high = three_qb_league(db)
    bad = db.player("Bad Row")
    qb_season(db, bad, 2010, passing_epa=None)
    conn = conn_of(db)
    with pytest.raises(ValueError, match="passing_epa"):
        get_qb_score(conn, sport="nfl", player_id=bad)
    # The bad row is in `high`'s baseline too: no baseline is built over it.
    with pytest.raises(ValueError, match="passing_epa"):
        get_qb_score(conn, sport="nfl", player_id=high)


def test_null_rushing_epa_in_a_qualifying_season_raises(db: PlayerDb) -> None:
    three_qb_league(db)
    bad = db.player("Bad Rush")
    qb_season(db, bad, 2010, rushing_epa=None)
    with pytest.raises(ValueError, match="rushing_epa"):
        get_qb_score(conn_of(db), sport="nfl", player_id=bad)


def test_null_epa_in_a_non_qualifying_season_does_not_raise(db: PlayerDb) -> None:
    _, _, high = three_qb_league(db)
    backup = db.player("Backup")
    qb_season(db, backup, 2010, attempts=50, sacks=5, passing_epa=None, rushing_epa=None)
    conn = conn_of(db)
    s = only_season(get_qb_score(conn, sport="nfl", player_id=backup), 2010)
    assert (s.qualifies, s.epa_per_dropback, s.rush_epa_per_play) == (False, None, None)
    assert get_qb_score(conn, sport="nfl", player_id=high).career is not None


# --- career and peak --------------------------------------------------------


def _composite_league(db: PlayerDb, target: int, composites: dict[int, float]) -> None:
    """For each season, a league of two filler QBs plus `target`, with
    `target`'s EPA/dropback and rush rate chosen so its composite is
    whatever sign the dict asks for. Fillers sit at 0.1 and 0.3; target at
    `0.2 + delta`. The exact composite is read back and checked by sum."""
    for season, delta in composites.items():
        for name, epa in [("F1", 30.0), ("F2", 90.0)]:
            qb_season(db, db.player(f"{name} {season}"), season, passing_epa=epa, rushing_epa=0.0)
        qb_season(db, target, season, passing_epa=300 * (0.2 + delta), rushing_epa=0.0)


def test_career_is_the_signed_sum_of_qualifying_composites(db: PlayerDb) -> None:
    p = db.player("Journeyman")
    _composite_league(db, p, {2001: 0.05, 2002: -0.08, 2003: 0.02})
    qb_season(db, p, 2004, attempts=20, sacks=1, passing_epa=50.0)  # not qualifying
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    composites = [s.composite for s in score.seasons if s.qualifies]
    assert len(composites) == 3 and all(c is not None for c in composites)
    assert composites[1] is not None and composites[1] < 0
    assert score.qualifying_seasons == 3
    assert score.career == pytest.approx(sum(c for c in composites if c is not None))
    assert only_season(score, 2004).composite is None


def test_peak_fills_missing_seasons_with_league_average(db: PlayerDb) -> None:
    p = db.player("Short Career")
    _composite_league(db, p, {2001: 0.05, 2002: 0.02})
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    c = [s.composite for s in score.seasons]
    assert c[0] is not None and c[1] is not None
    assert score.peak == pytest.approx((c[0] + c[1] + 0.0 * 3) / QB_SCORE_PEAK_SEASONS)
    assert score.peak_filled_with_average == 3
    assert all(s.in_peak for s in score.seasons)


def test_peak_fill_drags_a_short_positive_career_toward_zero(db: PlayerDb) -> None:
    p = db.player("One Year Wonder")
    _composite_league(db, p, {2001: 0.05})
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert score.career is not None and score.peak is not None
    assert score.peak == pytest.approx(score.career / 5)
    assert score.peak_filled_with_average == 4


def test_peak_is_the_best_five_and_flags_them(db: PlayerDb) -> None:
    p = db.player("Long Career")
    deltas = {2001: 0.01, 2002: -0.05, 2003: 0.06, 2004: 0.03, 2005: -0.01, 2006: 0.08, 2007: 0.0}
    _composite_league(db, p, deltas)
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    by_season = {s.season: s for s in score.seasons}
    best = sorted(deltas, key=lambda y: deltas[y], reverse=True)[:5]
    assert {y for y, s in by_season.items() if s.in_peak} == set(best)
    best_composites = [by_season[y].composite for y in best]
    assert score.peak == pytest.approx(sum(c for c in best_composites if c is not None) / 5)
    assert score.peak_filled_with_average == 0
    assert score.qualifying_seasons == 7


def test_an_all_negative_long_career_has_a_negative_peak_with_no_fill(db: PlayerDb) -> None:
    p = db.player("Bad Long")
    _composite_league(db, p, {y: -0.05 for y in range(2001, 2007)})
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert score.peak is not None and score.peak < 0
    assert score.peak_filled_with_average == 0


# --- identity, seasons, first seasons ---------------------------------------


def test_score_carries_identity_version_and_chronological_seasons(db: PlayerDb) -> None:
    p = db.player("Vet")
    _composite_league(db, p, {2003: 0.01, 2001: 0.02})
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert (score.sport, score.player_id, score.display_name, score.version) == (
        "nfl",
        p,
        "Vet",
        QB_SCORE_VERSION,
    )
    assert [s.season for s in score.seasons] == [2001, 2003]
    assert (score.first_season, score.first_scored_season) == (2001, 2001)


def test_first_season_counts_a_qb_start_before_any_season_row(db: PlayerDb) -> None:
    p = db.player("Pre EPA")
    home, away = db.team("Home"), db.team("Away")
    db.start(db.game(1998, home, away, 20, 10), home, p)
    # A postseason start never counts toward first_season.
    db.start(db.game(1997, home, away, 20, 10, season_type="postseason"), home, p)
    qb_season(db, p, 1999, attempts=50, sacks=0)
    _composite_league(db, p, {2000: 0.01})
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert (score.first_season, score.first_scored_season) == (1998, 2000)
    assert [s.season for s in score.seasons] == [1999, 2000]


def test_a_qb_with_no_rows_has_no_score(db: PlayerDb) -> None:
    p = db.player("Clipboard")
    score = get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert score.seasons == []
    assert (score.qualifying_seasons, score.career, score.peak) == (0, None, None)
    assert score.peak_filled_with_average == 0
    assert (score.first_season, score.first_scored_season) == (None, None)


def test_postseason_rows_are_ignored(db: PlayerDb) -> None:
    low, mid, high = three_qb_league(db)
    qb_season(db, mid, 2010, season_type="postseason", passing_epa=900.0)
    playoff_only = db.player("Playoff Only")
    qb_season(db, playoff_only, 2010, season_type="postseason", passing_epa=900.0)
    conn = conn_of(db)
    score = get_qb_score(conn, sport="nfl", player_id=mid)
    assert len(score.seasons) == 1
    s = score.seasons[0]
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.value == pytest.approx(0.2)
    assert s.epa_per_dropback.season_mean == pytest.approx(0.2)
    assert get_qb_score(conn, sport="nfl", player_id=playoff_only).seasons == []


def test_another_sports_qbs_are_not_in_the_baseline(db: PlayerDb) -> None:
    _, mid, _ = three_qb_league(db)
    college = db.player("College Star", sport="cfb")
    qb_season(db, college, 2010, passing_epa=900.0, sport="cfb")
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=mid), 2010)
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.season_mean == pytest.approx(0.2)


def test_non_qb_seasons_are_not_in_the_baseline(db: PlayerDb) -> None:
    _, mid, _ = three_qb_league(db)
    trick = db.player("Trick Play WR", position="WR")
    qb_season(db, trick, 2010, passing_epa=900.0)
    s = only_season(get_qb_score(conn_of(db), sport="nfl", player_id=mid), 2010)
    assert s.epa_per_dropback is not None
    assert s.epa_per_dropback.season_mean == pytest.approx(0.2)


# --- errors -----------------------------------------------------------------


def test_unknown_player_raises(db: PlayerDb) -> None:
    with pytest.raises(UnknownPlayerError) as exc:
        get_qb_score(conn_of(db), sport="nfl", player_id=12345)
    assert (exc.value.player_id, exc.value.sport) == (12345, "nfl")


def test_a_player_in_another_sport_is_unknown(db: PlayerDb) -> None:
    p = db.player("College", sport="cfb")
    with pytest.raises(UnknownPlayerError):
        get_qb_score(conn_of(db), sport="nfl", player_id=p)


@pytest.mark.parametrize("position", ["WR", "K", None])
def test_a_non_quarterback_raises(db: PlayerDb, position: str | None) -> None:
    p = db.player("Not A QB", position=position)
    with pytest.raises(NotAQuarterbackError) as exc:
        get_qb_score(conn_of(db), sport="nfl", player_id=p)
    assert (exc.value.player_id, exc.value.position) == (p, position)


# --- comparison -------------------------------------------------------------


def test_comparison_names_winners_and_margins(db: PlayerDb) -> None:
    good, bad = db.player("Good"), db.player("Bad")
    for season in (2001, 2002):
        qb_season(db, db.player(f"Filler {season}"), season, passing_epa=60.0)
        qb_season(db, good, season, passing_epa=90.0, rushing_epa=10.0)
        qb_season(db, bad, season, passing_epa=30.0)
    conn = conn_of(db)
    cmp = get_qb_score_comparison(conn, sport="nfl", a=bad, b=good)
    a, b = cmp.a, cmp.b
    assert (a.player_id, b.player_id) == (bad, good)
    assert a.career is not None and b.career is not None
    assert a.peak is not None and b.peak is not None
    assert (cmp.career_winner, cmp.peak_winner) == ("b", "b")
    assert cmp.career_margin == pytest.approx(a.career - b.career)
    assert cmp.peak_margin == pytest.approx(a.peak - b.peak)
    assert cmp.inconclusive is None
    assert (cmp.sport, cmp.version) == ("nfl", QB_SCORE_VERSION)
    assert dict(cmp.weights) == dict(QB_SCORE_WEIGHTS)
    flipped = get_qb_score_comparison(conn, sport="nfl", a=good, b=bad)
    assert (flipped.career_winner, flipped.peak_winner) == ("a", "a")


def test_career_and_peak_can_disagree(db: PlayerDb) -> None:
    # `long_` is a little above average for fifteen years (composite about
    # 0.2 each); `flash` is far above it for one year (about 2.6, a peak of
    # about 0.52 once four average years fill the peak). Career favours
    # long_, peak favours flash.
    long_, flash = db.player("Long"), db.player("Flash")
    _composite_league(db, long_, {y: 0.03 for y in range(2001, 2016)})
    for i in range(10):
        qb_season(db, db.player(f"Filler {i}"), 2020, passing_epa=60.0)
    qb_season(db, flash, 2020, passing_epa=150.0)
    cmp = get_qb_score_comparison(conn_of(db), sport="nfl", a=long_, b=flash)
    assert (cmp.career_winner, cmp.peak_winner) == ("a", "b")


def test_an_exact_tie_has_no_winner(db: PlayerDb) -> None:
    twin1, twin2 = db.player("Twin One"), db.player("Twin Two")
    qb_season(db, db.player("Filler"), 2010, passing_epa=30.0)
    qb_season(db, twin1, 2010, passing_epa=60.0, rushing_epa=5.0)
    qb_season(db, twin2, 2010, passing_epa=60.0, rushing_epa=5.0)
    cmp = get_qb_score_comparison(conn_of(db), sport="nfl", a=twin1, b=twin2)
    assert (cmp.career_winner, cmp.peak_winner) == (None, None)
    assert (cmp.career_margin, cmp.peak_margin) == (0.0, 0.0)
    assert cmp.inconclusive is None


@pytest.mark.parametrize(
    ("a_qualifies", "b_qualifies", "reason"),
    [
        (False, True, "a_no_qualifying_season"),
        (True, False, "b_no_qualifying_season"),
        (False, False, "neither_has_qualifying_season"),
    ],
)
def test_inconclusive_has_no_winners_and_no_margins(
    db: PlayerDb, a_qualifies: bool, b_qualifies: bool, reason: str
) -> None:
    three_qb_league(db)
    a, b = db.player("A"), db.player("B")
    qb_season(db, a, 2010, attempts=300 if a_qualifies else 100, passing_epa=90.0)
    qb_season(db, b, 2010, attempts=300 if b_qualifies else 100, passing_epa=30.0)
    cmp = get_qb_score_comparison(conn_of(db), sport="nfl", a=a, b=b)
    assert cmp.inconclusive == reason
    assert (cmp.career_winner, cmp.peak_winner) == (None, None)
    assert (cmp.career_margin, cmp.peak_margin) == (None, None)


def test_comparing_a_player_with_himself_raises_before_any_lookup(db: PlayerDb) -> None:
    with pytest.raises(ValueError, match="same player") as exc:
        get_qb_score_comparison(conn_of(db), sport="nfl", a=777, b=777)
    assert not isinstance(exc.value, UnknownPlayerError)


def test_comparison_errors_report_a_before_b(db: PlayerDb) -> None:
    qb, wr, wr2 = db.player("QB"), db.player("WR", position="WR"), db.player("TE", position="TE")
    conn = conn_of(db)
    with pytest.raises(UnknownPlayerError) as unknown:
        get_qb_score_comparison(conn, sport="nfl", a=999, b=wr)
    assert unknown.value.player_id == 999
    with pytest.raises(NotAQuarterbackError) as not_qb:
        get_qb_score_comparison(conn, sport="nfl", a=wr, b=999)
    assert not_qb.value.player_id == wr
    with pytest.raises(NotAQuarterbackError) as both:
        get_qb_score_comparison(conn, sport="nfl", a=wr2, b=wr)
    assert both.value.player_id == wr2
    with pytest.raises(UnknownPlayerError) as b_unknown:
        get_qb_score_comparison(conn, sport="nfl", a=qb, b=999)
    assert b_unknown.value.player_id == 999
    with pytest.raises(NotAQuarterbackError) as b_not_qb:
        get_qb_score_comparison(conn, sport="nfl", a=qb, b=wr)
    assert b_not_qb.value.player_id == wr


# --- the weight fit ---------------------------------------------------------


def test_fit_recovers_a_known_linear_relation(db: PlayerDb) -> None:
    # Season 2000: six QBs with independent-ish EPA/dropback and rush rates.
    # Season 2001: each one's total EPA per play is 0.6 * z_epa + 0.2 * z_rush
    # of 2000 (the exact recovery is the next test).
    e = [0.10, 0.20, 0.00, 0.30, 0.15, 0.05]
    r = [0.02, -0.01, 0.05, 0.00, 0.03, -0.02]
    ze = [(v - statistics.fmean(e)) / statistics.pstdev(e) for v in e]
    zr = [(v - statistics.fmean(r)) / statistics.pstdev(r) for v in r]
    t = [0.6 * a + 0.2 * b for a, b in zip(ze, zr, strict=True)]
    for i in range(6):
        p = db.player(f"QB{i}")
        qb_season(db, p, 2000, passing_epa=300 * e[i], rushing_epa=300 * r[i])
        rush_2001 = 0.01 * i  # varies, but the total is what's targeted
        qb_season(db, p, 2001, passing_epa=300 * t[i] - rush_2001, rushing_epa=rush_2001)
    # Not pairs: qualifies in 2000 only, in 2001 only, or in 2000 and 2002.
    qb_season(db, db.player("Gone"), 2000, passing_epa=40.0, rushing_epa=1.0)
    qb_season(db, db.player("New"), 2001, passing_epa=40.0, rushing_epa=1.0)
    gap = db.player("Gap Year")
    qb_season(db, gap, 2000, passing_epa=45.0, rushing_epa=2.0)
    qb_season(db, gap, 2001, attempts=10, sacks=0, passing_epa=1.0)
    # A postseason row and another sport's QB never make a pair.
    qb_season(db, gap, 2001, season_type="postseason", passing_epa=1.0)
    college = db.player("College", sport="cfb")
    qb_season(db, college, 2000, sport="cfb", passing_epa=10.0)
    qb_season(db, college, 2001, sport="cfb", passing_epa=10.0)

    # The off-pair QBs move the season baselines, so the exact weights are
    # only checked on the clean league below; here, what counts as a pair.
    fit = fit_qb_score_weights(conn_of(db), sport="nfl")
    assert fit.n_pairs == 6
    assert (fit.first_season, fit.last_season) == (2000, 2001)
    assert set(fit.weights) == set(QB_SCORE_WEIGHTS)
    assert sum(fit.weights.values()) == pytest.approx(1.0)
    ratio = fit.coefficients["epa_per_dropback"] / fit.coefficients["rush_epa_per_play"]
    assert fit.weights["epa_per_dropback"] / fit.weights["rush_epa_per_play"] == pytest.approx(
        ratio
    )


def test_fit_recovers_known_weights_exactly_on_a_clean_league(db: PlayerDb) -> None:
    e = [0.10, 0.20, 0.00, 0.30, 0.15, 0.05]
    r = [0.02, -0.01, 0.05, 0.00, 0.03, -0.02]
    ze = [(v - statistics.fmean(e)) / statistics.pstdev(e) for v in e]
    zr = [(v - statistics.fmean(r)) / statistics.pstdev(r) for v in r]
    t = [0.6 * a + 0.2 * b for a, b in zip(ze, zr, strict=True)]
    t_sd = statistics.pstdev(t)
    for i in range(6):
        p = db.player(f"QB{i}")
        qb_season(db, p, 2000, passing_epa=300 * e[i], rushing_epa=300 * r[i])
        rush_2001 = 0.01 * i
        qb_season(db, p, 2001, passing_epa=300 * t[i] - rush_2001, rushing_epa=rush_2001)
    fit = fit_qb_score_weights(conn_of(db), sport="nfl")
    assert fit.n_pairs == 6
    assert fit.weights["epa_per_dropback"] == pytest.approx(0.75)
    assert fit.weights["rush_epa_per_play"] == pytest.approx(0.25)
    # z(t) = t / sd(t) since mean(t) = 0.
    assert fit.coefficients["epa_per_dropback"] == pytest.approx(0.6 / t_sd)
    assert fit.coefficients["rush_epa_per_play"] == pytest.approx(0.2 / t_sd)


def test_fit_with_no_pairs_raises(db: PlayerDb) -> None:
    three_qb_league(db)
    with pytest.raises(ValueError, match="pair"):
        fit_qb_score_weights(conn_of(db), sport="nfl")
