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
    EloGameStep,
    EloLedger,
    Game,
    RatingMethod,
    TeamRating,
)
from cfb_strength.ratings.elo import (
    _MIN_DENOM_FRACTION,
    ELO_CONFIGS,
    EloCareerRating,
    EloConfig,
    EloRating,
    expected_score,
    game_result,
    mov_multiplier,
    rating_shift,
    revert_across_offseasons,
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
                (0, 0),
                (21, 21),
                (3, 0),
                (35, 7),
                (7, 35),
                (70, 0),
                (1, 2),
            ):
                for neutral in (False, True):
                    shift = rating_shift(elo_home, elo_away, home_points, away_points, neutral, CFB)
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
    assert mov_multiplier(35, -1000.0, 1.0, CFB) == pytest.approx(undamped * (CFB.mov_scale / 1.2))


def test_mov_multiplier_rejects_non_finite_inputs() -> None:
    """F4. The denominator clamp is `max(...)`, and `max(nan, 1.1)` is `nan`
    in Python -- every comparison against a NaN is False, so a NaN
    `elo_diff` walked straight through the clamp and out of the function.
    `rating_shift` then produced a NaN shift and `elo[root] += shift`
    poisoned that team, its opponents, and every later season, with no
    exception raised anywhere.

    A NaN is not clampable to a correctly-signed bounded value the way an
    extreme `elo_diff` is, so it raises instead.
    """
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite"):
            mov_multiplier(7, bad, 1.0, CFB)
        with pytest.raises(ValueError, match="finite"):
            mov_multiplier(bad, 100.0, 1.0, CFB)
        # A tie takes the `denom = 1.0` branch and must be guarded too.
        with pytest.raises(ValueError, match="finite"):
            mov_multiplier(0, bad, 0.5, CFB)

    # And the guard reaches through `rating_shift`, which is what the walk
    # actually calls.
    with pytest.raises(ValueError, match="finite"):
        rating_shift(math.nan, 1500.0, 28, 21, False, CFB)

    # Sanity: an ordinary call is untouched by the guard.
    assert mov_multiplier(7, 100.0, 1.0, CFB) == 1.9890310398676687


def test_elo_config_rejects_a_silently_wrong_tuning() -> None:
    """F4. `EloConfig` had no validation at all, which is inconsistent with
    `_EloConfigRegistry`'s "refuses to be silently wrong" philosophy twenty
    lines below it.

    Each rejected field maps to a concrete downstream hazard: `scale` is
    `expected_score`'s unguarded divisor, `mov_scale` is the basis of the
    mandatory denominator floor (which evaporates at `mov_scale <= 0`,
    re-enabling the very sign inversion the clamp exists to prevent), `k`
    scales every shift, and a `revert` outside [0, 1] pushes ratings away
    from the mean or oscillates past it instead of contracting.
    """
    base = dict(k=40.0, hfa=100.0, mean=1500.0, initial=1500.0)

    for field_name in ("k", "scale", "mov_scale"):
        for bad in (0.0, -1.0, math.nan, math.inf, -math.inf):
            with pytest.raises(ValueError, match=field_name):
                EloConfig(**{**base, field_name: bad})

    for bad_revert in (-0.001, 1.001, 2.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="revert"):
            EloConfig(**base, revert=bad_revert)

    # The endpoints are legal: revert=0 is "never revert", revert=1 is
    # "reset to the mean every offseason". Both are degenerate but coherent.
    assert EloConfig(**base, revert=0.0).revert == 0.0
    assert EloConfig(**base, revert=1.0).revert == 1.0

    # And nothing about the shipped presets trips the new validation.
    for cfg in ELO_CONFIGS.values():
        assert EloConfig(**vars(cfg)) == cfg


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
    """Issue #83: a tie is tallied as a tie, identically to Keener. Before
    #83 it incremented neither wins nor losses and was silently dropped from
    the record."""
    result = EloRating(CFB).rate(
        [
            _game(A, B, 28, 21),
            _game(A, C, 17, 17),
            _game(C, B, 10, 3),
        ]
    )
    assert (result[A].wins, result[A].losses, result[A].ties) == (1, 0, 1)
    assert (result[B].wins, result[B].losses, result[B].ties) == (0, 2, 0)
    assert (result[C].wins, result[C].losses, result[C].ties) == (1, 0, 1)


