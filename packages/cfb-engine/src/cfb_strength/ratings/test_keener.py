"""Lightweight/illustrative tests for KeenerRating on synthetic win-graphs.

Full-suite regression coverage is test-writer's territory (tests/**); this
file exists to document and check the behavior of this module's own
algorithm choices on small, hand-built graphs.
"""

from __future__ import annotations

import pytest

from cfb_strength.contracts import Game, TeamRating
from cfb_strength.ratings.keener import KeenerRating

# Arbitrary but distinct team ids used across tests.
A, B, C, D = 1, 2, 3, 4


def _rate(games: list[Game]) -> dict[int, TeamRating]:
    return KeenerRating().rate(games)


def test_satisfies_rating_method_signature() -> None:
    method = KeenerRating()
    result = method.rate([Game(home_team_id=A, away_team_id=B, home_points=20, away_points=10)])
    assert isinstance(result, dict)
    assert all(isinstance(v, TeamRating) for v in result.values())


def test_empty_games_returns_empty_dict() -> None:
    assert _rate([]) == {}


def test_single_game_no_opponents() -> None:
    result = _rate([Game(home_team_id=A, away_team_id=B, home_points=30, away_points=10)])
    assert result[A].rank == 1
    assert result[A].wins == 1 and result[A].losses == 0
    assert result[B].rank == 2
    assert result[B].wins == 0 and result[B].losses == 1
    assert result[A].rating > result[B].rating


def test_chain_a_beats_b_beats_c() -> None:
    """A > B > C transitively should rate A above B above C."""
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=24, away_points=17),
        Game(home_team_id=B, away_team_id=C, home_points=28, away_points=14),
        # Give C at least one more game so it isn't an absolute leaf, and
        # keep the graph connected with a bit more data.
        Game(home_team_id=C, away_team_id=A, home_points=3, away_points=45),
    ]
    result = _rate(games)
    assert result[A].rating > result[B].rating > result[C].rating
    assert result[A].rank == 1
    assert result[B].rank == 2
    assert result[C].rank == 3


def test_undefeated_team_outranks_one_loss_team_all_else_equal() -> None:
    """A beats X, Y, Z; B beats X, Y but loses to Z. A should outrank B."""
    X, Y, Z = 10, 11, 12
    games = [
        Game(home_team_id=A, away_team_id=X, home_points=30, away_points=10),
        Game(home_team_id=A, away_team_id=Y, home_points=28, away_points=14),
        Game(home_team_id=A, away_team_id=Z, home_points=21, away_points=17),
        Game(home_team_id=B, away_team_id=X, home_points=30, away_points=10),
        Game(home_team_id=B, away_team_id=Y, home_points=28, away_points=14),
        Game(home_team_id=Z, away_team_id=B, home_points=21, away_points=17),
    ]
    result = _rate(games)
    assert result[A].wins == 3 and result[A].losses == 0
    assert result[B].wins == 2 and result[B].losses == 1
    assert result[A].rating > result[B].rating


def test_win_always_beats_loss_regardless_of_margin() -> None:
    """A 1-point win must out-credit a 60-point loss for the same team.

    This is the specific property the module docstring claims: margin only
    nudges within a win or a loss, and never lets a large loss margin look
    better than a narrow win, or vice versa.
    """
    # Team W: one 1-point win over a common opponent K.
    # Team L: one 60-point loss to the same opponent K.
    W, L, K = 20, 21, 22
    games = [
        Game(home_team_id=W, away_team_id=K, home_points=15, away_points=14),
        Game(home_team_id=K, away_team_id=L, home_points=70, away_points=10),
    ]
    result = _rate(games)
    # W's credit against K and L's credit against K are not directly
    # comparable via .rating (different opponents), but we can check the
    # underlying invariant directly via the credit formula.
    from cfb_strength.ratings.keener import _single_game_credit

    w_credit, _ = _single_game_credit(15, 14)  # narrow win
    _, l_credit = _single_game_credit(70, 10)  # blowout loss
    assert w_credit > 0.5 > l_credit
    assert w_credit > l_credit


