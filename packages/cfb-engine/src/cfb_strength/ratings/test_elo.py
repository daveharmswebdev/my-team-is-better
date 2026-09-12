"""Tests for the Elo engine: the pure update math, the season-isolated
`EloRating`, and the cross-season `EloCareerRating`.

Style follows `test_keener.py` -- small, hand-built synthetic graphs that
document this module's own algorithm choices -- with one addition: the
pure functions here are pinned to *exact* float values, because Elo's
whole value is reproducibility. A one-ulp drift in `expected_score` is a
silent re-rating of 28 seasons, so it should fail a test rather than pass
an `approx`.
"""

from __future__ import annotations

import math

import pytest

from cfb_strength.contracts import (
    CareerRatingMethod,
    Game,
    RatingMethod,
    TeamRating,
)
from cfb_strength.ratings.elo import (
    ELO_CONFIGS,
    EloCareerRating,
    EloConfig,
    EloRating,
    expected_score,
    game_result,
    mov_multiplier,
    rating_shift,
    revert_between_seasons,
)
from cfb_strength.ratings.keener import KeenerRating

CFB = ELO_CONFIGS["cfb"]
NFL = ELO_CONFIGS["nfl"]

# Arbitrary but distinct team ids, matching test_keener.py's convention.
A, B, C, D = 1, 2, 3, 4


# ---------------------------------------------------------------------------
# Pure update math
# ---------------------------------------------------------------------------


def test_pinned_single_game_update_cfb() -> None:
    """The golden pin for the whole engine: one 1500-v-1500 game, home wins
    by 7, CFB config. Derivation, all in IEEE-754 double:

        elo_diff       = 1500 - 1500 + hfa(100)          = 100.0
        expected_score = 1 / (10 ** (-100/400) + 1)      = 0.6400649998028851
        result         = 1.0 (home won)
        winner_diff    = +100  (winner is the home team)
        denom          = 100 * 0.001 + 2.2               = 2.3
        mov_multiplier = ln(max(7,1) + 1) * (2.2 / 2.3)  = 1.9890310398676687
        shift          = 40 * 1.9890310398676687 * (1.0 - 0.6400649998028851)
                       = 28.636875509073477

    Exact `==` on purpose -- see this module's docstring.
    """
    elo_diff = 100.0
    assert expected_score(elo_diff, CFB) == 0.6400649998028851
    assert mov_multiplier(7, elo_diff, 1.0, CFB) == 1.9890310398676687

    shift = rating_shift(1500.0, 1500.0, 28, 21, False, CFB)
    assert shift == 28.636875509073477
    assert 1500.0 + shift == 1528.6368755090734
    assert 1500.0 - shift == 1471.3631244909266


def test_shift_is_zero_sum() -> None:
    """`home += shift; away -= shift` conserves the pair's total exactly."""
    for elo_home in (1200.0, 1345.5, 1500.0, 1712.25, 2000.0):
        for elo_away in (1100.0, 1500.0, 1633.75, 1890.0):
            for home_points, away_points in (
                (0, 0), (21, 21), (3, 0), (35, 7), (7, 35), (70, 0), (1, 2),
            ):
                for neutral in (False, True):
                    shift = rating_shift(
                        elo_home, elo_away, home_points, away_points, neutral, CFB
                    )
                    assert (elo_home + shift) + (elo_away - shift) == elo_home + elo_away


def test_game_result_is_win_tie_loss() -> None:
    assert game_result(21, 14) == 1.0
    assert game_result(14, 21) == 0.0
    assert game_result(17, 17) == 0.5


def test_expected_score_is_one_half_at_equal_ratings() -> None:
    assert expected_score(0.0, CFB) == 0.5
    assert expected_score(0.0, NFL) == 0.5


def test_expected_score_symmetry() -> None:
    for diff in (0.0, 1.0, 37.5, 100.0, 400.0, 1234.5):
        assert expected_score(diff, CFB) + expected_score(-diff, CFB) == pytest.approx(1.0)