def test_elo_and_keener_report_identical_records_including_ties() -> None:
    """`TeamRating.ties` has one definition across every method (contracts.py),
    so the two methods must agree on every team's full record."""
    games = [
        _game(A, B, 28, 21),
        _game(A, C, 17, 17),
        _game(C, B, 10, 3),
        _game(B, D, 3, 3),
        _game(D, A, 24, 0),
    ]
    elo = EloRating(CFB).rate(games)
    keener = KeenerRating().rate(games)
    assert {t: (r.wins, r.losses, r.ties) for t, r in elo.items()} == {
        t: (r.wins, r.losses, r.ties) for t, r in keener.items()
    }


def test_ratings_sum_is_conserved() -> None:
    games = [
        _game(A, B, 28, 21),
        _game(B, C, 35, 7),
        _game(C, D, 14, 10),
        _game(D, A, 3, 45),
        _game(A, C, 21, 20),
    ]
    result = EloRating(CFB).rate(games)
    assert sum(tr.rating for tr in result.values()) == pytest.approx(len(result) * CFB.initial)


def test_ranks_are_dense_and_rating_ordered() -> None:
    result = EloRating(CFB).rate(
        [
            _game(A, B, 28, 21),
            _game(B, C, 35, 7),
            _game(C, A, 3, 40),
        ]
    )
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


def test_career_ties_count_target_season_only() -> None:
    """Issue #83, per `CareerRatingMethod`'s docstring: `ties` counts only
    `target_season` games, exactly like wins/losses. Two prior-season ties
    must not leak into the target season's record, and the target season's
    own tie must not be dropped.

    A lineage predecessor's prior-season tie is included too: ties are keyed
    by the id that played, not the lineage root, same as wins/losses."""
    stl, la = 11, 12
    games = [
        _game(A, B, 14, 14, season=2001),
        _game(A, C, 21, 21, season=2001),
        _game(stl, B, 10, 10, season=2001),
        _game(A, B, 28, 21, season=2002),
        _game(A, C, 20, 20, season=2002),
        _game(la, B, 3, 3, season=2002),
    ]
    result = EloCareerRating(CFB, {stl: la}).rate_through(games, 2002)
    assert set(result) == {A, B, C, la}
    assert (result[A].wins, result[A].losses, result[A].ties) == (1, 0, 1)
    assert (result[B].wins, result[B].losses, result[B].ties) == (0, 1, 1)
    assert (result[C].wins, result[C].losses, result[C].ties) == (0, 0, 1)
    assert (result[la].wins, result[la].losses, result[la].ties) == (0, 0, 1)

    # And the prior season's ties are real when that season is the target.
    earlier = EloCareerRating(CFB, {stl: la}).rate_through(games[:3], 2001)
    assert (earlier[A].wins, earlier[A].losses, earlier[A].ties) == (0, 0, 2)
    assert earlier[stl].ties == 1


