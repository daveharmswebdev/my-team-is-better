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
  toward parity. In the reported record it increments `ties`, not `wins`
  or `losses`. That is `TeamRating.ties`' one cross-method definition
  (issue #83), so Keener counts it the same way.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from cfb_strength.contracts import EloGameStep, EloLedger, Game, TeamRating


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

    def __post_init__(self) -> None:
        """Reject a config that would make the update math silently wrong.

        Same philosophy as `_EloConfigRegistry` twenty lines below: the
        failure mode being guarded is not a crash, it is a plausible-looking
        wrong number. Each check corresponds to a concrete division or clamp
        downstream:

        * `scale` is `expected_score`'s unguarded divisor -- a 0.0 scale is a
          `ZeroDivisionError`, a negative one silently inverts every
          prediction (the favorite becomes the underdog).
        * `mov_scale` is both the numerator of the margin-of-victory
          multiplier and the basis of its mandatory denominator floor
          (`_MIN_DENOM_FRACTION * cfg.mov_scale`). At `mov_scale <= 0` the
          floor evaporates -- it can no longer stop the denominator reaching
          zero or going negative -- which is exactly the sign inversion
          `mov_multiplier`'s clamp exists to prevent.
        * `k` scales every shift; a negative `k` rewards losing.
        * `revert` outside `[0, 1]` is not a partial reversion at all: below
          0 it pushes a rating *away* from the mean each offseason, above 1
          it overshoots past it and oscillates. `revert_across_offseasons`'
          closed form `(1 - revert) ** n` only contracts inside this range.

        NaN is rejected explicitly rather than left to the comparisons: every
        `<=` against a NaN is False, so a NaN would pass a bare
        `if value <= 0` check and then poison every rating it touched.
        """
        for name in ("k", "scale", "mov_scale"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"EloConfig.{name} must be finite and positive; got {value!r}")
        if not math.isfinite(self.revert) or not 0.0 <= self.revert <= 1.0:
            raise ValueError(
                f"EloConfig.revert must be a finite fraction in [0, 1]; got {self.revert!r}"
            )


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
            f"no Elo configuration registered for sport {sport!r}; available: {sorted(self)}"
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


def mov_multiplier(point_diff: float, elo_diff: float, result: float, cfg: EloConfig) -> float:
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

    NaN IS NOT CLAMPABLE
    --------------------
    The clamp above is `max(...)`, and `max(nan, 1.1)` returns `nan` in
    Python -- every comparison against a NaN is False, so the floor passes a
    NaN straight through untouched. The result is a NaN multiplier, a NaN
    shift, and `elo[root] += shift` poisoning that team's rating for the
    rest of the replay and, through it, every opponent it plays -- with no
    exception anywhere to notice. A non-finite input is therefore rejected
    outright rather than clamped: unlike a merely extreme `elo_diff`, there
    is no correctly-signed bounded value to saturate to.
    """
    if not math.isfinite(elo_diff) or not math.isfinite(point_diff):
        raise ValueError(
            "mov_multiplier requires finite inputs (a NaN survives the "
            f"denominator clamp and silently poisons every later rating); got "
            f"point_diff={point_diff!r} elo_diff={elo_diff!r}"
        )
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


@dataclass(frozen=True)
class _GameUpdate:
    """Every intermediate of one game's update, from the home side, as
    `_game_update` computed it. `shift` is exactly `rating_shift`'s return
    value; the other fields exist so `_walk` can record the numbers it used
    in an `EloLedger` without recomputing any of them."""

    home_field_adjustment: float
    elo_diff: float
    result: float
    expected: float
    multiplier: float
    shift: float


def _game_update(
    elo_home: float,
    elo_away: float,
    home_points: int,
    away_points: int,
    neutral_site: bool,
    cfg: EloConfig,
) -> _GameUpdate:
    """`rating_shift`'s body, keeping its intermediates. The expressions and
    their evaluation order are `rating_shift`'s own, so `.shift` is
    bit-identical to it (pinned by
    `test_elo.py::test_pinned_single_game_update_cfb`)."""
    home_field_adjustment = 0.0 if neutral_site else cfg.hfa
    elo_diff = elo_home - elo_away + home_field_adjustment
    result = game_result(home_points, away_points)
    multiplier = mov_multiplier(home_points - away_points, elo_diff, result, cfg)
    expected = expected_score(elo_diff, cfg)
    return _GameUpdate(
        home_field_adjustment=home_field_adjustment,
        elo_diff=elo_diff,
        result=result,
        expected=expected,
        multiplier=multiplier,
        shift=cfg.k * multiplier * (result - expected),
    )


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

    Delegates to `_game_update`, which `_walk` calls directly so that the
    ledger records the intermediates this function discards.
    """
    return _game_update(elo_home, elo_away, home_points, away_points, neutral_site, cfg).shift


def revert_between_seasons(elo: float, cfg: EloConfig) -> float:
    """Move a rating `cfg.revert` of the way toward `cfg.mean`.

    Rosters, coaches and recruiting classes all turn over in the offseason,
    so last season's rating is evidence about this season but not a
    prediction of it. A partial reversion keeps the signal while bounding
    how long a single dominant (or disastrous) season echoes. Applied
    exactly once per team per offseason, on that team's first game of the
    new season -- see `_walk` and `revert_across_offseasons`.
    """
    return cfg.mean * cfg.revert + elo * (1.0 - cfg.revert)


def revert_across_offseasons(elo: float, cfg: EloConfig, offseasons: int) -> float:
    """Apply `offseasons` consecutive reversions in one step.

    "Once per team per offseason" means *per elapsed offseason*, not per
    observed season-to-season transition. A team that plays 2001 and then
    reappears in 2005 has sat out four offseasons, so its 2005 rating starts
    four reversions from where 2001 ended -- not one. Counting observed
    transitions instead (the obvious `last_season[root] != season`
    implementation) would let a team carry a four-year-stale rating into a
    league it has not played in since, which is precisely the staleness the
    reversion exists to bound. This is reachable in CFB, where non-FBS teams
    enter and leave the win-graph intermittently, and in the NFL only across
    a season a franchise genuinely missed.

    Closed form, not a loop: `revert_between_seasons` is affine, so n
    applications collapse to

        mean + (elo - mean) * (1 - revert) ** n

    which is O(1) in the gap. A loop would be correct but would scale with a
    gap that is attacker-free but unbounded in principle (a fixture db with
    a 1900 game and a 2024 game).

    `offseasons == 1` deliberately delegates to `revert_between_seasons`
    rather than evaluating the closed form. The two agree to within a bit or
    two, not exactly (`mean*revert + elo*(1-revert)` and
    `mean + (elo-mean)*(1-revert)` round differently), and the one-season gap
    is the overwhelmingly common case -- routing it through the closed form
    would perturb every carried rating in every sport by ~1e-13 for no
    benefit. Pinned by
    `test_elo.py::test_closed_form_matches_repeated_reversion`.
    """
    if offseasons < 0:
        raise ValueError(
            f"offseasons must be non-negative; got {offseasons}. A negative gap "
            "means `games` was not in ascending season order, which violates "
            "`RatingMethod`'s documented chronological total order."
        )
    if offseasons == 0:
        return elo
    if offseasons == 1:
        return revert_between_seasons(elo, cfg)
    return cfg.mean + (elo - cfg.mean) * math.pow(1.0 - cfg.revert, offseasons)


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


def _rank(
    ratings: dict[int, float],
    wins: dict[int, int],
    losses: dict[int, int],
    ties: dict[int, int],
    ledgers: Mapping[int, EloLedger] | None = None,
) -> dict[int, TeamRating]:
    """Rank 1..n by rating descending, team id ascending as the tiebreak.

    `compute_and_store` re-ranks for display anyway (FBS-only, per
    `compute_ratings`' module docstring), so this rank is mostly for direct
    callers and tests -- but it is deterministic, which matters more than
    it being final.

    `ledgers=None` (the career walk) leaves every `elo_ledger` None.
    """
    order = sorted(ratings, key=lambda team_id: (-ratings[team_id], team_id))
    return {
        team_id: TeamRating(
            team_id=team_id,
            rating=ratings[team_id],
            rank=position + 1,
            wins=wins.get(team_id, 0),
            losses=losses.get(team_id, 0),
            ties=ties.get(team_id, 0),
            elo_ledger=None if ledgers is None else ledgers[team_id],
        )
        for position, team_id in enumerate(order)
    }


def _result_letter(team_points: int, opponent_points: int) -> Literal["W", "L", "T"]:
    if team_points > opponent_points:
        return "W"
    if team_points < opponent_points:
        return "L"
    return "T"


def _record_participant(
    participants: dict[int, int],
    root: int,
    actual_id: int,
    record_season: int | None,
) -> None:
    """Claim `root`'s result slot for the team id that actually played.

    `participants` is keyed by lineage root and holds the *actual* team id
    to emit, which is only unambiguous because a lineage's members never
    overlap in a season (`franchise_lineage.py`, pinned by
    `test_franchise_lineage.py::test_nfl_lineage_pairs_are_strictly_non_overlapping`).
    A plain `participants[root] = actual_id` would make that premise
    last-writer-wins: if a predecessor and its successor both played
    `record_season`, the earlier-seen team would silently vanish from the
    result while the survivor inherited the *combined* franchise rating
    alongside only its own win/loss record. That is a corrupted table with
    no error, so it raises instead -- same reasoning as `_resolve_roots`'
    cycle guard.
    """
    existing = participants.get(root)
    if existing is not None and existing != actual_id:
        raise ValueError(
            f"franchise lineage overlap: team ids {existing} and {actual_id} both "
            f"resolve to lineage root {root} and both played season "
            f"{record_season}. A lineage's members must not overlap in a single "
            "season -- see franchise_lineage.py, whose non-overlap premise is what "
            "makes 'the id that played the target season' unique."
        )
    participants[root] = actual_id


def _walk(
    games: list[Game],
    cfg: EloConfig,
    *,
    roots: Mapping[int, int],
    career: bool,
    record_season: int | None,
    record_ledger: bool = False,
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

    `career=True` enables the offseason reversion (one per *elapsed*
    offseason -- see `revert_across_offseasons`) and requires every
    `Game.season` to be populated. `record_season=None` means "count every
    game toward the record and emit every team", which is the
    season-isolated case; when it is set, a game from a *later* season is a
    caller-contract violation and raises, rather than silently making the
    emitted rating the end-of-*last*-season one.

    `record_ledger=True` (season-isolated only) records one `EloGameStep`
    per team per game, keyed by the actual team id, from the values this
    loop computed: `_game_update`'s intermediates, the ratings read just
    before the update, and each rating read just after its own addition.
    It is rejected with `career=True`, whose reversions a ledger of game
    steps alone cannot show (issue #183 leaves career ledgers out of scope).
    """
    if record_ledger and career:
        raise ValueError(
            "an Elo ledger is recorded only for a season-isolated walk; a career "
            "ledger would also need offseason-reversion steps"
        )
    elo: dict[int, float] = {}
    steps: dict[int, list[EloGameStep]] = {}
    last_season: dict[int, int] = {}
    # root -> the actual team id that played in `record_season`.
    participants: dict[int, int] = {}
    wins: dict[int, int] = {}
    losses: dict[int, int] = {}
    ties: dict[int, int] = {}

    for game in games:
        season = game.season
        if career and season is None:
            raise ValueError(
                "EloCareerRating requires every Game.season to be populated; got "
                f"None for home_team_id={game.home_team_id} "
                f"away_team_id={game.away_team_id}. The loader always sets it, so "
                "a None here is a programming error, not a data gap."
            )
        if record_season is not None and season is not None and season > record_season:
            raise ValueError(
                f"a game from season {season} was handed to a career walk targeting "
                f"season {record_season}. `games` must span only seasons <= the "
                "target (see compute_ratings._load_games' `season <= ?` history "
                "branch). Continuing would emit the rating at the end of the LAST "
                "season present rather than the end of the target season -- a wrong "
                "number with no crash, so it is rejected here instead."
            )

        home_id, away_id = game.home_team_id, game.away_team_id
        home_root = roots.get(home_id, home_id)
        away_root = roots.get(away_id, away_id)

        for root in (home_root, away_root):
            if root not in elo:
                elo[root] = cfg.initial
                if season is not None:
                    last_season[root] = season
            elif career and season is not None:
                previous = last_season.get(root)
                if previous is not None and previous != season:
                    # First game of a new season for this franchise. Revert
                    # once per *elapsed* offseason, not once per observed
                    # transition: a team returning after a four-year absence
                    # has sat out four offseasons and must not carry a
                    # four-year-stale rating. See
                    # `revert_across_offseasons`.
                    elo[root] = revert_across_offseasons(elo[root], cfg, season - previous)
                    last_season[root] = season

        home_before = elo[home_root]
        away_before = elo[away_root]
        update = _game_update(
            home_before,
            away_before,
            game.home_points,
            game.away_points,
            game.neutral_site,
            cfg,
        )
        shift = update.shift
        elo[home_root] += shift
        home_after = elo[home_root]
        elo[away_root] -= shift
        away_after = elo[away_root]

        if record_ledger:
            home_steps = steps.setdefault(home_id, [])
            home_steps.append(
                EloGameStep(
                    game_number=len(home_steps) + 1,
                    opponent_team_id=away_id,
                    venue="neutral" if game.neutral_site else "home",
                    team_points=game.home_points,
                    opponent_points=game.away_points,
                    result=_result_letter(game.home_points, game.away_points),
                    rating_before=home_before,
                    opponent_rating_before=away_before,
                    home_field_adjustment=update.home_field_adjustment,
                    rating_gap=update.elo_diff,
                    win_expectancy=update.expected,
                    mov_multiplier=update.multiplier,
                    shift=shift,
                    rating_after=home_after,
                    week=game.week,
                    season_type=game.season_type,
                    start_date=game.start_date,
                )
            )
            away_steps = steps.setdefault(away_id, [])
            away_steps.append(
                EloGameStep(
                    game_number=len(away_steps) + 1,
                    opponent_team_id=home_id,
                    venue="neutral" if game.neutral_site else "away",
                    team_points=game.away_points,
                    opponent_points=game.home_points,
                    result=_result_letter(game.away_points, game.home_points),
                    rating_before=away_before,
                    opponent_rating_before=home_before,
                    # `0.0 - x` rather than `-x`: on a neutral field the
                    # walk used +0.0, and the away side's is +0.0 too, not
                    # a signed zero.
                    home_field_adjustment=0.0 - update.home_field_adjustment,
                    rating_gap=-update.elo_diff,
                    # The walk evaluates only the home side's expectancy.
                    win_expectancy=1.0 - update.expected,
                    mov_multiplier=update.multiplier,
                    shift=-shift,
                    rating_after=away_after,
                    week=game.week,
                    season_type=game.season_type,
                    start_date=game.start_date,
                )
            )

        if record_season is not None and season != record_season:
            continue

        _record_participant(participants, home_root, home_id, record_season)
        _record_participant(participants, away_root, away_id, record_season)
        for team_id in (home_id, away_id):
            wins.setdefault(team_id, 0)
            losses.setdefault(team_id, 0)
            ties.setdefault(team_id, 0)
        if game.home_points > game.away_points:
            wins[home_id] += 1
            losses[away_id] += 1
        elif game.away_points > game.home_points:
            wins[away_id] += 1
            losses[home_id] += 1
        else:
            # A tie, counted after the `record_season` filter above, so a
            # career walk reports only target-season ties (issue #83).
            ties[home_id] += 1
            ties[away_id] += 1

    ratings = {actual_id: elo[root] for root, actual_id in participants.items()}
    if not record_ledger:
        return _rank(ratings, wins, losses, ties)
    ledgers = {
        team_id: EloLedger(
            starting_rating=cfg.initial,
            k=cfg.k,
            hfa=cfg.hfa,
            scale=cfg.scale,
            mov_scale=cfg.mov_scale,
            mov_autocorr=cfg.mov_autocorr,
            steps=team_steps,
        )
        for team_id, team_steps in steps.items()
    }
    return _rank(ratings, wins, losses, ties, ledgers)


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
        """Every returned `TeamRating` carries an `EloLedger` (issue #183)."""
        return _walk(
            games,
            self.cfg,
            roots={},
            career=False,
            record_season=None,
            record_ledger=True,
        )


class EloCareerRating:
    """Cross-season Elo. Satisfies the `CareerRatingMethod` Protocol.

    Replays every season in `games` (which the caller guarantees spans only
    seasons <= `target_season`, in chronological total order), reverting
    each team's rating toward `cfg.mean` once per offseason, and returns
    only the teams that played in `target_season` -- with
    `target_season`-only win/loss/tie records. A team carried through the replay
    but absent from the target season influences its opponents' ratings and
    is then simply not emitted.

    `successors` is a resolved `{predecessor_team_id: successor_team_id}`
    map, passed in rather than looked up, so this module stays a pure
    function of its inputs with no db dependency (see
    `compute_ratings._franchise_successors`, which resolves
    `franchise_lineage.FRANCHISE_LINEAGE`'s abbreviations against `teams`).
    Chains are collapsed and cycles rejected at construction time.
    """

    def __init__(self, cfg: EloConfig, successors: Mapping[int, int] | None = None) -> None:
        self.cfg = cfg
        self.roots = _resolve_roots(successors or {})

    def rate_through(self, games: list[Game], target_season: int) -> dict[int, TeamRating]:
        return _walk(
            games,
            self.cfg,
            roots=self.roots,
            career=True,
            record_season=target_season,
        )