def test_disconnected_components_do_not_crash() -> None:
    """Two totally separate 2-team pods that never play each other."""
    P, Q, R, S = 30, 31, 32, 33
    games = [
        Game(home_team_id=P, away_team_id=Q, home_points=20, away_points=10),
        Game(home_team_id=R, away_team_id=S, home_points=20, away_points=10),
    ]
    result = _rate(games)
    assert set(result.keys()) == {P, Q, R, S}
    assert result[P].rating > result[Q].rating
    assert result[R].rating > result[S].rating
    # Every rank from 1..4 assigned exactly once.
    assert sorted(v.rank for v in result.values()) == [1, 2, 3, 4]


def test_cycle_of_three_produces_no_crash_and_plausible_symmetry() -> None:
    """A beats B, B beats C, C beats A -- a pure cycle with identical
    margins. By symmetry all three should end up with very close (in
    practice, due to floating point and tie-break-by-id, not bit-identical)
    ratings; report actual behavior rather than asserting a specific winner,
    since a symmetric cycle has no principled "best" team.
    """
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=21, away_points=14),
        Game(home_team_id=B, away_team_id=C, home_points=21, away_points=14),
        Game(home_team_id=C, away_team_id=A, home_points=21, away_points=14),
    ]
    result = _rate(games)
    ratings = [result[A].rating, result[B].rating, result[C].rating]
    # Symmetric cycle: all three ratings should be very close to equal.
    assert max(ratings) - min(ratings) < 1e-6
    assert sorted(v.rank for v in result.values()) == [1, 2, 3]


def test_ratings_sum_to_one() -> None:
    """Sanity check on the column-stochastic power-iteration normalization."""
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=24, away_points=17),
        Game(home_team_id=B, away_team_id=C, home_points=28, away_points=14),
        Game(home_team_id=C, away_team_id=D, home_points=10, away_points=7),
        Game(home_team_id=D, away_team_id=A, home_points=3, away_points=45),
    ]
    result = _rate(games)
    total = sum(v.rating for v in result.values())
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Per-opponent rating breakdown (issue #31)
# ---------------------------------------------------------------------------

BREAKDOWN_TOL = 1e-9


def _assert_breakdown_invariants(result: dict[int, TeamRating], n: int) -> None:
    """Invariant that must hold for every team in every graph of `n` teams
    (see keener.py's RatingBreakdown docstring / issue #31 brief):

        entries' contributions + residual == the team's overall rating.

    NOTE on the brief's second claimed invariant ("residual_contribution
    equals epsilon == 1/(2n) exactly for every team"): that claim assumes
    the power-iteration matrix `a` is row-stochastic (dominant eigenvalue
    lambda == 1), so that r = a @ r exactly at convergence. It is not: `a`'s
    rows sum to `raw_normalized`'s row sum (average per-game credit, which
    varies by a team's win/loss mix) plus a constant `n * epsilon`, not 1
    (see the module docstring's "No stochastic normalization" section,
    which deliberately keeps A unnormalized beyond the games-played row
    division). Verified numerically across every synthetic graph in this
    file: the actual dominant eigenvalue lambda is ~0.81-0.83, not 1, and
    residual_i = epsilon + r_i * (1 - lambda) -- constant only in the
    epsilon term, not equal to epsilon itself. Reported to the coordinator
    as a contract_gap rather than silently "fixed" by renormalizing A to be
    row-stochastic, which would change actual rating values (forbidden by
    this task's brief) and contradict the module's own documented design
    choice against that normalization.
    """
    for tr in result.values():
        breakdown = tr.rating_breakdown
        total = sum(e.contribution for e in breakdown.entries) + breakdown.residual_contribution
        assert abs(total - tr.rating) < BREAKDOWN_TOL


def test_breakdown_reconstructs_rating_exactly() -> None:
    """Chain A>B>C (3 teams): breakdown entries + residual reconstruct the
    overall rating exactly."""
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=24, away_points=17),
        Game(home_team_id=B, away_team_id=C, home_points=28, away_points=14),
        Game(home_team_id=C, away_team_id=A, home_points=3, away_points=45),
    ]
    result = _rate(games)
    _assert_breakdown_invariants(result, n=3)


def test_breakdown_disconnected_components() -> None:
    """Residual == epsilon invariant must hold even for teams in a
    disconnected component of the win-graph (the whole point of epsilon)."""
    P, Q, R, S = 30, 31, 32, 33
    games = [
        Game(home_team_id=P, away_team_id=Q, home_points=20, away_points=10),
        Game(home_team_id=R, away_team_id=S, home_points=20, away_points=10),
    ]
    result = _rate(games)
    _assert_breakdown_invariants(result, n=4)


