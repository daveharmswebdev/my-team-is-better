"""Keener's eigenvector rating method.

Implements the ranking method of J.P. Keener, "The Perron-Frobenius Theorem
and the Ranking of Football Teams" (SIAM Review, 1993): a team's rating is
defined recursively as a weighted sum of the ratings of the teams it played,
weighted by how well it performed against each of them. Written as a linear
system r = A r, the rating vector r is the dominant eigenvector of a
nonnegative matrix A, whose existence and (up to scale) uniqueness is
guaranteed by the Perron-Frobenius theorem provided A is irreducible and
nonnegative. This is the same fixed-point idea as PageRank's link-following
random walk, applied to a "who played whom, and how well" graph instead of
a hyperlink graph.

Credit formula (A[i][j] -- what team i "earns" from having played team j)
--------------------------------------------------------------------------
Keener's original paper scores a single game by score ratio, e.g.
``h_ij = points_i / (points_i + points_j)``, and then applies a smoothing
transform to compress that ratio's influence. That family of formulas makes
a team's credit a continuous, unbounded-in-effect function of margin of
victory (MOV): score enough blowouts and average MOV can outweigh a
head-to-head loss. This is a documented, real distortion -- it is why real
BCS-era computer polls banned MOV as an input, and it is exactly the failure
mode this project's own history (take 1) hit on the actual 2005 season
(USC's blowout margins outrating a Texas team that beat USC head-to-head).

An earlier revision of this module addressed that with a saturating-margin
formula (``margin / (margin + MARGIN_SCALE)``) layered onto a 0.5/0.5
midpoint. That formula was win/loss-dominant on its own, but running it
against the full 2000-2023 golden dataset (undisputed national champions)
surfaced two further failures that formula alone could not explain: 2001
(undefeated 12-0 Miami (FL) ranked #3, behind two-loss Tennessee) and 2013
(undefeated Florida State ranked #2, behind three-loss Stanford). The root
cause was not the credit formula but the *lack of per-team normalization*:
without dividing a team's outgoing credit row by its own games-played
count, a team that plays more games (Tennessee's 13 vs. Miami's 12, in a
season with unequal conference-championship/bowl participation) injects
more total credit into the recursive system independent of how well it
played, which is exactly the kind of schedule-length artifact Keener's own
paper normalizes away. Fixing normalization alone was not sufficient,
though: it flipped a *third* golden year (2019, undefeated LSU) into a new
failure, because the old saturating-margin formula's fixed 0.5 win/loss
midpoint interacts with per-row normalization in a way that lets enough
merely-decent wins outweigh a few good ones once every row is rescaled to
the same total weight.

The fix that passes all seven golden years (five must-match, two contested)
combines both changes:

1. Normalize each team's raw outgoing credit row by its games-played count,
   so a team's total "vote weight" into the recursive system does not scale
   with how many games it happened to play (Keener's own original design
   choice, not a departure from it).
2. Replace the saturating-margin formula with a clamped score-share formula
   that keeps win/loss strictly dominant but is shaped differently: each
   team's per-game credit is a fixed win/loss base rate, nudged by a capped
   share of that game's total points scored.

    share_i  = clamp(points_i / (points_i + points_j), 0.5 - MAX_SKEW, 0.5 + MAX_SKEW)

    winner's credit  = BASE_WIN  + MARGIN_NUDGE * (share_winner - 0.5)
    loser's credit   = BASE_LOSS + MARGIN_NUDGE * (share_loser - (0.5 - MAX_SKEW))

With ``MAX_SKEW = 0.35``, ``BASE_WIN = 0.6``, ``BASE_LOSS = 0.05``, and
``MARGIN_NUDGE = 0.3``: a winner's credit always lies in
``[BASE_WIN, BASE_WIN + MARGIN_NUDGE * MAX_SKEW]`` = ``[0.6, 0.705]``, and a
loser's credit always lies in
``[BASE_LOSS, BASE_LOSS + MARGIN_NUDGE * MAX_SKEW]`` = ``[0.05, 0.155]``.
Because ``BASE_WIN`` (0.6) strictly exceeds the maximum possible loss credit
(0.155), a win always outweighs a loss regardless of margin or how a
team's raw score share is clamped -- the same win/loss-dominance invariant
the previous formula guaranteed, verified by the same
``test_win_always_beats_loss_regardless_of_margin`` property test, now
against the new formula. Margin still only nudges a team within its own
win or loss band via the clamped share, never across the win/loss
boundary; the clamp (``MAX_SKEW``) additionally caps how much a single
lopsided score can move that nudge, so an extreme (e.g. 70-0) score is
capped at the same nudge as, say, a 65% points share. A tied game (score
difference of 0; not possible under current NCAA rules but handled
defensively) splits credit 0.5 / 0.5.

Irreducibility / disconnected components / periodicity
---------------------------------------------------------
Real win-graphs are not fully connected (e.g. an FCS team that only plays
other FCS teams no FBS team has faced). To guarantee the Perron-Frobenius
premises (a strictly positive, irreducible, primitive matrix -> a unique
positive dominant eigenvalue with a unique positive eigenvector, found by
power iteration) regardless of actual graph connectivity, a small constant
EPSILON is added to *every* entry of the raw credit matrix, including the
diagonal, exactly as Keener's paper itself proposes ("as if every team
played a tiny bit of every other team, and itself"). This does two things
at once: it makes disconnected components resolve to a sane (if imprecise,
for teams truly cut off from the main component) rating rather than
crashing or producing a degenerate zero, and it breaks a real periodicity
trap -- a matrix with an exact zero diagonal restricted to exactly two
teams that only played each other is bipartite-like and power iteration on
it oscillates between two states rather than converging (verified while
building this module; see the module's test suite). A strictly positive
diagonal makes the matrix primitive (irreducible + aperiodic), which is
what actually guarantees power iteration converges to a single fixed
vector. Adding a constant times the identity only shifts every eigenvalue
by that constant; it does not change any eigenvector, so this
regularization does not distort the ranking -- it only repairs the
convergence guarantee.

Per-team row normalization by games played
-------------------------------------------
Before the +EPSILON regularization, each team's raw outgoing credit row
(``raw[index[t], :]``, i.e. how much credit team ``t`` grants to each
opponent it played) is divided by that team's total games-played count.
Without this, a team's total outgoing credit -- and hence its influence on
every other team's recursive rating -- scales with how many games it
played, entirely independent of how well it played them. This is not a
cosmetic normalization: on real 2001 data it is the reason undefeated,
12-0 Miami (FL) was outranked by 11-2 Tennessee, which played 13 games.
Dividing by games played makes each team's total outgoing "vote weight"
comparable regardless of schedule length, which is Keener's own original
design choice (his paper phrases it as normalizing so no team's vote
counts for more than any other's merely by virtue of playing more games),
not a departure from his method. This division happens once per team, on
the raw credit matrix, strictly before the diagonal EPSILON regularizer
below is added -- EPSILON is a fixed convergence-guarantee constant, not a
per-game credit, so it is intentionally left out of this normalization.

No stochastic normalization; power iteration
-----------------------------------------------
Beyond the per-team games-played row normalization above, A here is
deliberately *not* additionally row- or column-normalized to sum to 1 the
way PageRank's transition matrix is. An earlier version of this module did
try full column-normalization (so column j summed to 1, describing how
team j's fixed unit of "importance" is distributed across the teams that
played it), but that construction has a degenerate failure mode: when a
team's column has only a single nonzero entry (e.g. two teams whose only
game in the dataset was against each other), normalizing it to sum to 1
forces that entry to exactly 1 regardless of the actual game's margin or
credit split -- it erases the very performance information the matrix is
supposed to encode. Leaving A's magnitude otherwise unnormalized (beyond
the games-played row division and +EPSILON regularization) preserves that
information at every scale of sub-graph, and the ranking (the *direction*
of the dominant eigenvector) is what matters here, not any particular
normalization of its magnitude. r solves A r = lambda r for the dominant
eigenvalue lambda, computed by power iteration with a per-iteration
renormalization that is purely a numerical-stability device (preventing
under/overflow across iterations), not a modeling choice.
"""