def test_tie_multiplier_is_log_two_times_mov_scale() -> None:
    """A tie has point_diff 0, and `max(|pd|, 1)` floors it at 1, so the
    multiplier is `ln(2) * mov_scale / 1.0`."""
    assert mov_multiplier(0, 0.0, 0.5, CFB) == 1.5249237972318797
    # 0-0 and 21-21 are both zero-margin: identical multiplier.
    assert mov_multiplier(0, 0.0, 0.5, CFB) == mov_multiplier(0, 250.0, 0.5, CFB)

    # A tie between unequal-rated teams still moves ratings: the favorite
    # expected more than 0.5 and gets docked for not delivering.
    shift = rating_shift(1800.0, 1500.0, 17, 17, True, CFB)
    assert shift < 0.0


def test_tie_multiplier_ignores_elo_diff() -> None:
    """Ties bypass the autocorrelation correction entirely (denom == 1.0),
    so the multiplier cannot depend on who was favored."""
    base = mov_multiplier(0, 0.0, 0.5, CFB)
    assert mov_multiplier(0, 500.0, 0.5, CFB) == base
    assert mov_multiplier(0, -500.0, 0.5, CFB) == base


def test_neutral_site_drops_home_field_advantage() -> None:
    home_shift = rating_shift(1500.0, 1500.0, 28, 21, False, CFB)
    neutral_shift = rating_shift(1500.0, 1500.0, 28, 21, True, CFB)
    # On a neutral field the home team was not favored, so beating an
    # equally-rated opponent is worth more.
    assert neutral_shift > home_shift

    # And at equal ratings a neutral game is a coin flip by construction.
    assert expected_score(1500.0 - 1500.0 + 0.0, CFB) == 0.5


def test_underdog_win_produces_larger_shift_than_favorite_win() -> None:
    favorite_win = rating_shift(1800.0, 1500.0, 24, 21, True, CFB)
    underdog_win = rating_shift(1500.0, 1800.0, 24, 21, True, CFB)
    assert underdog_win > favorite_win > 0.0


def test_mov_multiplier_monotonic_in_margin() -> None:
    previous = mov_multiplier(1, 0.0, 1.0, CFB)
    for point_diff in range(2, 71):
        current = mov_multiplier(point_diff, 0.0, 1.0, CFB)
        assert current > previous
        previous = current


def test_mov_multiplier_has_diminishing_returns() -> None:
    """Logarithmic in margin: the 7->14 step is worth more than 21->28."""
    def f(point_diff: int) -> float:
        return mov_multiplier(point_diff, 0.0, 1.0, CFB)

    assert f(14) - f(7) > f(28) - f(21)


def test_autocorrelation_damps_favorite_blowouts() -> None:
    """Same margin, same |elo_diff|: a favorite blowing out an underdog is
    worth less than an underdog blowing out a favorite. This is the
    autocorrelation correction, which exists to stop a dominant team from
    running away with the rating scale."""
    favorite = mov_multiplier(35, 500.0, 1.0, CFB)
    underdog = mov_multiplier(35, -500.0, 1.0, CFB)
    assert favorite < underdog


def test_mov_denominator_guard_prevents_sign_inversion() -> None:
    """The hazard the `_MIN_DENOM_FRACTION` clamp exists for.

    `winner_diff * mov_autocorr + mov_scale` hits exactly 0.0 at
    winner_diff == -2200 with the shipped constants and goes negative
    beyond it -- which without the clamp is a ZeroDivisionError and then,
    worse, a *negative* multiplier that inverts the sign of the whole
    shift and rewards the loser.
    """
    undamped = math.log(35 + 1)  # multiplier with denom == mov_scale

    for winner_diff, away_rating in ((-2200.0, 3800.0), (-3000.0, 4600.0)):
        multiplier = mov_multiplier(35, winner_diff, 1.0, CFB)
        assert math.isfinite(multiplier)
        assert multiplier > 0.0
        # Saturates at exactly 2x the undamped value, never beyond.
        assert multiplier == pytest.approx(2.0 * undamped)
        assert multiplier <= 2.0 * undamped

        # 1500 - away_rating + hfa(100) == winner_diff, and the home team
        # wins, so `result - expected_score` is positive: the shift must be
        # positive too. This is the assertion that actually catches an
        # inverted sign.
        shift = rating_shift(1500.0, away_rating, 42, 7, False, CFB)
        delta = game_result(42, 7) - expected_score(winner_diff, CFB)
        assert delta > 0.0
        assert shift > 0.0

    # The guard must not bind in the normal range: at -1000 the raw denom
    # is 1.2, comfortably above the 1.1 floor.
    assert mov_multiplier(35, -1000.0, 1.0, CFB) == pytest.approx(
        undamped * (CFB.mov_scale / 1.2)
    )