def test_carried_rating_survives_a_skipped_season() -> None:
    """A team absent from an intermediate season is still carried; it just
    is not emitted for the seasons it missed.

    Asserts the *rating*, not merely `set(result)`. The set-only version of
    this test passed both before and after the elapsed-offseason fix (F2),
    because which teams are emitted never depended on the reversion count --
    only the numbers did.

    A plays 2001 and 2003 (a two-offseason gap, so two reversions); C plays
    2002 and 2003 (one offseason, one reversion).
    """
    games = [
        _game(A, B, 28, 21, season=2001),
        _game(C, D, 14, 10, season=2002),
        _game(A, C, 21, 20, season=2003),
    ]
    result = EloCareerRating(CFB, {}).rate_through(games, 2003)
    assert set(result) == {A, C}

    a_end_2001 = CFB.initial + rating_shift(CFB.initial, CFB.initial, 28, 21, False, CFB)
    c_end_2002 = CFB.initial + rating_shift(CFB.initial, CFB.initial, 14, 10, False, CFB)
    a_start_2003 = revert_across_offseasons(a_end_2001, CFB, 2)
    c_start_2003 = revert_between_seasons(c_end_2002, CFB)
    shift = rating_shift(a_start_2003, c_start_2003, 21, 20, False, CFB)

    assert result[A].rating == a_start_2003 + shift
    assert result[C].rating == c_start_2003 - shift

    # And two reversions really is two: the same composition applied once
    # (the pre-fix behavior, which counted observed transitions rather than
    # elapsed offseasons) leaves A measurably higher.
    one_reversion_only = revert_between_seasons(a_end_2001, CFB)
    assert one_reversion_only > a_start_2003 > CFB.mean
    assert result[A].rating != one_reversion_only + rating_shift(
        one_reversion_only, c_start_2003, 21, 20, False, CFB
    )


def test_reversion_count_is_elapsed_offseasons_not_observed_transitions() -> None:
    """F2. A team that sits out three seasons reverts four times, not once.

    The bug this pins was a one-line predicate (`last_season[root] != season`)
    that fired once per *observed* season-to-season transition, so a 2001 ->
    2005 reappearance got a single reversion and carried a four-year-stale
    rating -- contradicting `revert_between_seasons`' own docstring ("exactly
    once per team per offseason").
    """
    gapped = [
        _game(A, B, 42, 0, season=2001),
        _game(A, B, 24, 20, season=2005),
    ]
    result = EloCareerRating(CFB, {}).rate_through(gapped, 2005)

    a_end_2001 = CFB.initial + rating_shift(CFB.initial, CFB.initial, 42, 0, False, CFB)
    b_end_2001 = CFB.initial - (a_end_2001 - CFB.initial)
    a_start = revert_across_offseasons(a_end_2001, CFB, 4)
    b_start = revert_across_offseasons(b_end_2001, CFB, 4)
    shift = rating_shift(a_start, b_start, 24, 20, False, CFB)

    assert result[A].rating == a_start + shift
    assert result[B].rating == b_start - shift

    # Four reversions have pulled A most of the way back toward the mean;
    # one would have left it far above. This is the assertion that fails
    # against the pre-fix implementation.
    one_only = revert_between_seasons(a_end_2001, CFB)
    assert abs(a_start - CFB.mean) < abs(one_only - CFB.mean)
    assert result[A].rating < one_only


def test_closed_form_matches_repeated_reversion() -> None:
    """`revert_across_offseasons` is defined as n applications of
    `revert_between_seasons`; the closed form is an optimization, so the
    equivalence is the actual contract and is pinned here.

    `approx`, not `==`, and deliberately so: `mean*revert + elo*(1-revert)`
    and `mean + (elo-mean)*(1-revert)**n` round differently in IEEE-754.
    They agree to ~1e-12 absolute, which is nine orders of magnitude below
    one Elo point.
    """
    for cfg in (CFB, NFL):
        for elo in (1200.0, 1499.0, cfg.mean, 1650.5, 2100.0):
            carried = elo
            for n in range(1, 13):
                carried = revert_between_seasons(carried, cfg)
                assert revert_across_offseasons(elo, cfg, n) == pytest.approx(carried, abs=1e-9)

    # n == 1 is bit-identical, not merely approximate: the common case must
    # not be perturbed by the closed form's different rounding.
    for elo in (1200.0, 1650.5, 2100.0):
        assert revert_across_offseasons(elo, CFB, 1) == revert_between_seasons(elo, CFB)

    # n == 0 is the identity: a team playing two games in the same season
    # must not revert between them.
    assert revert_across_offseasons(1777.25, CFB, 0) == 1777.25


