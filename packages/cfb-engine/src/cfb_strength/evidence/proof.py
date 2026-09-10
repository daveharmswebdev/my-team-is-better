"""Empirical-proof layer: schedules, quality wins, worst losses, and
head-to-head / common-opponent comparisons between two teams.

This module reads the `ratings`, `games`, and `teams` tables directly via
SQL. It must never import `cfb_strength.ratings` or `cfb_strength.ingest` --
the database is the integration boundary, not Python imports (enforced by
import-linter's independence contract).
"""

from __future__ import annotations

import difflib
import sqlite3
from typing import Literal

from cfb_strength.contracts import (
    AmbiguousTeamError,
    ComparisonResult,
    ComparisonTeamSummary,
    CommonOpponent,
    HeadToHead,
    HeadToHeadMeeting,
    OpponentResult,
    SameTeamComparisonError,
    TeamCase,
    UnknownYearError,
)

# Wins against an opponent ranked this or better count as "quality wins".
# Take 1 used a top-25 threshold; we keep that convention here.
QUALITY_WIN_RANK_THRESHOLD = 25


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _rated_teams(conn: sqlite3.Connection, year: int, method: str) -> list[sqlite3.Row]:
    """All (team_id, school) pairs that have a rating row for year/method."""
    return conn.execute(
        """
        SELECT t.id AS team_id, t.school AS school
        FROM ratings r
        JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ?
        """,
        (year, method),
    ).fetchall()


def _ratings_map(conn: sqlite3.Connection, year: int, method: str) -> dict[int, sqlite3.Row]:
    """team_id -> ratings row, for every team rated in year/method."""
    rows = conn.execute(
        "SELECT team_id, rating, rank, wins, losses FROM ratings WHERE year = ? AND method = ?",
        (year, method),
    ).fetchall()
    return {int(r["team_id"]): r for r in rows}


def _require_year(conn: sqlite3.Connection, year: int, method: str) -> None:
    years = list_available_years(conn, method)
    if year not in years:
        raise UnknownYearError(year, years)


# ---------------------------------------------------------------------------
# public API (signatures fixed by contracts.py -- do not rename/reorder)
# ---------------------------------------------------------------------------


def list_available_years(conn: sqlite3.Connection, method: str = "keener") -> list[int]:
    """Distinct years for which ratings exist under `method`, ascending."""
    rows = conn.execute(
        "SELECT DISTINCT year FROM ratings WHERE method = ? ORDER BY year", (method,)
    ).fetchall()
    return [int(r["year"]) for r in rows]


def resolve_team(
    conn: sqlite3.Connection, year: int, query: str, method: str = "keener"
) -> int:
    """Resolve a team name query to a team_id, scoped to teams that have a
    rating row for `year`/`method` (a team without a rating can't have a
    TeamCase built for it anyway).

    Resolution order:
      1. Exact match (case-insensitive, whitespace-trimmed).
      2. Substring match (either direction), case-insensitive.
      3. Fuzzy match via difflib.get_close_matches.

    Raises AmbiguousTeamError if any stage other than a unique exact match
    yields more than one candidate. Raises UnknownYearError if there are no
    ratings at all for year/method.
    """
    _require_year(conn, year, method)
    candidates = _rated_teams(conn, year, method)

    q = query.strip()
    q_lower = q.lower()

    exact = [row for row in candidates if row["school"].lower() == q_lower]
    if len(exact) == 1:
        return int(exact[0]["team_id"])
    if len(exact) > 1:
        raise AmbiguousTeamError(query, sorted(r["school"] for r in exact))

    substring = [
        row
        for row in candidates
        if q_lower in row["school"].lower() or row["school"].lower() in q_lower
    ]
    if len(substring) == 1:
        return int(substring[0]["team_id"])
    if len(substring) > 1:
        raise AmbiguousTeamError(query, sorted(r["school"] for r in substring))

    names = [row["school"] for row in candidates]
    close = difflib.get_close_matches(q, names, n=10, cutoff=0.6)
    if len(close) == 1:
        matched = close[0]
        return int(next(r["team_id"] for r in candidates if r["school"] == matched))

    # Either 0 matches (genuinely not found) or >1 (ambiguous). contracts.py
    # has no dedicated "not found" error, so we reuse AmbiguousTeamError with
    # an empty candidate list for the 0 case -- its message ("could not
    # uniquely resolve ...: candidates=[]") still reads correctly there.
    # Reported as a contract-insufficiency note in the delegation return.
    raise AmbiguousTeamError(query, sorted(close))


