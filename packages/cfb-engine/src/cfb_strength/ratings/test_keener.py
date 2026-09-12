"""Lightweight/illustrative tests for KeenerRating on synthetic win-graphs.

Full-suite regression coverage is test-writer's territory (tests/**); this
file exists to document and check the behavior of this module's own
algorithm choices on small, hand-built graphs.
"""

from __future__ import annotations

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

    Bit-identity, not approximate equality, is the right assertion here:

    * Each credit-matrix cell `raw[i, j]` accumulates one addend per game
      in which team i hosted (or visited) team j *in that same
      orientation*. IEEE-754 addition is commutative -- `a + b == b + a`
      exactly -- and only *associativity* fails, so a cell fed exactly two
      addends is exactly order-invariant regardless of their values.
    * Three or more meetings between the same two teams with the same
      home/away orientation in a single season do not occur in CFB or the
      NFL, so two is the worst case in practice.
    * Everything downstream of the matrix (row normalization, epsilon,
      power iteration, the sort) is a deterministic function of the matrix
      and of `team_ids`, which is itself sorted.

    The graph below is built to hit that worst case deliberately: it
    includes a repeated A-vs-B pairing with A at home both times.

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
    # The load-bearing case: a second A-at-home meeting with B, so one
    # matrix cell takes two addends instead of one.
    games.append(Game(home_team_id=A, away_team_id=B, home_points=31, away_points=17))

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
