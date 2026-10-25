"""The era-adjusted QB score (#440, epic #439 step 1), implemented to the
definition in `contracts.py` ("QB score"). The math decides; every season
carries its raw metrics, the season's mean and population sd and the z's, so
a panel can show how each number was reached (#183).

A season is one regular-season `player_season_stats` row: its primary key is
(player_id, season, season_type), so a QB traded mid-season has one
whole-season row (team_id NULL) and there is nothing to sum.

`get_qb_score*` score with the frozen `QB_SCORE_WEIGHTS`; `fit_qb_score_weights`
is the offline refit behind them and is never called per request.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from cfb_strength.contracts import (
    POSITION_GROUP_BY_LABEL,
    QB_SCORE_MIN_DROPBACKS,
    QB_SCORE_PEAK_SEASONS,
    QB_SCORE_VERSION,
    QB_SCORE_WEIGHTS,
    NotAQuarterbackError,
    QbMetricValue,
    QbScore,
    QbScoreComparison,
    QbScoreInconclusiveReason,
    QbScoreMetric,
    QbScoreSeason,
    QbScoreSide,
    QbScoreWeightFit,
    Sport,
    UnknownPlayerError,
    position_group,
)

# The `players.position` labels in the "QB" group, as bound parameters.
_QB_LABELS: tuple[str, ...] = tuple(
    label for label, group in POSITION_GROUP_BY_LABEL.items() if group == "QB"
)
_QB_LABEL_PARAMS = ", ".join(f":qb{i}" for i in range(len(_QB_LABELS)))

# Every regular-season row of a QB-group player in `:sport`. Dropbacks treat a
# NULL attempts/sacks_suffered as 0, by the contract's definition; every
# other column comes through as stored, NULL included.
_ROWS_SQL = f"""
SELECT s.player_id, s.season,
       COALESCE(s.attempts, 0) + COALESCE(s.sacks_suffered, 0) AS dropbacks,
       COALESCE(s.carries, 0) AS carries,
       s.passing_epa, s.rushing_epa,
       s.passing_yards, s.passing_tds, s.passing_interceptions, s.sack_yards_lost
FROM player_season_stats s
JOIN players p ON p.id = s.player_id AND p.sport = :sport
WHERE s.sport = :sport AND s.season_type = 'regular'
  AND p.position IN ({_QB_LABEL_PARAMS})
"""

# The player's own rows, and the qualifying rows of every QB in the seasons
# he has a row in (his baselines).
_PLAYER_ROWS_SQL = f"{_ROWS_SQL} AND s.player_id = :player_id ORDER BY s.season"
_BASELINE_ROWS_SQL = f"""{_ROWS_SQL}
  AND COALESCE(s.attempts, 0) + COALESCE(s.sacks_suffered, 0) >= :min_dropbacks
  AND s.season IN (
      SELECT season FROM player_season_stats
      WHERE player_id = :player_id AND sport = :sport AND season_type = 'regular'
  )
"""
_ALL_QUALIFYING_ROWS_SQL = f"""{_ROWS_SQL}
  AND COALESCE(s.attempts, 0) + COALESCE(s.sacks_suffered, 0) >= :min_dropbacks