def _team_games(conn: sqlite3.Connection, year: int, team_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, week, season_type, neutral_site,
               home_team_id, away_team_id, home_team, away_team,
               home_points, away_points
        FROM games
        WHERE season = ? AND completed = 1
          AND (home_team_id = ? OR away_team_id = ?)
        ORDER BY
            CASE season_type WHEN 'regular' THEN 0 ELSE 1 END,
            week
        """,
        (year, team_id, team_id),
    ).fetchall()


def _opponent_result(
    game: sqlite3.Row, team_id: int, ratings: dict[int, sqlite3.Row]
) -> OpponentResult | None:
    is_home = game["home_team_id"] == team_id
    team_score = game["home_points"] if is_home else game["away_points"]
    opp_score = game["away_points"] if is_home else game["home_points"]
    opponent_id = game["away_team_id"] if is_home else game["home_team_id"]
    opponent_name = game["away_team"] if is_home else game["home_team"]

    if team_score is None or opp_score is None or team_score == opp_score:
        # Equal scores in this dataset are data artifacts (e.g. 0-0 rows for
        # small-school games CFBD never reported), not real modern-era ties
        # -- OpponentResult only models W/L, so skip anything without a
        # well-defined winner.
        return None

    result: Literal["W", "L"] = "W" if team_score > opp_score else "L"
    opp_rating_row = ratings.get(int(opponent_id))

    return OpponentResult(
        opponent_team_id=int(opponent_id),
        opponent_name=opponent_name,
        opponent_rank=int(opp_rating_row["rank"]) if opp_rating_row is not None else None,
        opponent_rating=float(opp_rating_row["rating"]) if opp_rating_row is not None else None,
        result=result,
        team_score=int(team_score),
        opponent_score=int(opp_score),
        week=int(game["week"]) if game["week"] is not None else None,
        season_type=game["season_type"],
        neutral_site=bool(game["neutral_site"]),
    )


def build_team_case(
    conn: sqlite3.Connection, year: int, team: str, method: str = "keener"
) -> TeamCase:
    team_id = resolve_team(conn, year, team, method=method)

    rating_row = conn.execute(
        "SELECT rating, rank, wins, losses FROM ratings WHERE year = ? AND method = ? AND team_id = ?",
        (year, method, team_id),
    ).fetchone()
    # resolve_team only returns ids scoped to rated teams, so this must exist.
    assert rating_row is not None

    team_name_row = conn.execute("SELECT school FROM teams WHERE id = ?", (team_id,)).fetchone()
    team_name = team_name_row["school"] if team_name_row is not None else team

    ratings = _ratings_map(conn, year, method)
    games = _team_games(conn, year, team_id)

    opponent_results: list[OpponentResult] = []
    for game in games:
        result = _opponent_result(game, team_id, ratings)
        if result is not None:
            opponent_results.append(result)

    quality_wins = sorted(
        (
            o
            for o in opponent_results
            if o.result == "W"
            and o.opponent_rank is not None
            and o.opponent_rank <= QUALITY_WIN_RANK_THRESHOLD
        ),
        key=lambda o: o.opponent_rank,  # type: ignore[arg-type, return-value]
    )

    losses = [o for o in opponent_results if o.result == "L"]
    worst_loss: OpponentResult | None = None
    if losses:
        worst_loss = max(
            losses,
            key=lambda o: (o.opponent_rank is None, o.opponent_rank or 0),
        )

    return TeamCase(
        year=year,
        method=method,
        team_id=team_id,
        team_name=team_name,
        rank=int(rating_row["rank"]),
        rating=float(rating_row["rating"]),
        wins=int(rating_row["wins"]),
        losses=int(rating_row["losses"]),
        games=opponent_results,
        quality_wins=quality_wins,
        worst_loss=worst_loss,
    )


def _case_summary(case: TeamCase) -> ComparisonTeamSummary:
    return ComparisonTeamSummary(
        team_id=case.team_id,
        team_name=case.team_name,
        rank=case.rank,
        rating=case.rating,
        wins=case.wins,
        losses=case.losses,
        quality_wins=case.quality_wins,
        worst_loss=case.worst_loss,
    )


def build_comparison(
    conn: sqlite3.Connection, year: int, team_a: str, team_b: str, method: str = "keener"
) -> ComparisonResult:
    team_a_id = resolve_team(conn, year, team_a, method=method)
    team_b_id = resolve_team(conn, year, team_b, method=method)
    if team_a_id == team_b_id:
        team_name_row = conn.execute(
            "SELECT school FROM teams WHERE id = ?", (team_a_id,)
        ).fetchone()
        resolved_name = team_name_row["school"] if team_name_row is not None else team_a
        raise SameTeamComparisonError(resolved_name)

    case_a = build_team_case(conn, year, team_a, method=method)
    case_b = build_team_case(conn, year, team_b, method=method)

    # Head-to-head: any completed game this season between the two teams.
    h2h_games = conn.execute(
        """
        SELECT week, season_type, neutral_site, home_team_id, away_team_id,
               home_team, away_team, home_points, away_points
        FROM games
        WHERE season = ? AND completed = 1
          AND ((home_team_id = ? AND away_team_id = ?)
            OR (home_team_id = ? AND away_team_id = ?))
        ORDER BY CASE season_type WHEN 'regular' THEN 0 ELSE 1 END, week
        """,
        (year, case_a.team_id, case_b.team_id, case_b.team_id, case_a.team_id),
    ).fetchall()

    meetings: list[HeadToHeadMeeting] = []
    if h2h_games:
        for g in h2h_games:
            if g["home_points"] is None or g["away_points"] is None:
                continue
            a_is_home = g["home_team_id"] == case_a.team_id
            a_score = g["home_points"] if a_is_home else g["away_points"]
            b_score = g["away_points"] if a_is_home else g["home_points"]
            winner = (
                case_a.team_name
                if a_score > b_score
                else case_b.team_name
                if b_score > a_score
                else None
            )
            meetings.append(
                HeadToHeadMeeting(
                    week=g["week"],
                    season_type=g["season_type"],
                    neutral_site=bool(g["neutral_site"]),
                    home_team=g["home_team"],
                    away_team=g["away_team"],
                    home_points=g["home_points"],
                    away_points=g["away_points"],
                    winner=winner,
                )
            )
    head_to_head = HeadToHead(played=bool(meetings), meetings=meetings)

    # Common opponents: any team both A and B played this season (excluding
    # each other), with each side's result against that opponent.
    a_by_opp = {o.opponent_team_id: o for o in case_a.games}
    b_by_opp = {o.opponent_team_id: o for o in case_b.games}
    common_ids = (set(a_by_opp) & set(b_by_opp)) - {case_a.team_id, case_b.team_id}

    common_opponents: list[CommonOpponent] = []
    for opp_id in common_ids:
        oa = a_by_opp[opp_id]
        ob = b_by_opp[opp_id]
        common_opponents.append(
            CommonOpponent(
                opponent_team_id=opp_id,
                opponent_name=oa.opponent_name,
                opponent_rank=oa.opponent_rank,
                team_a_result=oa.result,
                team_a_score=oa.team_score,
                team_a_opponent_score=oa.opponent_score,
                team_b_result=ob.result,
                team_b_score=ob.team_score,
                team_b_opponent_score=ob.opponent_score,
            )
        )
    common_opponents.sort(key=lambda c: (c.opponent_rank is None, c.opponent_rank or 0))

    rating_diff = case_a.rating - case_b.rating

    verdict = _build_verdict(case_a, case_b, meetings, common_opponents, rating_diff)

    return ComparisonResult(
        year=year,
        team_a=_case_summary(case_a),
        team_b=_case_summary(case_b),
        head_to_head=head_to_head,
        common_opponents=common_opponents,
        rating_diff=rating_diff,
        verdict=verdict,
    )


def _build_verdict(
    case_a: TeamCase,
    case_b: TeamCase,
    meetings: list[HeadToHeadMeeting],
    common_opponents: list[CommonOpponent],
    rating_diff: float,
) -> str:
    parts: list[str] = []

    if meetings:
        for m in meetings:
            if m.winner == case_a.team_name:
                parts.append(
                    f"{case_a.team_name} beat {case_b.team_name} head-to-head "
                    f"{m.home_points}-{m.away_points} "
                    f"({m.home_team} vs {m.away_team}, week {m.week})."
                )
            elif m.winner == case_b.team_name:
                parts.append(
                    f"{case_b.team_name} beat {case_a.team_name} head-to-head "
                    f"{m.home_points}-{m.away_points} "
                    f"({m.home_team} vs {m.away_team}, week {m.week})."
                )
    else:
        parts.append(f"{case_a.team_name} and {case_b.team_name} did not play each other.")

    if common_opponents:
        for c in common_opponents[:3]:
            parts.append(
                f"vs common opponent {c.opponent_name} "
                f"(rank {c.opponent_rank}): {case_a.team_name} went {c.team_a_result}, "
                f"{case_b.team_name} went {c.team_b_result}."
            )

    leader = case_a.team_name if rating_diff > 0 else case_b.team_name if rating_diff < 0 else None
    if leader:
        parts.append(
            f"{leader} rates higher overall ({case_a.rating:.6f} vs {case_b.rating:.6f}, "
            f"rank {case_a.rank} vs {case_b.rank})."
        )
    else:
        parts.append("Ratings are effectively tied.")

    return " ".join(parts)