def test_reversion_pulls_toward_mean() -> None:
    """`pytest.approx`, not `==`: `1500.0 * (1/3) + 1800.0 * (1 - 1/3)`
    evaluates to 1700.0000000000002 in IEEE-754, because `1 - 1/3` is one
    ulp above the nearest double to 2/3. Pinning it exactly would be
    pinning a rounding artifact."""
    assert revert_between_seasons(1800.0, CFB) == pytest.approx(1700.0)
    assert revert_between_seasons(CFB.mean, CFB) == pytest.approx(CFB.mean)

    # Strict contraction from both sides.
    assert CFB.mean < revert_between_seasons(1800.0, CFB) < 1800.0
    assert 1200.0 < revert_between_seasons(1200.0, CFB) < CFB.mean

    # The NFL reverts toward 1505, not 1500 -- 538's published constant.
    assert revert_between_seasons(1505.0, NFL) == pytest.approx(1505.0)
    assert revert_between_seasons(1500.0, NFL) > 1500.0


# ---------------------------------------------------------------------------
# EloRating (season-isolated)
# ---------------------------------------------------------------------------


def _game(home: int, away: int, hp: int, ap: int, season: int | None = None) -> Game:
    return Game(
        home_team_id=home,
        away_team_id=away,
        home_points=hp,
        away_points=ap,
        season=season,
    )


def test_order_dependence_is_real() -> None:
    """Elo is path-dependent by construction: the same games in a different
    order give different ratings. This is exactly why
    `compute_ratings._load_games` has to impose a *total* order (season,
    season_type, week, start_date, id) -- contrast
    `test_keener.py::test_keener_is_bit_identical_under_game_reordering`,
    which pins the opposite property for the eigenvector method."""
    games = [
        _game(A, B, 28, 21),
        _game(B, C, 35, 7),
        _game(C, A, 14, 10),
        _game(A, C, 42, 3),
    ]
    forward = EloRating(CFB).rate(games)
    reversed_ = EloRating(CFB).rate(list(reversed(games)))
    assert any(forward[t].rating != reversed_[t].rating for t in forward)


def test_empty_games_returns_empty_dict() -> None:
    assert EloRating(CFB).rate([]) == {}


def test_every_team_starts_at_initial() -> None:
    """One game, so each team's rating is exactly initial +/- one shift."""
    result = EloRating(CFB).rate([_game(A, B, 28, 21)])
    shift = rating_shift(CFB.initial, CFB.initial, 28, 21, False, CFB)
    assert result[A].rating == CFB.initial + shift
    assert result[B].rating == CFB.initial - shift


def test_wins_losses_and_ties() -> None:
    """A tie increments neither wins nor losses, matching Keener."""
    result = EloRating(CFB).rate([
        _game(A, B, 28, 21),
        _game(A, C, 17, 17),
        _game(C, B, 10, 3),
    ])
    assert (result[A].wins, result[A].losses) == (1, 0)
    assert (result[B].wins, result[B].losses) == (0, 2)
    assert (result[C].wins, result[C].losses) == (1, 0)


def test_ratings_sum_is_conserved() -> None:
    games = [
        _game(A, B, 28, 21),
        _game(B, C, 35, 7),
        _game(C, D, 14, 10),
        _game(D, A, 3, 45),
        _game(A, C, 21, 20),
    ]
    result = EloRating(CFB).rate(games)
    assert sum(tr.rating for tr in result.values()) == pytest.approx(
        len(result) * CFB.initial
    )


def test_ranks_are_dense_and_rating_ordered() -> None:
    result = EloRating(CFB).rate([
        _game(A, B, 28, 21),
        _game(B, C, 35, 7),
        _game(C, A, 3, 40),
    ])
    ordered = sorted(result.values(), key=lambda tr: tr.rank)
    assert [tr.rank for tr in ordered] == [1, 2, 3]
    assert ordered[0].rating >= ordered[1].rating >= ordered[2].rating


# ---------------------------------------------------------------------------
# EloCareerRating (cross-season carryover)
# ---------------------------------------------------------------------------