def test_reversion_is_monotone_and_contracting_in_the_gap() -> None:
    """Each extra elapsed offseason moves a rating strictly closer to the
    mean and never overshoots it -- the property that makes the closed form
    a reversion rather than an oscillation."""
    for cfg in (CFB, NFL):
        for elo in (1150.0, 1900.0):
            previous = abs(elo - cfg.mean)
            for n in range(1, 40):
                current = abs(revert_across_offseasons(elo, cfg, n) - cfg.mean)
                assert current < previous
                previous = current
            # A very large gap converges to the mean rather than diverging.
            assert revert_across_offseasons(elo, cfg, 500) == pytest.approx(cfg.mean)


def test_negative_offseason_gap_raises() -> None:
    """A negative gap can only mean `games` was not in ascending season
    order, which `RatingMethod` documents as guaranteed. `(1-revert) ** -n`
    would silently *amplify* the deviation from the mean."""
    with pytest.raises(ValueError, match="non-negative"):
        revert_across_offseasons(1600.0, CFB, -1)


def test_target_season_with_no_games_of_its_own_returns_empty() -> None:
    """No game in the target season -> nothing to emit, even though earlier
    seasons were replayed.

    This used to also assert `rate_through([2001 game], 1999) == {}`. That
    case is now a `ValueError` (see
    `test_games_after_the_target_season_raise`): a game from *after* the
    target violates the caller's contract, and answering it with `{}` was
    only accidentally harmless.
    """
    games = [_game(A, B, 28, 21, season=2001)]
    assert EloCareerRating(CFB, {}).rate_through(games, 2002) == {}
    assert EloCareerRating(CFB, {}).rate_through([], 2001) == {}


def test_games_after_the_target_season_raise() -> None:
    """F1. A post-target season in `games` used to silently emit the rating
    at the end of the *last* season present, not the target one.

    `participants` was populated during the walk but `ratings` was read out
    of `elo` only *after* the whole walk finished, so a 2002 game kept
    moving A's rating after 2001 had been recorded as the target. With the
    two games below the emitted 2001 rating was 1408.4856 -- A's post-2002
    value -- where the correct answer is A's end-of-2001 value,
    1528.6368755090734.

    Safe today only because `_load_games(history=True)` filters
    `season <= ?`. The walk already validates a `None` season one branch
    above, and a wrong number is a worse failure than a crash, so this
    raises rather than snapshotting and continuing.
    """
    games = [
        _game(A, B, 28, 21, season=2001),
        _game(A, B, 24, 20, season=2002),
    ]
    with pytest.raises(ValueError) as exc:
        EloCareerRating(CFB, {}).rate_through(games, 2001)
    message = str(exc.value)
    assert "2002" in message and "2001" in message

    # The boundary must NOT raise: `season == target_season` is the normal
    # case (the target season's own games are part of the replay), and the
    # answer is A's end-of-2001 rating.
    ok = EloCareerRating(CFB, {}).rate_through(games[:1], 2001)
    assert ok[A].rating == 1528.6368755090734

    # Season-isolated `EloRating` has no target season and is unaffected.
    assert set(EloRating(CFB).rate(games)) == {A, B}


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


def test_lineage_members_overlapping_in_the_target_season_raise() -> None:
    """F3. `participants[root] = actual_id` was last-writer-wins.

    If a lineage predecessor and its successor both play `record_season`,
    only one of them survives into `participants` -- the other's team id
    disappears from the result entirely, and its wins/losses are computed
    and then thrown away, while the survivor is handed the *combined*
    franchise rating next to only its own record. Before the fix this
    fixture returned keys `[1, 901]`: STL (900) was simply gone.

    Real data never does this (`franchise_lineage.py`'s three pairs are
    strictly non-overlapping, pinned by
    `test_franchise_lineage.py`), but the premise is now enforced rather
    than assumed -- same reasoning as `_resolve_roots`' cycle guard.
    """
    games = [
        _game(STL, A, 28, 21, season=2016),
        _game(LA, A, 24, 20, season=2016),
    ]
    with pytest.raises(ValueError) as exc:
        EloCareerRating(CFB, {STL: LA}).rate_through(games, 2016)
    message = str(exc.value)
    assert str(STL) in message and str(LA) in message

    # Non-overlapping seasons are the supported case and must stay silent.
    ok = EloCareerRating(CFB, {STL: LA}).rate_through(
        [_game(STL, A, 28, 21, season=2015), _game(LA, A, 24, 20, season=2016)], 2016
    )
    assert set(ok) == {LA, A}


