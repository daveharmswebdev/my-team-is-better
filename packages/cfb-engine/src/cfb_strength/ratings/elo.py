"""Elo ratings: a sequential, game-by-game rating engine.

Two registered methods live here, sharing one update rule:

* `EloRating` -- `RatingMethod`. Rates a single season in isolation: every
  team starts at `EloConfig.initial`, one chronological pass, no carryover.
* `EloCareerRating` -- `CareerRatingMethod`. Replays every season up to and
  including the target one, carrying ratings across the offseason with a
  partial reversion toward the league mean, and emits only the teams that
  played in the target season.

Both delegate to the same private `_walk`, so the season-isolated and
career variants cannot drift apart on the update math.

Provenance
----------
Clean-room reimplementation from the *published description* of
FiveThirtyEight's NFL Elo model (Nate Silver / Jay Boice, "How Our NFL
Predictions Work"), itself a descendant of Arpad Elo's chess rating system.
No code and no data were taken from any 538 repository. Everything below is
implemented from the formula as described:

    expected_score = 1 / (10 ** (-elo_diff / 400) + 1)
    mov_multiplier = ln(margin + 1) * (2.2 / (winner_elo_diff * 0.001 + 2.2))
    shift          = K * mov_multiplier * (result - expected_score)

with a home-field bonus added to `elo_diff` and a one-third reversion to the
mean between seasons.

Calibration is per-sport data, never per-sport subclasses
---------------------------------------------------------
Every tunable is a field on the frozen `EloConfig` dataclass and every
function here takes one as an argument. There is deliberately no
`NflEloRating(EloRating)`: a subclass hierarchy would let a behavioral
difference hide in an override, where a config field's difference is
visible in one table and pinned by one test
(`test_elo.py::test_shipped_configs_match_published_constants`).

Deliberate non-features
-----------------------
* **No playoff K boost.** 538's model applies the same K to postseason
  games; matching that keeps the citation honest. Do not "fix" this by
  scaling K for `season_type == 'postseason'` without re-deriving and
  re-pinning the whole model.
* **No per-team QB / travel / rest adjustments.** Those are later 538
  refinements (Elo+/QB-adjusted Elo) and are out of scope here.
* **Ties move ratings.** A tie is `result == 0.5` and pulls both teams
  toward parity. It increments neither `wins` nor `losses`, matching
  Keener's convention (see `keener.py`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from cfb_strength.contracts import Game, TeamRating


@dataclass(frozen=True)
class EloConfig:
    """Every tunable of the Elo update, for one sport.

    Frozen so a config can be shared freely and can be compared by value in
    tests. See `ELO_CONFIGS` for the shipped presets.

    k
        Maximum rating movement scale for one game, before the
        margin-of-victory multiplier.
    hfa
        Home-field advantage, in Elo points, added to the home team's
        effective rating. Dropped entirely on a neutral field.
    mean
        The between-season reversion target.
    initial
        The rating assigned on a team's first-ever appearance.
    revert
        Fraction of the way to `mean` a rating moves each offseason.
    scale
        Logistic denominator: a `scale`-point edge is a 10:1 expected
        score ratio.
    mov_scale
        Numerator of the margin-of-victory multiplier, and also the
        undamped denominator.
    mov_autocorr
        Autocorrelation correction. Damps the credit a *favorite* gets for
        a blowout, which is what stops a dominant team from running away
        with the rating scale.
    """

    k: float
    hfa: float
    mean: float
    initial: float
    revert: float = 1 / 3
    scale: float = 400.0
    mov_scale: float = 2.2
    mov_autocorr: float = 0.001


class _EloConfigRegistry(dict[str, EloConfig]):
    """A `dict[str, EloConfig]` that refuses to be silently wrong.

    A plain dict's `KeyError` is fine for a typo, but the failure mode this
    guards is worse than a typo: falling back to a default config would
    rate NFL games at CFB's `k=40 / hfa=100` and produce a plausible-looking
    but wrong table that nothing downstream could detect. So the lookup
    raises a `ValueError` naming the registered sports instead, and there is
    no `.get()`-with-default path anywhere in this module.
    """

    def __missing__(self, sport: str) -> EloConfig:
        raise ValueError(
            f"no Elo configuration registered for sport {sport!r}; "
            f"available: {sorted(self)}"
        )


ELO_CONFIGS: dict[str, EloConfig] = _EloConfigRegistry(
    {
        # 538's published NFL tuning, verbatim. Note `mean=1505.0`, not
        # 1500.0: the reversion target deliberately sits slightly above the
        # initial rating. That asymmetry is 538's, reproduced here because
        # we are implementing their published formulation -- we have not
        # independently derived why they chose it, so do not "tidy" it to
        # 1500 on the assumption it is a typo. It is not.
        "nfl": EloConfig(k=20.0, hfa=65.0, mean=1505.0, initial=1500.0),
        # UNCALIBRATED -- our own reasoned first pass, not a published
        # tuning, and explicitly not validated against the CFB golden
        # dataset. Tracked for calibration by issue #87.
        #
        # The reasoning behind the two changed fields: a college season is
        # ~12-13 games against the NFL's 17+, so each game has to move a
        # rating further for a season's worth of information to be absorbed
        # (k doubled); and college home-field advantage is conventionally
        # estimated well above the NFL's, on much wider talent gaps and much
        # louder stadiums (hfa 100 vs 65). `mean` and `initial` both sit at
        # 1500 because CFB has no NFL-style expansion-team entry rate to
        # offset. Treat every number here as a starting point for #87, not
        # as a result.
        "cfb": EloConfig(k=40.0, hfa=100.0, mean=1500.0, initial=1500.0),
    }
)

_MIN_DENOM_FRACTION = 0.5
"""Floor for the margin-of-victory denominator, as a fraction of
`cfg.mov_scale` -- so the multiplier saturates at exactly 2x its undamped
value. See `mov_multiplier` for why this clamp is mandatory."""


# ---------------------------------------------------------------------------
# Pure update math. Floats/ints and an EloConfig in, floats out -- never a
# `Game`, never a `TeamRating`, never a db handle. That is what makes the
# pinned tests in test_elo.py able to assert exact values.
# ---------------------------------------------------------------------------


def game_result(home_points: int, away_points: int) -> float:
    """1.0 home win, 0.5 tie, 0.0 home loss."""
    if home_points > away_points:
        return 1.0
    if home_points < away_points:
        return 0.0
    return 0.5


def expected_score(elo_diff: float, cfg: EloConfig) -> float:
    """The home team's expected score given the home-perspective rating gap.

    `elo_diff` already includes home-field advantage where applicable (see
    `rating_shift`). Exactly 0.5 at `elo_diff == 0`.
    """
    # `math.pow` rather than the `**` operator purely for typing: mypy
    # infers `float ** float` as `Any` (the operator can return complex
    # for a negative base), and this function's return type is load-
    # bearing. Both route to the same libm `pow`, so the value is
    # bit-identical -- pinned by
    # `test_elo.py::test_pinned_single_game_update_cfb`.
    return 1.0 / (math.pow(10.0, -elo_diff / cfg.scale) + 1.0)


def mov_multiplier(
    point_diff: float, elo_diff: float, result: float, cfg: EloConfig
) -> float:
    """Margin-of-victory multiplier with 538's autocorrelation correction.

    Two shaping decisions, both from the published model:

    * **Logarithmic in margin.** `ln(max(|pd|, 1) + 1)` -- a 7-point win is
      worth meaningfully more than a 3-point win, a 56-point win barely more
      than a 42-point one. The `max(..., 1)` floor keeps a zero margin (a
      tie) from collapsing the multiplier to `ln(1) == 0`, which would make
      ties inert.
    * **Autocorrelation correction.** Good teams blow out bad teams; without
      a correction, margin and rating reinforce each other and the scale
      runs away. Dividing by `winner_diff * mov_autocorr + mov_scale` shrinks
      the multiplier when the *winner* was already favored and inflates it
      when the winner was the underdog. `winner_diff` is the rating gap from
      the winner's perspective, hence the flip below.

    Ties (`result == 0.5`) bypass the correction entirely: with no winner,
    "the winner's rating edge" is undefined, and 538 does not define one.
    `denom = 1.0` exactly, so a tie's multiplier is `ln(2) * mov_scale`
    regardless of who was favored.

    MANDATORY DENOMINATOR GUARD
    ---------------------------
    With the shipped constants, `winner_diff * 0.001 + 2.2` reaches exactly
    `0.0` at `winner_diff == -2200` and goes *negative* beyond it. Unclamped
    that is a `ZeroDivisionError` at the boundary and, past it, a negative
    multiplier -- which flips the sign of the entire shift and *rewards the
    loser*, silently, with no exception to notice. A -2200 winner-perspective
    gap is not reachable in a healthy season, but it is absolutely reachable
    in a 28-season replay with a pathological or mis-ingested game, and the
    corrupted rating would then propagate through every subsequent season.

    So the denominator is clamped at `_MIN_DENOM_FRACTION * cfg.mov_scale`,
    applied *after* the winner-perspective flip and *before* the division.
    A clamp and not an `assert`: an assert would abort a full backfill over
    one bad game, whereas the clamp saturates the multiplier at exactly 2x
    its undamped value -- a large but bounded, correctly-signed update.
    """
    if result == 0.5:
        # No winner: the autocorrelation term is undefined, not zero.
        denom = 1.0
    else:
        winner_diff = elo_diff if result == 1.0 else -elo_diff
        denom = max(
            winner_diff * cfg.mov_autocorr + cfg.mov_scale,
            _MIN_DENOM_FRACTION * cfg.mov_scale,
        )
    return math.log(max(abs(point_diff), 1.0) + 1.0) * (cfg.mov_scale / denom)


def rating_shift(
    elo_home: float,
    elo_away: float,
    home_points: int,
    away_points: int,
    neutral_site: bool,
    cfg: EloConfig,
) -> float:
    """Rating points the home team gains (negative: loses) from one game.

    Zero-sum by construction, and applied that way by the caller:
    `home += shift; away -= shift`. Home-field advantage is added to the
    home team's *effective* rating for the prediction only -- it never
    enters either team's stored rating -- and is dropped entirely on a
    neutral field.
    """
    elo_diff = elo_home - elo_away + (0.0 if neutral_site else cfg.hfa)
    result = game_result(home_points, away_points)
    multiplier = mov_multiplier(home_points - away_points, elo_diff, result, cfg)
    return cfg.k * multiplier * (result - expected_score(elo_diff, cfg))


def revert_between_seasons(elo: float, cfg: EloConfig) -> float:
    """Move a rating `cfg.revert` of the way toward `cfg.mean`.

    Rosters, coaches and recruiting classes all turn over in the offseason,
    so last season's rating is evidence about this season but not a
    prediction of it. A partial reversion keeps the signal while bounding
    how long a single dominant (or disastrous) season echoes. Applied
    exactly once per team per offseason, on that team's first game of the
    new season -- see `_walk`.
    """
    return cfg.mean * cfg.revert + elo * (1.0 - cfg.revert)


# ---------------------------------------------------------------------------
# Franchise lineage canonicalization
# ---------------------------------------------------------------------------


def _resolve_roots(successors: Mapping[int, int]) -> dict[int, int]:
    """Collapse a `{predecessor: successor}` map into `{id: terminal id}`.

    Follows each chain to its end so a franchise that moved twice folds all
    the way down in one lookup rather than one hop per season.

    A cycle (`{a: b, b: a}`, or any longer loop) is a bad lineage table and
    raises immediately, at construction time -- an unguarded chain walk
    would spin forever and hang a 28-season backfill with no output and no
    error.
    """
    roots: dict[int, int] = {}
    for start in successors:
        seen = {start}
        node = start
        while node in successors:
            node = successors[node]
            if node in seen:
                raise ValueError(
                    f"franchise lineage contains a cycle reachable from team {start}: "
                    f"{sorted(seen)}"
                )
            seen.add(node)
        roots[start] = node
    return roots


# ---------------------------------------------------------------------------
# The shared walk
# ---------------------------------------------------------------------------


def _rank(ratings: dict[int, float], wins: dict[int, int], losses: dict[int, int]) -> dict[int, TeamRating]:
    """Rank 1..n by rating descending, team id ascending as the tiebreak.

    `compute_and_store` re-ranks for display anyway (FBS-only, per
    `compute_ratings`' module docstring), so this rank is mostly for direct
    callers and tests -- but it is deterministic, which matters more than
    it being final.
    """
    order = sorted(ratings, key=lambda team_id: (-ratings[team_id], team_id))
    return {
        team_id: TeamRating(
            team_id=team_id,
            rating=ratings[team_id],
            rank=position + 1,
            wins=wins.get(team_id, 0),
            losses=losses.get(team_id, 0),
        )
        for position, team_id in enumerate(order)
    }


def _walk(
    games: list[Game],
    cfg: EloConfig,
    *,
    roots: Mapping[int, int],
    career: bool,
    record_season: int | None,
) -> dict[int, TeamRating]:
    """One chronological pass over `games`; the single update loop both
    public classes use.

    `games` is consumed in the order given and is never re-sorted: the
    loader's SQL `ORDER BY` (see `compute_ratings._load_games`) is the
    single source of truth for chronology, and a second sort here could
    only disagree with it.

    `roots` maps a relocated franchise's team id to its terminal identity.
    Elo state is keyed by **root**, so a franchise's rating is continuous
    across a relocation; results are keyed by the **actual team id that
    played `record_season`**, which is unambiguous because lineage members
    never overlap in a season (see `franchise_lineage.py`). Rewriting
    pre-target ids to the successor instead would emit, say, the Los
    Angeles Rams' team id for 2005 -- a season in which that identity did
    not exist -- orphaning the row against `team_season` and breaking
    evidence's name resolution.

    `career=True` enables the offseason reversion and requires every
    `Game.season` to be populated. `record_season=None` means "count every
    game toward the record and emit every team", which is the
    season-isolated case.
    """
    elo: dict[int, float] = {}
    last_season: dict[int, int] = {}
    # root -> the actual team id that played in `record_season`.
    participants: dict[int, int] = {}
    wins: dict[int, int] = {}
    losses: dict[int, int] = {}

    for game in games:
        season = game.season
        if career and season is None:
            raise ValueError(
                "EloCareerRating requires every Game.season to be populated; got "
                f"None for home_team_id={game.home_team_id} "
                f"away_team_id={game.away_team_id}. The loader always sets it, so "
                "a None here is a programming error, not a data gap."
            )

        home_id, away_id = game.home_team_id, game.away_team_id
        home_root = roots.get(home_id, home_id)
        away_root = roots.get(away_id, away_id)

        for root in (home_root, away_root):
            if root not in elo:
                elo[root] = cfg.initial
                if season is not None:
                    last_season[root] = season
            elif career and season is not None and last_season.get(root) != season:
                # First game of a new season for this franchise: revert once.
                elo[root] = revert_between_seasons(elo[root], cfg)
                last_season[root] = season

        shift = rating_shift(
            elo[home_root],
            elo[away_root],
            game.home_points,
            game.away_points,
            game.neutral_site,
            cfg,
        )
        elo[home_root] += shift
        elo[away_root] -= shift

        if record_season is not None and season != record_season:
            continue

        participants[home_root] = home_id
        participants[away_root] = away_id
        for team_id in (home_id, away_id):
            wins.setdefault(team_id, 0)
            losses.setdefault(team_id, 0)
        if game.home_points > game.away_points:
            wins[home_id] += 1
            losses[away_id] += 1
        elif game.away_points > game.home_points:
            wins[away_id] += 1
            losses[home_id] += 1
        # A tie increments neither, matching Keener's convention.

    ratings = {actual_id: elo[root] for root, actual_id in participants.items()}
    return _rank(ratings, wins, losses)


# ---------------------------------------------------------------------------
# The two registered methods
# ---------------------------------------------------------------------------


class EloRating:
    """Season-isolated Elo. Satisfies the `RatingMethod` Protocol.

    Every team starts at `cfg.initial` and the season is replayed once, in
    the order `games` arrives in. No cross-season carryover and no
    reversion -- for that, use `EloCareerRating`.

    Deliberately does NOT define `rate_through`: `compute_and_store`
    dispatches on `isinstance(impl, CareerRatingMethod)`, which is a check
    for that method's *name*, so defining it here would silently turn this
    class into a career method.
    """

    def __init__(self, cfg: EloConfig) -> None:
        self.cfg = cfg

    def rate(self, games: list[Game]) -> dict[int, TeamRating]:
        return _walk(games, self.cfg, roots={}, career=False, record_season=None)


class EloCareerRating:
    """Cross-season Elo. Satisfies the `CareerRatingMethod` Protocol.

    Replays every season in `games` (which the caller guarantees spans only
    seasons <= `target_season`, in chronological total order), reverting
    each team's rating toward `cfg.mean` once per offseason, and returns
    only the teams that played in `target_season` -- with
    `target_season`-only win/loss records. A team carried through the replay
    but absent from the target season influences its opponents' ratings and
    is then simply not emitted.

    `successors` is a resolved `{predecessor_team_id: successor_team_id}`
    map, passed in rather than looked up, so this module stays a pure
    function of its inputs with no db dependency (see
    `compute_ratings._franchise_successors`, which resolves
    `franchise_lineage.FRANCHISE_LINEAGE`'s abbreviations against `teams`).
    Chains are collapsed and cycles rejected at construction time.
    """

    def __init__(
        self, cfg: EloConfig, successors: Mapping[int, int] | None = None
    ) -> None:
        self.cfg = cfg
        self.roots = _resolve_roots(successors or {})

    def rate_through(
        self, games: list[Game], target_season: int
    ) -> dict[int, TeamRating]:
        return _walk(
            games,
            self.cfg,
            roots=self.roots,
            career=True,
            record_season=target_season,
        )