def test_carryover_across_seasons() -> None:
    season_one = [_game(A, B, 28, 21, season=2001)]
    season_two = [_game(A, B, 24, 20, season=2002)]

    end_of_one = EloCareerRating(CFB, {}).rate_through(season_one, 2001)
    both = EloCareerRating(CFB, {}).rate_through(season_one + season_two, 2002)

    expected_start_a = revert_between_seasons(end_of_one[A].rating, CFB)
    expected_start_b = revert_between_seasons(end_of_one[B].rating, CFB)
    shift = rating_shift(expected_start_a, expected_start_b, 24, 20, False, CFB)
    assert both[A].rating == expected_start_a + shift
    assert both[B].rating == expected_start_b - shift


def test_returns_only_teams_that_played_in_target_season() -> None:
    games = [
        _game(A, B, 28, 21, season=2001),
        _game(C, D, 14, 10, season=2001),
        _game(A, C, 30, 27, season=2002),
    ]
    result = EloCareerRating(CFB, {}).rate_through(games, 2002)
    assert set(result) == {A, C}


def test_records_count_target_season_only() -> None:
    """3-0 in season 1, 1-2 in season 2 -> the target-season record only."""
    games = [
        _game(A, B, 28, 0, season=2001),
        _game(A, C, 31, 3, season=2001),
        _game(A, D, 24, 7, season=2001),
        _game(A, B, 10, 20, season=2002),
        _game(A, C, 13, 27, season=2002),
        _game(A, D, 35, 14, season=2002),
    ]
    result = EloCareerRating(CFB, {}).rate_through(games, 2002)
    assert (result[A].wins, result[A].losses) == (1, 2)


def test_carried_rating_survives_a_skipped_season() -> None:
    """A team absent from an intermediate season is still carried; it just
    is not emitted for the seasons it missed."""
    games = [
        _game(A, B, 28, 21, season=2001),
        _game(C, D, 14, 10, season=2002),
        _game(A, C, 21, 20, season=2003),
    ]
    result = EloCareerRating(CFB, {}).rate_through(games, 2003)
    assert set(result) == {A, C}


def test_target_season_before_any_games_returns_empty() -> None:
    games = [_game(A, B, 28, 21, season=2001)]
    assert EloCareerRating(CFB, {}).rate_through(games, 1999) == {}
    assert EloCareerRating(CFB, {}).rate_through([], 2001) == {}


def test_none_season_raises() -> None:
    """`Game.season` is `int | None` only because Keener does not need it.
    A None reaching a career method is a loader bug, not something to
    silently coerce."""
    with pytest.raises(ValueError, match="season"):
        EloCareerRating(CFB, {}).rate_through([_game(A, B, 28, 21)], 2001)


# ---------------------------------------------------------------------------
# Franchise lineage canonicalization
# ---------------------------------------------------------------------------

STL, LA = 900, 901


def test_franchise_lineage_carries_rating_across_relocation() -> None:
    """St. Louis in season 1, Los Angeles in season 2, one franchise: LA's
    season-2 starting rating must be the reverted end of STL's season 1,
    and the emitted key must be LA's team id."""
    games = [
        _game(STL, A, 28, 21, season=2015),
        _game(LA, A, 24, 20, season=2016),
    ]
    successors = {STL: LA}

    season_one = EloCareerRating(CFB, successors).rate_through(games[:1], 2015)
    stl_end = season_one[STL].rating

    result = EloCareerRating(CFB, successors).rate_through(games, 2016)
    assert set(result) == {LA, A}
    assert LA in result and STL not in result

    expected_la_start = revert_between_seasons(stl_end, CFB)
    expected_a_start = revert_between_seasons(season_one[A].rating, CFB)
    shift = rating_shift(expected_la_start, expected_a_start, 24, 20, False, CFB)
    assert result[LA].rating == expected_la_start + shift


def test_lineage_emits_the_predecessor_id_for_a_pre_move_target_season() -> None:
    """The matched inverse of the test above, and the one that catches the
    naive "rewrite every pre-target id to the successor" implementation:
    rating a season the franchise played *as St. Louis* must emit STL's
    team id. Emitting LA's would orphan the row against `team_season` and
    break evidence's name resolution for a season in which LA did not
    exist."""
    games = [
        _game(STL, A, 28, 21, season=2015),
        _game(LA, A, 24, 20, season=2016),
    ]
    result = EloCareerRating(CFB, {STL: LA}).rate_through(games[:1], 2015)
    assert set(result) == {STL, A}
    assert LA not in result