"""

# First regular season with a season row or a QB start, any year.
_FIRST_SEASON_SQL = """
SELECT MIN(season) FROM (
    SELECT season FROM player_season_stats
    WHERE player_id = :player_id AND sport = :sport AND season_type = 'regular'
    UNION ALL
    SELECT g.season FROM game_starters s
    JOIN games g ON g.id = s.game_id AND g.sport = :sport
    WHERE s.player_id = :player_id AND s.sport = :sport AND s.position = 'QB'
      AND g.season_type = 'regular'
)
"""

_ALL_METRICS = ("epa_per_dropback", "rush_epa_per_play", "any_a")


@dataclass(frozen=True)
class _Row:
    """One QB season row with its rates (None when a denominator is 0 or an
    input is NULL)."""

    player_id: int
    season: int
    dropbacks: int
    qualifies: bool
    rates: Mapping[str, float | None]
    # (passing_epa + rushing_epa) / (dropbacks + carries): the fit's target.
    total_epa_per_play: float | None


def _ratio(numerator: float | None, denominator: int) -> float | None:
    if numerator is None or denominator == 0:
        return None
    return numerator / denominator


def _row(r: sqlite3.Row) -> _Row:
    dropbacks = int(r["dropbacks"])
    plays = dropbacks + int(r["carries"])
    qualifies = dropbacks >= QB_SCORE_MIN_DROPBACKS
    if qualifies:
        for column in ("passing_epa", "rushing_epa"):
            if r[column] is None:
                raise ValueError(
                    f"player {r['player_id']} season {r['season']} qualifies "
                    f"({dropbacks} dropbacks) but {column} is NULL: EPA coverage "
                    "is complete from 1999 on (#354), so this is a data bug"
                )
    any_a_inputs = [
        r["passing_yards"],
        r["passing_tds"],
        r["passing_interceptions"],
        r["sack_yards_lost"],
    ]
    any_a_numerator = (
        None
        if any(v is None for v in any_a_inputs)
        else (
            r["passing_yards"]
            + 20 * r["passing_tds"]
            - 45 * r["passing_interceptions"]
            - r["sack_yards_lost"]
        )
    )
    total = (
        None
        if r["passing_epa"] is None or r["rushing_epa"] is None
        else r["passing_epa"] + r["rushing_epa"]
    )
    return _Row(
        player_id=int(r["player_id"]),
        season=int(r["season"]),
        dropbacks=dropbacks,
        qualifies=qualifies,
        rates={
            "epa_per_dropback": _ratio(r["passing_epa"], dropbacks),
            "rush_epa_per_play": _ratio(r["rushing_epa"], plays),
            "any_a": _ratio(any_a_numerator, dropbacks),
        },
        total_epa_per_play=_ratio(total, plays),
    )


def _params(sport: Sport, **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {f"qb{i}": label for i, label in enumerate(_QB_LABELS)}
    params.update(sport=sport, min_dropbacks=QB_SCORE_MIN_DROPBACKS, **extra)
    return params


@dataclass(frozen=True)
class _Baseline:
    mean: float
    sd: float

    def z(self, value: float) -> float:
        # A season whose qualifying QBs all share one value (or there is only
        # one of them) has no spread to judge against: everyone is average.
        if self.sd == 0:
            return 0.0
        return (value - self.mean) / self.sd


def _baselines(
    rows: Iterable[_Row], value_of: Callable[[_Row], float | None]
) -> dict[int, _Baseline]:
    """Per season, the mean and population sd of `value_of` over that
    season's qualifying rows (a None value is left out)."""
    by_season: dict[int, list[float]] = {}
    for row in rows:
        if not row.qualifies:
            continue
        value = value_of(row)
        if value is not None:
            by_season.setdefault(row.season, []).append(value)
    return {
        season: _Baseline(mean=statistics.fmean(values), sd=statistics.pstdev(values))
        for season, values in by_season.items()
    }


def _rate(metric: str) -> Callable[[_Row], float | None]:
    return lambda row: row.rates[metric]


def _player(conn: sqlite3.Connection, sport: Sport, player_id: int) -> sqlite3.Row:
    player: sqlite3.Row | None = conn.execute(
        "SELECT display_name, position FROM players WHERE id = ? AND sport = ?",
        (player_id, sport),
    ).fetchone()
    if player is None:
        raise UnknownPlayerError(player_id, sport)
    if position_group(player["position"]) != "QB":
        raise NotAQuarterbackError(player_id, player["position"])
    return player