from __future__ import annotations

import numpy as np

from cfb_strength.contracts import Game, TeamRating

MAX_SKEW = 0.35
"""Cap, in either direction from 0.5, on how far a game's raw points-share
can move a team's credit. Bounds the clamped share to
[0.5 - MAX_SKEW, 0.5 + MAX_SKEW] = [0.15, 0.85], so an extreme blowout score
(e.g. 70-0) is treated the same as any other sufficiently lopsided score."""

BASE_WIN = 0.6
"""Fixed credit floor for a win, before the margin nudge. A win's credit is
always in [BASE_WIN, BASE_WIN + MARGIN_NUDGE * MAX_SKEW]."""

BASE_LOSS = 0.05
"""Fixed credit floor for a loss, before the margin nudge. A loss's credit
is always in [BASE_LOSS, BASE_LOSS + MARGIN_NUDGE * MAX_SKEW]. BASE_WIN
must always exceed this range's maximum (BASE_LOSS + MARGIN_NUDGE *
MAX_SKEW) so that win/loss remains the dominant signal regardless of
margin -- see test_win_always_beats_loss_regardless_of_margin."""

MARGIN_NUDGE = 0.3
"""How much of the clamped points-share nudges credit within a team's own
win or loss band. Combined with MAX_SKEW, bounds the nudge's total swing to
MARGIN_NUDGE * MAX_SKEW = 0.105 in either direction."""

assert BASE_WIN > BASE_LOSS + MARGIN_NUDGE * MAX_SKEW, (
    "win/loss dominance invariant violated: a win must always out-credit "
    "any loss regardless of margin"
)

