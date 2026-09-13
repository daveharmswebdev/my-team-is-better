"""Single-game Keener credit math, shared between `ratings` and `evidence`.

Coordinator-owned, like `contracts.py` -- lives at the same bottom layer (see
`.importlinter`) so both `ratings/keener.py` (which uses it to compute the
actual credit matrix) and `evidence/` (which uses it, against the same raw
game scores, to explain a credit value in plain-English-plus-numbers copy for
issue #37) call the exact same function. That is the point: the explanation
shown to a user can never drift from the number the rating is actually built
from, because both are the same function call.

This module intentionally does NOT know about the row-normalization (divide
by a team's season games-played) or epsilon-regularization steps that turn
these per-game numbers into the final `credit`/`contribution` columns
displayed elsewhere -- see `ratings/keener.py`'s module docstring for those.
A `CreditComponents.total` here is a single game's raw credit only.
"""

from __future__ import annotations

from dataclasses import dataclass

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
margin -- see ratings/test_keener.py's
test_win_always_beats_loss_regardless_of_margin."""

MARGIN_NUDGE = 0.3
"""How much of the clamped points-share nudges credit within a team's own
win or loss band. Combined with MAX_SKEW, bounds the nudge's total swing to
MARGIN_NUDGE * MAX_SKEW = 0.105 in either direction."""

assert BASE_WIN > BASE_LOSS + MARGIN_NUDGE * MAX_SKEW, (
    "win/loss dominance invariant violated: a win must always out-credit "
    "any loss regardless of margin"
)


def clamped_share(points_i: int, points_j: int) -> float:
    """Team i's share of total points scored in the game, clamped to
    [0.5 - MAX_SKEW, 0.5 + MAX_SKEW]. Symmetric: clamped_share(i, j) and
    clamped_share(j, i) always sum to 1."""
    total = points_i + points_j
    if total == 0:
        return 0.5
    share = points_i / total
    return min(max(share, 0.5 - MAX_SKEW), 0.5 + MAX_SKEW)


@dataclass(frozen=True)
class CreditComponents:
    """One team's single-game credit, decomposed into its base rate and
    margin bonus -- `base + bonus == total`, always, by construction.

    `raw_share`/`clamped_share` are this team's share of the game's total
    points, before/after the [0.15, 0.85] clamp. `capped` is True when the
    clamp actually changed the value (i.e. the raw share fell outside that
    band) -- callers use this to decide whether "capped at 85%"-style
    language applies to this particular game, since most games don't hit it.
    """

    base: float
    bonus: float
    total: float
    raw_share: float
    clamped_share: float
    capped: bool


def single_game_credit(points_for: int, points_against: int) -> CreditComponents:
    """One team's credit for a single game, from its own points scored
    (`points_for`) and its opponent's (`points_against`).

    See `ratings/keener.py`'s module docstring for the full derivation and
    why this shape (fixed win/loss base, clamped-share margin nudge) passes
    the golden historical-championship dataset. A tie (a completed game with
    equal scores -- real in the NFL, see issue #83) splits credit 0.5/0.0 (base/bonus).
    """
    share = clamped_share(points_for, points_against)
    total_points = points_for + points_against
    raw_share = points_for / total_points if total_points else 0.5
    capped = raw_share != share

    if points_for > points_against:
        base = BASE_WIN
        bonus = MARGIN_NUDGE * (share - 0.5)
    elif points_against > points_for:
        base = BASE_LOSS
        bonus = MARGIN_NUDGE * (share - (0.5 - MAX_SKEW))
    else:
        base = 0.5
        bonus = 0.0

    return CreditComponents(
        base=base,
        bonus=bonus,
        total=base + bonus,
        raw_share=raw_share,
        clamped_share=share,
        capped=capped,
    )