def get_qb_score(conn: sqlite3.Connection, *, sport: Sport, player_id: int) -> QbScore:
    """One QB's era-adjusted score: every regular season with a row, the
    qualifying ones z-scored against that season's qualifying QBs, and the
    career (signed sum) and peak (best five, filled with 0.0).

    Raises UnknownPlayerError when no `players` row has that id and sport,
    NotAQuarterbackError when the player's group isn't "QB", and ValueError
    when a qualifying season in a baseline has NULL passing or rushing EPA."""
    player = _player(conn, sport, player_id)
    params = _params(sport, player_id=player_id)
    own = [_row(r) for r in conn.execute(_PLAYER_ROWS_SQL, params).fetchall()]
    baseline_rows = [_row(r) for r in conn.execute(_BASELINE_ROWS_SQL, params).fetchall()]
    baselines = {m: _baselines(baseline_rows, _rate(m)) for m in _ALL_METRICS}

    composites: dict[int, float] = {}
    metric_values: list[dict[str, QbMetricValue | None]] = []
    for row in own:
        values: dict[str, QbMetricValue | None] = {}
        for metric in _ALL_METRICS:
            value = row.rates[metric]
            base = baselines[metric].get(row.season) if row.qualifies else None
            if value is None:
                values[metric] = None
            elif base is None:
                values[metric] = QbMetricValue(
                    value=value, season_mean=None, season_sd=None, z=None
                )
            else:
                values[metric] = QbMetricValue(
                    value=value, season_mean=base.mean, season_sd=base.sd, z=base.z(value)
                )
        metric_values.append(values)
        if row.qualifies:
            composite = 0.0
            for metric, weight in QB_SCORE_WEIGHTS.items():
                scored = values[metric]
                # A qualifying row has both EPA rates (`_row` raises
                # otherwise) and is in its own season's baseline.
                assert scored is not None and scored.z is not None
                composite += weight * scored.z
            composites[row.season] = composite

    peak_seasons = sorted(composites, key=lambda season: (-composites[season], season))[
        :QB_SCORE_PEAK_SEASONS
    ]
    seasons = [
        QbScoreSeason(
            season=row.season,
            dropbacks=row.dropbacks,
            qualifies=row.qualifies,
            epa_per_dropback=values["epa_per_dropback"],
            rush_epa_per_play=values["rush_epa_per_play"],
            any_a=values["any_a"],
            composite=composites.get(row.season),
            in_peak=row.season in peak_seasons,
        )
        for row, values in zip(own, metric_values, strict=True)
    ]

    career: float | None = None
    peak: float | None = None
    filled = 0
    if composites:
        career = sum(composites[season] for season in sorted(composites))
        filled = QB_SCORE_PEAK_SEASONS - len(peak_seasons)
        best = [composites[season] for season in peak_seasons] + [0.0] * filled
        peak = sum(best) / QB_SCORE_PEAK_SEASONS

    first_season = conn.execute(_FIRST_SEASON_SQL, params).fetchone()[0]
    return QbScore(
        sport=sport,
        player_id=player_id,
        display_name=player["display_name"],
        version=QB_SCORE_VERSION,
        seasons=seasons,
        qualifying_seasons=len(composites),
        career=career,
        peak=peak,
        peak_filled_with_average=filled,
        first_season=first_season,
        first_scored_season=min(composites) if composites else None,
    )


def _winner(margin: float) -> QbScoreSide | None:
    if margin > 0:
        return "a"
    if margin < 0:
        return "b"
    return None