EPSILON_DENOMINATOR = 2.0
"""EPSILON = 1 / (EPSILON_DENOMINATOR * N) for N teams -- small enough that
it is negligible next to real game credit (each game contributes O(1) credit
split between two teams) while still guaranteeing every matrix entry is
strictly positive, which is what makes the matrix irreducible/primitive
regardless of the real win-graph's connectivity."""

MAX_ITERATIONS = 10_000
CONVERGENCE_TOL = 1e-12


def _clamped_share(points_i: int, points_j: int) -> float:
    """Team i's share of total points scored in the game, clamped to
    [0.5 - MAX_SKEW, 0.5 + MAX_SKEW]. Symmetric: clamped_share(i, j) and
    clamped_share(j, i) always sum to 1."""
    total = points_i + points_j
    if total == 0:
        return 0.5
    share = points_i / total
    return min(max(share, 0.5 - MAX_SKEW), 0.5 + MAX_SKEW)


def _single_game_credit(home_points: int, away_points: int) -> tuple[float, float]:
    """Return (home_credit, away_credit), each a fixed win/loss base rate
    nudged by a clamped share of points scored.

    See module docstring: win/loss is the dominant signal (BASE_WIN always
    exceeds the maximum possible loss credit); margin only nudges within
    the winner's or loser's own band, via a clamped points share.
    """
    home_share = _clamped_share(home_points, away_points)
    away_share = 1.0 - home_share  # _clamped_share is symmetric around 0.5

    def credit(points_i: int, points_j: int, share_i: float) -> float:
        if points_i > points_j:
            return BASE_WIN + MARGIN_NUDGE * (share_i - 0.5)
        if points_j > points_i:
            return BASE_LOSS + MARGIN_NUDGE * (share_i - (0.5 - MAX_SKEW))
        return 0.5  # tie, not possible under current NCAA rules but handled

    return (
        credit(home_points, away_points, home_share),
        credit(away_points, home_points, away_share),
    )


class KeenerRating:
    """Keener eigenvector rating method. Satisfies the `RatingMethod` Protocol."""

    def rate(self, games: list[Game]) -> dict[int, TeamRating]:
        if not games:
            return {}

        team_ids = sorted({g.home_team_id for g in games} | {g.away_team_id for g in games})
        n = len(team_ids)
        index = {team_id: i for i, team_id in enumerate(team_ids)}

        raw = np.zeros((n, n), dtype=np.float64)
        wins = {team_id: 0 for team_id in team_ids}
        losses = {team_id: 0 for team_id in team_ids}
        games_played = {team_id: 0 for team_id in team_ids}

        for g in games:
            hi, ai = index[g.home_team_id], index[g.away_team_id]
            home_credit, away_credit = _single_game_credit(g.home_points, g.away_points)
            raw[hi, ai] += home_credit
            raw[ai, hi] += away_credit

            games_played[g.home_team_id] += 1
            games_played[g.away_team_id] += 1

            if g.home_points > g.away_points:
                wins[g.home_team_id] += 1
                losses[g.away_team_id] += 1
            elif g.away_points > g.home_points:
                wins[g.away_team_id] += 1
                losses[g.home_team_id] += 1
            # a tie increments neither; not possible under current NCAA rules

        if n == 1:
            only = team_ids[0]
            return {
                only: TeamRating(
                    team_id=only, rating=1.0, rank=1,
                    wins=wins[only], losses=losses[only],
                )
            }

        # Normalize each team's outgoing credit row by its games-played
        # count, so a team's total influence on the recursive system does
        # not scale with schedule length. See module docstring ("Per-team
        # row normalization by games played"). Every team appearing in the
        # matrix has played at least one game (it only appears because it
        # is on one side of a game in `games`), so this division is always
        # by a positive count.
        for team_id in team_ids:
            ti = index[team_id]
            if games_played[team_id] > 0:
                raw[ti, :] /= games_played[team_id]

        epsilon = 1.0 / (EPSILON_DENOMINATOR * n)
        # EPSILON is added to every entry, including the diagonal: see the
        # module docstring for why a strictly positive diagonal is required
        # for power iteration to converge (not just for connectivity).
        a = raw + epsilon

        r = np.full(n, 1.0 / n, dtype=np.float64)
        for _ in range(MAX_ITERATIONS):
            r_next = a @ r
            r_next /= r_next.sum()
            if np.max(np.abs(r_next - r)) < CONVERGENCE_TOL:
                r = r_next
                break
            r = r_next

        order = sorted(range(n), key=lambda i: (-r[i], team_ids[i]))
        rank_of = {i: rank + 1 for rank, i in enumerate(order)}

        return {
            team_ids[i]: TeamRating(
                team_id=team_ids[i],
                rating=float(r[i]),
                rank=rank_of[i],
                wins=wins[team_ids[i]],
                losses=losses[team_ids[i]],
            )
            for i in range(n)
        }