def test_empty_lineage_is_identity() -> None:
    games = [
        _game(A, B, 28, 21, season=2001),
        _game(B, C, 35, 7, season=2002),
        _game(C, A, 14, 10, season=2002),
    ]
    with_empty = EloCareerRating(CFB, {}).rate_through(games, 2002)
    without = EloCareerRating(CFB).rate_through(games, 2002)
    assert set(with_empty) == set(without)
    for team_id, tr in with_empty.items():
        assert tr.rating == without[team_id].rating
        assert tr.wins == without[team_id].wins
        assert tr.losses == without[team_id].losses


def test_lineage_chain_of_three_folds_to_the_final_id() -> None:
    """A -> B -> C must fold A's history all the way to C, not one hop."""
    x, y, z = 910, 911, 912
    games = [
        _game(x, A, 28, 21, season=2001),
        _game(y, A, 24, 20, season=2002),
        _game(z, A, 31, 17, season=2003),
    ]
    result = EloCareerRating(CFB, {x: y, y: z}).rate_through(games, 2003)
    assert set(result) == {z, A}

    # Same franchise, three labels: A has lost three straight to it, so the
    # franchise rating is well above initial by season 3.
    assert result[z].rating > CFB.initial


def test_lineage_cycle_raises() -> None:
    """A bad lineage table must fail fast, not hang a 28-season backfill."""
    with pytest.raises(ValueError, match="cycle"):
        EloCareerRating(CFB, {STL: LA, LA: STL})


# ---------------------------------------------------------------------------
# Protocol conformance. Unlike test_keener.py's duck-typed check, these
# import the real Protocols -- `compute_ratings.compute_and_store`
# dispatches on `isinstance(impl, CareerRatingMethod)`, so both the
# positive and the negative results are load-bearing.
# ---------------------------------------------------------------------------


def test_elo_satisfies_rating_method_protocol() -> None:
    method: RatingMethod = EloRating(CFB)
    result = method.rate([_game(A, B, 20, 10)])
    assert all(isinstance(v, TeamRating) for v in result.values())


def test_elo_career_satisfies_career_rating_method_protocol() -> None:
    method: CareerRatingMethod = EloCareerRating(CFB, {})
    assert isinstance(method, CareerRatingMethod)
    result = method.rate_through([_game(A, B, 20, 10, season=2001)], 2001)
    assert all(isinstance(v, TeamRating) for v in result.values())


def test_season_isolated_elo_is_not_a_career_method() -> None:
    assert not isinstance(EloRating(CFB), CareerRatingMethod)


def test_keener_is_not_a_career_method() -> None:
    """Deliberately lives here, next to the `isinstance` dispatch it
    protects, rather than in test_keener.py -- so it cannot be missed by
    someone editing Keener."""
    assert not isinstance(KeenerRating(), CareerRatingMethod)


# ---------------------------------------------------------------------------
# Shipped constants
# ---------------------------------------------------------------------------


def test_shipped_configs_match_published_constants() -> None:
    """All eight fields of both presets, pinned, so a "harmless" tuning
    tweak has to be a deliberate test edit. The NFL row is 538's published
    tuning verbatim (note mean=1505, not 1500). The CFB row is our own
    uncalibrated first pass -- see issue #87."""
    assert ELO_CONFIGS["nfl"] == EloConfig(
        k=20.0,
        hfa=65.0,
        mean=1505.0,
        initial=1500.0,
        revert=1 / 3,
        scale=400.0,
        mov_scale=2.2,
        mov_autocorr=0.001,
    )
    assert ELO_CONFIGS["cfb"] == EloConfig(
        k=40.0,
        hfa=100.0,
        mean=1500.0,
        initial=1500.0,
        revert=1 / 3,
        scale=400.0,
        mov_scale=2.2,
        mov_autocorr=0.001,
    )
    assert sorted(ELO_CONFIGS) == ["cfb", "nfl"]


def test_unregistered_sport_raises_naming_the_available_sports() -> None:
    """Never fall back to a default config: rating NFL games at k=40/hfa=100
    would be wrong-but-plausible, the worst failure mode."""
    with pytest.raises(ValueError) as exc:
        ELO_CONFIGS["nba"]
    assert "nba" in str(exc.value)
    assert "cfb" in str(exc.value) and "nfl" in str(exc.value)