def test_lineage_overlap_outside_the_target_season_is_not_an_error() -> None:
    """Only `record_season` participants are checked. The walk deliberately
    keys Elo state by root across every season, so a predecessor and
    successor sharing an *earlier* season is a lineage-table problem for
    `test_franchise_lineage.py` to catch, not something this guard can see
    -- it only guards the ambiguity in the emitted keys."""
    games = [
        _game(STL, A, 28, 21, season=2015),
        _game(LA, A, 24, 20, season=2015),
        _game(LA, A, 31, 17, season=2016),
    ]
    result = EloCareerRating(CFB, {STL: LA}).rate_through(games, 2016)
    assert set(result) == {LA, A}


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


# ---------------------------------------------------------------------------
# EloLedger (issue #183): the shown work behind a season Elo rating. Every
# number in a step is the value the walk used or produced, so the chain
# identities below are asserted with `==`, not `approx` -- a ledger that is
# merely close to the rating is a recomputation, not a record.
# ---------------------------------------------------------------------------

E = 5

_RESULT_SCORE = {"W": 1.0, "T": 0.5, "L": 0.0}


def _ledger_season() -> list[Game]:
    """Five teams, eight games, in walk order: home wins, away wins, two
    neutral-site games, a home tie and a neutral tie, with every ordering
    field populated so the copy-through can be checked. A plays five games
    (home, away and neutral), so its chain is long enough to catch a
    swapped or dropped step anywhere in the middle."""

    def g(
        home: int,
        away: int,
        hp: int,
        ap: int,
        week: int | None,
        *,
        neutral: bool = False,
        season_type: str = "regular",
        start_date: str | None = None,
    ) -> Game:
        return Game(
            home_team_id=home,
            away_team_id=away,
            home_points=hp,
            away_points=ap,
            neutral_site=neutral,
            season=2009,
            week=week,
            season_type=season_type,
            start_date=start_date,
        )

    return [
        g(A, B, 31, 10, 1, start_date="2009-09-05"),  # A home win
        g(C, A, 24, 27, 2, start_date="2009-09-12"),  # A away win
        g(B, D, 17, 17, 2),  # home tie
        g(A, D, 14, 35, 3, neutral=True),  # neutral, A loses
        g(C, E, 3, 3, 4, neutral=True),  # neutral tie
        g(D, B, 49, 0, None),  # null week
        g(E, A, 20, 21, 5),  # A away win by one
        g(A, C, 38, 7, None, season_type="postseason", start_date="2010-01-01"),
    ]


def _step_pairs(
    games: list[Game], ratings: dict[int, TeamRating]
) -> list[tuple[Game, EloGameStep, EloGameStep]]:
    """Pair each game with its home and away steps, by per-team walk order."""
    cursor: dict[int, int] = {}
    pairs: list[tuple[Game, EloGameStep, EloGameStep]] = []
    for game in games:
        steps: list[EloGameStep] = []
        for team_id in (game.home_team_id, game.away_team_id):
            ledger = ratings[team_id].elo_ledger
            assert ledger is not None
            steps.append(ledger.steps[cursor.get(team_id, 0)])
            cursor[team_id] = cursor.get(team_id, 0) + 1
        pairs.append((game, steps[0], steps[1]))
    return pairs


