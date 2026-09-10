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