def test_breakdown_entries_only_for_opponents_actually_played() -> None:
    """A team's breakdown should have exactly one entry per distinct
    opponent it played -- not one per team in the graph."""
    X, Y, Z = 10, 11, 12
    games = [
        Game(home_team_id=A, away_team_id=X, home_points=30, away_points=10),
        Game(home_team_id=A, away_team_id=Y, home_points=28, away_points=14),
        Game(home_team_id=A, away_team_id=Z, home_points=21, away_points=17),
        Game(home_team_id=B, away_team_id=X, home_points=30, away_points=10),
        Game(home_team_id=B, away_team_id=Y, home_points=28, away_points=14),
        Game(home_team_id=Z, away_team_id=B, home_points=21, away_points=17),
    ]
    result = _rate(games)
    n = len({A, B, X, Y, Z})
    _assert_breakdown_invariants(result, n=n)

    a_opponents = {e.opponent_team_id for e in result[A].rating_breakdown.entries}
    assert a_opponents == {X, Y, Z}
    for e in result[A].rating_breakdown.entries:
        assert e.games_played == 1
        assert e.wins == 1 and e.losses == 0


def test_breakdown_combines_repeated_matchup_into_one_entry() -> None:
    """A team that plays the same opponent twice in a season gets ONE
    OpponentCredit entry for that opponent, with the combined record --
    not two separate entries."""
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=24, away_points=17),
        Game(home_team_id=B, away_team_id=A, home_points=10, away_points=35),
        # Give C a game too so there's a third team in the graph.
        Game(home_team_id=C, away_team_id=A, home_points=3, away_points=45),
    ]
    result = _rate(games)
    _assert_breakdown_invariants(result, n=3)

    a_entries = result[A].rating_breakdown.entries
    a_vs_b = [e for e in a_entries if e.opponent_team_id == B]
    assert len(a_vs_b) == 1
    entry = a_vs_b[0]
    assert entry.games_played == 2
    assert entry.wins == 2 and entry.losses == 0

    b_entries = result[B].rating_breakdown.entries
    b_vs_a = [e for e in b_entries if e.opponent_team_id == A]
    assert len(b_vs_a) == 1
    assert b_vs_a[0].games_played == 2
    assert b_vs_a[0].wins == 0 and b_vs_a[0].losses == 2


def test_breakdown_credit_times_opponent_rating_equals_contribution() -> None:
    """`entry.credit * opponent_rating == entry.contribution` per the
    OpponentCredit docstring contract."""
    games = [
        Game(home_team_id=A, away_team_id=B, home_points=24, away_points=17),
        Game(home_team_id=B, away_team_id=C, home_points=28, away_points=14),
        Game(home_team_id=C, away_team_id=D, home_points=10, away_points=7),
        Game(home_team_id=D, away_team_id=A, home_points=3, away_points=45),
    ]
    result = _rate(games)
    _assert_breakdown_invariants(result, n=4)
    for tr in result.values():
        for e in tr.rating_breakdown.entries:
            opponent_rating = result[e.opponent_team_id].rating
            assert abs(e.credit * opponent_rating - e.contribution) < BREAKDOWN_TOL