def test_elo_ledger_chain_is_exact_for_every_team() -> None:
    """Rubric (a): the chain holds bit for bit, and ends on the rating."""
    ratings = EloRating(CFB).rate(_ledger_season())
    assert set(ratings) == {A, B, C, D, E}
    for team_id, tr in ratings.items():
        ledger = tr.elo_ledger
        assert ledger is not None, team_id
        assert ledger.steps, team_id
        assert ledger.steps[0].rating_before == ledger.starting_rating
        for before, after in zip(ledger.steps, ledger.steps[1:]):
            assert after.rating_before == before.rating_after
        for step in ledger.steps:
            assert step.rating_after == step.rating_before + step.shift
        assert [s.game_number for s in ledger.steps] == list(range(1, len(ledger.steps) + 1))
        assert ledger.steps[-1].rating_after == tr.rating
        assert ledger.starting_rating + sum(s.shift for s in ledger.steps) == pytest.approx(
            tr.rating
        )


def test_elo_ledger_steps_re_derive_from_their_own_fields() -> None:
    """Rubric (b): every step's win expectancy, multiplier and shift follow
    from its own fields and the ledger's constants."""
    ratings = EloRating(CFB).rate(_ledger_season())
    for tr in ratings.values():
        ledger = tr.elo_ledger
        assert ledger is not None
        assert ledger.starting_rating == CFB.initial
        assert (
            ledger.k,
            ledger.hfa,
            ledger.scale,
            ledger.mov_scale,
            ledger.mov_autocorr,
            ledger.mov_denom_floor_fraction,
        ) == (
            CFB.k,
            CFB.hfa,
            CFB.scale,
            CFB.mov_scale,
            CFB.mov_autocorr,
            _MIN_DENOM_FRACTION,
        )
        for step in ledger.steps:
            result_score = _RESULT_SCORE[step.result]
            assert expected_score(step.rating_gap, CFB) == pytest.approx(
                step.win_expectancy, abs=1e-9
            )
            multiplier = mov_multiplier(
                step.team_points - step.opponent_points, step.rating_gap, result_score, CFB
            )
            assert multiplier == pytest.approx(step.mov_multiplier, abs=1e-9)
            assert CFB.k * step.mov_multiplier * (
                result_score - step.win_expectancy
            ) == pytest.approx(step.shift, abs=1e-9)
            assert step.rating_gap == pytest.approx(
                step.rating_before - step.opponent_rating_before + step.home_field_adjustment,
                abs=1e-9,
            )
            expected_adjustment = {"home": CFB.hfa, "away": -CFB.hfa, "neutral": 0.0}
            assert step.home_field_adjustment == expected_adjustment[step.venue]
            if step.team_points > step.opponent_points:
                assert step.result == "W"
            elif step.team_points < step.opponent_points:
                assert step.result == "L"
            else:
                assert step.result == "T"


def test_elo_ledger_records_what_the_walk_used_and_copies_the_game() -> None:
    """The two sides of each game, against the game itself (rubric (c) plus
    the field-by-field copy). The home step's numbers are the update
    functions' own outputs, exactly; the away step mirrors them."""
    games = _ledger_season()
    ratings = EloRating(CFB).rate(games)
    pairs = _step_pairs(games, ratings)
    assert len(pairs) == len(games)
    venues: set[str] = set()
    for game, home, away in pairs:
        # Rubric (c).
        assert away.shift == -home.shift
        assert away.mov_multiplier == home.mov_multiplier
        assert home.win_expectancy + away.win_expectancy == pytest.approx(1.0)

        assert (home.opponent_team_id, away.opponent_team_id) == (
            game.away_team_id,
            game.home_team_id,
        )
        assert (home.team_points, home.opponent_points) == (game.home_points, game.away_points)
        assert (away.team_points, away.opponent_points) == (game.away_points, game.home_points)
        assert home.opponent_rating_before == away.rating_before
        assert away.opponent_rating_before == home.rating_before
        for step in (home, away):
            assert (step.week, step.season_type, step.start_date) == (
                game.week,
                game.season_type,
                game.start_date,
            )
            assert step.opponent_name == ""
        if game.neutral_site:
            assert home.venue == away.venue == "neutral"
        else:
            assert (home.venue, away.venue) == ("home", "away")
        venues.update((home.venue, away.venue))

        # Exactly the walk's values, not a recomputation that happens to agree.
        assert home.rating_gap == home.rating_before - away.rating_before + (
            0.0 if game.neutral_site else CFB.hfa
        )
        assert away.rating_gap == -home.rating_gap
        assert home.win_expectancy == expected_score(home.rating_gap, CFB)
        assert away.win_expectancy == 1.0 - home.win_expectancy
        assert home.shift == rating_shift(
            home.rating_before,
            away.rating_before,
            game.home_points,
            game.away_points,
            game.neutral_site,
            CFB,
        )
    assert venues == {"home", "away", "neutral"}