def get_qb_score_comparison(
    conn: sqlite3.Connection, *, sport: Sport, a: int, b: int
) -> QbScoreComparison:
    """Two QBs' scores and the verdict on each measure: the higher score
    wins by any margin, an exact tie has no winner, and a QB with no
    qualifying season makes both measures inconclusive.

    Raises ValueError when a == b, then UnknownPlayerError and
    NotAQuarterbackError for the first of `a`, `b`."""
    if a == b:
        raise ValueError(f"cannot compare player {a} with the same player")
    score_a = get_qb_score(conn, sport=sport, player_id=a)
    score_b = get_qb_score(conn, sport=sport, player_id=b)

    inconclusive: QbScoreInconclusiveReason | None = None
    if score_a.qualifying_seasons == 0 and score_b.qualifying_seasons == 0:
        inconclusive = "neither_has_qualifying_season"
    elif score_a.qualifying_seasons == 0:
        inconclusive = "a_no_qualifying_season"
    elif score_b.qualifying_seasons == 0:
        inconclusive = "b_no_qualifying_season"

    career_margin: float | None = None
    peak_margin: float | None = None
    if inconclusive is None:
        assert score_a.career is not None and score_b.career is not None
        assert score_a.peak is not None and score_b.peak is not None
        career_margin = score_a.career - score_b.career
        peak_margin = score_a.peak - score_b.peak
    return QbScoreComparison(
        sport=sport,
        version=QB_SCORE_VERSION,
        a=score_a,
        b=score_b,
        career_winner=None if career_margin is None else _winner(career_margin),
        peak_winner=None if peak_margin is None else _winner(peak_margin),
        career_margin=career_margin,
        peak_margin=peak_margin,
        inconclusive=inconclusive,
        weights=QB_SCORE_WEIGHTS,
    )


def fit_qb_score_weights(conn: sqlite3.Connection, *, sport: Sport) -> QbScoreWeightFit:
    """The reproducible refit behind `QB_SCORE_WEIGHTS`: OLS with no
    intercept of next season's total-EPA-per-play z on this season's
    (z_epa_per_dropback, z_rush_epa_per_play), over every pair of the same
    QB qualifying in seasons y and y+1. Weights are the coefficients
    normalised to sum to 1. Raises ValueError when there is no pair, or the
    pairs can't separate the two metrics."""
    rows = [_row(r) for r in conn.execute(_ALL_QUALIFYING_ROWS_SQL, _params(sport)).fetchall()]
    metrics: tuple[QbScoreMetric, QbScoreMetric] = ("epa_per_dropback", "rush_epa_per_play")
    baselines = {m: _baselines(rows, _rate(m)) for m in metrics}
    target = _baselines(rows, lambda row: row.total_epa_per_play)
    by_key = {(row.player_id, row.season): row for row in rows}

    xs: list[tuple[float, float]] = []
    ys: list[float] = []
    years: list[int] = []
    for (player_id, season), row in sorted(by_key.items()):
        following = by_key.get((player_id, season + 1))
        if following is None:
            continue
        x = []
        for m in metrics:
            value = row.rates[m]
            assert value is not None
            x.append(baselines[m][season].z(value))
        assert following.total_epa_per_play is not None
        xs.append((x[0], x[1]))
        ys.append(target[season + 1].z(following.total_epa_per_play))
        years.append(season)
    if not xs:
        raise ValueError(f"no consecutive qualifying QB-season pairs in {sport}")

    # Normal equations, 2x2, solved by Cramer's rule.
    s11 = sum(x1 * x1 for x1, _ in xs)
    s12 = sum(x1 * x2 for x1, x2 in xs)
    s22 = sum(x2 * x2 for _, x2 in xs)
    t1 = sum(x1 * y for (x1, _), y in zip(xs, ys, strict=True))
    t2 = sum(x2 * y for (_, x2), y in zip(xs, ys, strict=True))
    det = s11 * s22 - s12 * s12
    if det == 0:
        raise ValueError("the pairs cannot separate the two metrics (singular fit)")
    b1 = (t1 * s22 - t2 * s12) / det
    b2 = (s11 * t2 - s12 * t1) / det
    return QbScoreWeightFit(
        n_pairs=len(xs),
        first_season=min(years),
        last_season=max(years) + 1,
        coefficients=MappingProxyType({metrics[0]: b1, metrics[1]: b2}),
        weights=MappingProxyType({metrics[0]: b1 / (b1 + b2), metrics[1]: b2 / (b1 + b2)}),
    )