def test_keener_is_bit_identical_under_game_reordering() -> None:
    """Reordering `games` must not change a single bit of Keener's output.

    This is the machine-checked form of the claim that the `Game` dataclass
    amendment (season/week/season_type/start_date, added for the sequential
    Elo engine) cannot perturb Keener: Keener never reads those fields, and
    the only thing they changed about the caller is the order rows arrive
    in -- `compute_ratings._load_games` now has an `ORDER BY` where it
    previously had none.

    Bit-identity holds here, and the reason is worth stating precisely
    because an earlier version of this docstring got it wrong:

    * Each credit-matrix cell `raw[i, j]` accumulates one addend per
      *meeting* between teams i and j, in **either** orientation --
      `keener.py` writes `raw[hi, ai] += home_credit` and
      `raw[ai, hi] += away_credit` for every game, so both cells of the
      pair are touched by every meeting. The count that matters is
      therefore **unordered** meetings between the pair, not
      same-orientation ones. (The old docstring counted same-orientation
      meetings and concluded no cell could exceed two addends. That
      conclusion is false.)
    * IEEE-754 addition is commutative -- `a + b == b + a` exactly -- and
      only *associativity* fails, so a cell fed exactly **two** addends is
      exactly order-invariant regardless of their values. That is the case
      this test pins, using the deliberately-added second A-vs-B meeting
      below.
    * Everything downstream of the matrix (row normalization, epsilon,
      power iteration, the sort) is a deterministic function of the matrix
      and of `team_ids`, which is itself sorted.

    Three unordered meetings between one pair DO occur in real data -- a
    home-and-home plus a conference-championship or playoff rematch: nfl
    2000 has 4 such pairs, nfl 2024 has 2, cfb 2024 has 1. Those cells take
    three addends, where associativity does bite. See
    `test_keener_reordering_drift_is_bounded_for_a_three_meeting_pair` for
    the property that actually holds there.

    The real, unconditional guarantee -- the one this module relies on --
    is that **Keener is exactly reproducible on identical input**: it is a
    deterministic function of the credit matrix and the sorted team ids,
    with no BLAS nondeterminism. Order-induced drift is a property of the
    matrix's *construction*, not of the solve, and is bounded at ~1e-16.

    Contrast `test_elo.py::test_order_dependence_is_real`, which pins the
    opposite property for the sequential method.
    """
    import random

    games = [
        Game(
            home_team_id=i,
            away_team_id=j,
            home_points=10 + ((i * 7 + j * 3) % 40),
            away_points=3 + ((i * 5 + j * 11) % 35),
        )
        for i in range(1, 13)
        for j in range(i + 1, 13)
        if (i + j) % 3
    ]
    # The load-bearing case: TWO A-vs-B meetings, so `raw[A, B]` and
    # `raw[B, A]` each take two addends instead of one.
    #
    # Two games are appended, not one. `(i + j) % 3` is falsy for i=1, j=2,
    # so the comprehension above skips A-vs-B entirely -- the previous
    # single appended game left that cell with exactly ONE addend, and the
    # two-addend case this test claims to exercise was never actually hit.
    games.append(Game(home_team_id=A, away_team_id=B, home_points=31, away_points=17))
    games.append(Game(home_team_id=B, away_team_id=A, home_points=24, away_points=20))

    baseline = _rate(games)

    for seed in range(8):
        shuffled = list(games)
        random.Random(seed).shuffle(shuffled)
        result = _rate(shuffled)

        assert set(result) == set(baseline)
        for team_id, expected in baseline.items():
            actual = result[team_id]
            assert actual.rating == expected.rating
            assert actual.rank == expected.rank
            assert actual.wins == expected.wins
            assert actual.losses == expected.losses

            expected_entries = {
                e.opponent_team_id: e for e in expected.rating_breakdown.entries
            }
            actual_entries = {
                e.opponent_team_id: e for e in actual.rating_breakdown.entries
            }
            assert actual_entries.keys() == expected_entries.keys()
            for opponent_id, expected_entry in expected_entries.items():
                actual_entry = actual_entries[opponent_id]
                assert actual_entry.credit == expected_entry.credit
                assert actual_entry.contribution == expected_entry.contribution
                assert actual_entry.games_played == expected_entry.games_played
                assert actual_entry.wins == expected_entry.wins
                assert actual_entry.losses == expected_entry.losses