def test_elo_ledger_step_count_is_the_record() -> None:
    """Rubric (d), including ties."""
    ratings = EloRating(CFB).rate(_ledger_season())
    assert any(tr.ties for tr in ratings.values())
    for tr in ratings.values():
        assert tr.elo_ledger is not None
        assert len(tr.elo_ledger.steps) == tr.wins + tr.losses + tr.ties


def test_elo_ledger_carries_the_nfl_constants() -> None:
    """The constants are the config the walk ran with, per sport."""
    ratings = EloRating(NFL).rate(_ledger_season())
    ledger = ratings[A].elo_ledger
    assert ledger is not None
    assert ledger == EloLedger(
        starting_rating=NFL.initial,
        k=NFL.k,
        hfa=NFL.hfa,
        scale=NFL.scale,
        mov_scale=NFL.mov_scale,
        mov_autocorr=NFL.mov_autocorr,
        mov_denom_floor_fraction=_MIN_DENOM_FRACTION,
        steps=ledger.steps,
    )
    assert {s.home_field_adjustment for s in ledger.steps} == {NFL.hfa, -NFL.hfa, 0.0}


def test_elo_ledger_floor_fraction_is_the_constant_the_multiplier_clamps_with() -> None:
    """Issue #194: the ledger names the margin-of-victory denominator floor
    the walk ran with, and the number is tied to behaviour rather than
    copied from a config. With `mov_autocorr` large enough that an
    underdog's win drives the raw denominator below the floor, the walked
    step's multiplier is the undamped `ln(margin + 1)` divided by the
    ledger's own fraction -- exactly 2x at 0.5. A ledger claiming any other
    fraction would name a saturation the multiplier never produced."""
    for cfg in (CFB, NFL):
        for tr in EloRating(cfg).rate(_ledger_season()).values():
            assert tr.elo_ledger is not None
            assert tr.elo_ledger.mov_denom_floor_fraction == _MIN_DENOM_FRACTION

    # One game at B's home, won by A (the away side, so the underdog by
    # `hfa`) by 21. Raw denominator = -100 * 0.02 + 2.2 = 0.2, below the
    # 0.5 * 2.2 = 1.1 floor, so this step ran at the clamp.
    cfg = EloConfig(k=20.0, hfa=100.0, mean=1500.0, initial=1500.0, mov_autocorr=0.02)
    ledger = EloRating(cfg).rate([_game(B, A, 10, 31)])[A].elo_ledger
    assert ledger is not None
    assert ledger.mov_denom_floor_fraction == _MIN_DENOM_FRACTION
    (step,) = ledger.steps
    assert step.result == "W"
    assert step.rating_gap == -cfg.hfa
    floor = ledger.mov_denom_floor_fraction * cfg.mov_scale
    assert step.rating_gap * cfg.mov_autocorr + cfg.mov_scale < floor
    undamped = math.log((step.team_points - step.opponent_points) + 1.0)
    assert step.mov_multiplier == pytest.approx(undamped / ledger.mov_denom_floor_fraction)
    assert step.mov_multiplier == pytest.approx(2.0 * undamped)


def test_elo_ledger_is_none_for_career_elo_and_keener() -> None:
    """Rubric (e): only season-isolated Elo produces a ledger."""
    games = _ledger_season()
    career = EloCareerRating(CFB, {}).rate_through(games, 2009)
    keener = KeenerRating().rate(games)
    assert career and keener
    assert all(tr.elo_ledger is None for tr in career.values())
    assert all(tr.elo_ledger is None for tr in keener.values())