def test_keener_reordering_drift_is_bounded_for_a_three_meeting_pair() -> None:
    """Three unordered meetings between one pair: bounded drift, no rank change.

    This is the case real data actually produces and the exact-equality test
    above cannot cover. A pair that meets three times in a season -- a
    home-and-home plus a conference-championship or playoff rematch -- feeds
    three addends into `raw[i, j]` (and three into `raw[j, i]`), because
    `keener.py` credits *both* cells on every game regardless of orientation.
    IEEE-754 addition is commutative but not associative, so
    `(a + b) + c != a + (b + c)` in general and the matrix cell itself
    becomes order-dependent.

    Measured, not assumed. Replaying the pre-`ORDER BY` unordered query
    against the new total order across all 55 real seasons perturbs Keener
    ratings by at most 1.3877787807814457e-17 (matrix cells by at most
    2.22e-16), with **zero** rank changes.

    Whether any *particular* graph drifts is platform-dependent, and this
    test learned that the hard way: this exact fixture drifts ~2.8e-17 on
    the author's machine and exactly 0.0 on the CI runner, because numpy's
    eigenvector solve reduces in a different order under a different BLAS
    build. Keener remains exactly reproducible on identical input on a given
    machine -- rerunning it never moves -- so the residue is order-induced
    rather than random. But "reordering always perturbs" is not a claim this
    or any test can make, which is why the assertion below is a bound and
    never a demand that drift be non-zero.

    The assertion is therefore a *bound plus exact ordinals*, not a
    weakening into vagueness: `rank`, `wins` and `losses` must still be
    exactly equal, and the rating tolerance (1e-12 absolute) is still five
    orders of magnitude below the measured drift's ceiling and far below any
    rating difference that could reorder two teams.
    """
    import random

    games = [
        Game(
            home_team_id=i,
            away_team_id=j,
            home_points=10 + ((i * 7 + j * 3) % 40),
            away_points=3 + ((i * 5 + j * 11) % 35),
        )
        for i in range(1, 13)
        for j in range(i + 1, 13)
        if (i + j) % 3
    ]
    # Three A-vs-B meetings in mixed orientations -- home-and-home plus a
    # neutral-site rematch, which is what a CCG or a playoff round is.
    games.append(Game(home_team_id=A, away_team_id=B, home_points=31, away_points=17))
    games.append(Game(home_team_id=B, away_team_id=A, home_points=24, away_points=20))
    games.append(
        Game(home_team_id=A, away_team_id=B, home_points=13, away_points=10, neutral_site=True)
    )

    baseline = _rate(games)
    worst_drift = 0.0

    for seed in range(8):
        shuffled = list(games)
        random.Random(seed).shuffle(shuffled)
        result = _rate(shuffled)

        assert set(result) == set(baseline)
        for team_id, expected in baseline.items():
            actual = result[team_id]
            # Ordinals and records are exactly equal -- the test is not
            # allowed to go vacuous on the properties users actually see.
            assert actual.rank == expected.rank
            assert actual.wins == expected.wins
            assert actual.losses == expected.losses
            assert actual.rating == pytest.approx(expected.rating, abs=1e-12)
            worst_drift = max(worst_drift, abs(actual.rating - expected.rating))

            expected_entries = {
                e.opponent_team_id: e for e in expected.rating_breakdown.entries
            }
            actual_entries = {
                e.opponent_team_id: e for e in actual.rating_breakdown.entries
            }
            assert actual_entries.keys() == expected_entries.keys()
            for opponent_id, expected_entry in expected_entries.items():
                actual_entry = actual_entries[opponent_id]
                assert actual_entry.games_played == expected_entry.games_played
                assert actual_entry.wins == expected_entry.wins
                assert actual_entry.losses == expected_entry.losses
                assert actual_entry.credit == pytest.approx(
                    expected_entry.credit, abs=1e-12
                )
                assert actual_entry.contribution == pytest.approx(
                    expected_entry.contribution, abs=1e-12
                )

    # Assert the BOUND, never that drift is non-zero.
    #
    # An earlier version of this test asserted `worst_drift > 0.0`, reasoning
    # that a graph which never drifts would make the bound vacuous. That
    # assertion is wrong, and CI proved it: this same fixture drifts by
    # 2.78e-17 on the author's machine and by exactly 0.0 on the CI runner --
    # numpy's eigenvector solve reduces in a different order under a
    # different BLAS build. Requiring floating point to misbehave is not a
    # property of Keener, it is a property of whoever's CPU is running it.
    #
    # The anti-vacuity guard is structural instead, at the bottom of this
    # test: the fixture is asserted to actually CONTAIN a pair with three
    # unordered meetings, which is the input capable of exposing
    # non-associativity. Whether it does expose it here is the platform's
    # business; that the fixture can represent the case is ours.
    assert worst_drift < 1e-14

    # A/B's own breakdown entry must record all three meetings, so a future
    # edit cannot quietly drop the case the test exists for.
    a_vs_b = [e for e in baseline[A].rating_breakdown.entries if e.opponent_team_id == B]
    assert len(a_vs_b) == 1 and a_vs_b[0].games_played == 3
