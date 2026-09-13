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
    CommonOpponent,
    ComparisonResult,
    ComparisonTeamSummary,
    HeadToHead,
    HeadToHeadMeeting,
    Method,
    OpponentCredit,
    OpponentResult,
    RatingBreakdown,
    SameTeamComparisonError,
    Sport,
    TeamCase,
    UnknownTeamError,
    UnknownYearError,
)
from cfb_strength.evidence.credit_explain import explain_credit

# Wins against an opponent ranked this or better count as "quality wins".
# Take 1 used a top-25 threshold; we keep that convention here.
QUALITY_WIN_RANK_THRESHOLD = 25

# Fuzzy-match tuning for `resolve_team`'s third and last stage: one close
# name at or above this ratio is a resolution. Anything below it is not a
# match and gets no second, looser pass -- see UnknownTeamError in
# contracts.py for why a near-miss list cannot be built here.
FUZZY_MATCH_CUTOFF = 0.6
FUZZY_MATCH_LIMIT = 10

# How `build_comparison`'s verdict prints a rating, per registered method
# (issue #95). A rating's scale is the method's, so its precision is too:
#
# - keener: six places. Its ratings are a sum-to-1 eigenvector (~0.005 for a
#   CFB team), so fewer places would erase the differences. This is the
#   pre-#95 text, byte for byte.
# - elo / elo_career: one place. Ratings sit around 1100-2000, where `.6f`
#   printed false precision ("1523.456789"). One place still separates two
#   teams a few tenths apart. An integer would print a dead heat right beside
#   a sentence claiming one of them "rates higher".
#
# Keyed by `Method` so a stray key is a mypy error. evidence/test_proof.py
# checks the keys equal `typing.get_args(Method)`, so a newly registered
# method must choose a format here. `_verdict_rating_format` raises for
# anything unlisted rather than falling back to `.6f`.
VERDICT_RATING_FORMATS: dict[Method, str] = {
    "keener": ".6f",
    "elo": ".1f",
    "elo_career": ".1f",
}


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _rated_teams(
    conn: sqlite3.Connection, year: int, method: str, sport: str
) -> list[sqlite3.Row]:
    """All (team_id, school) pairs that have a rating row for year/method/sport.

    `sport` must be filtered here (issue #58, same bug class as #57 in
    ratings/compute_ratings.py): CFB and NFL rows can share a `year` value,
    so an unfiltered join would let a same-named team from the other sport
    bleed into `resolve_team`'s candidate pool.
    """
    return conn.execute(
        """
        SELECT t.id AS team_id, t.school AS school
        FROM ratings r
        JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ? AND r.sport = ?
        """,
        (year, method, sport),
    ).fetchall()


def _ratings_map(
    conn: sqlite3.Connection, year: int, method: str, sport: str
) -> dict[int, sqlite3.Row]:
    """team_id -> ratings row, for every team rated in year/method/sport."""
    rows = conn.execute(
        "SELECT team_id, rating, rank, wins, losses FROM ratings "
        "WHERE year = ? AND method = ? AND sport = ?",
        (year, method, sport),
    ).fetchall()
    return {int(r["team_id"]): r for r in rows}


def _scores_vs_opponent(
    games: list[sqlite3.Row], team_id: int, opponent_team_id: int
) -> list[tuple[int, int]]:
    """(team_score, opponent_score) tuples, in `games`' existing chronological
    order, for every completed game in `games` (already scoped to `team_id`
    by `_team_games`) played against `opponent_team_id` specifically.

    Mirrors `_opponent_result`'s is_home resolution and null-score skip
    exactly, so the games fed to `explain_credit` are the same games (by
    score) `OpponentResult` itself would report for this matchup -- ties
    included (issue #83), which also keeps the explanation's game count in
    step with the persisted `games_played`, which has always counted them.
    """
    pairs: list[tuple[int, int]] = []
    for game in games:
        is_home = game["home_team_id"] == team_id
        opponent_id = game["away_team_id"] if is_home else game["home_team_id"]
        if opponent_id != opponent_team_id:
            continue
        team_score = game["home_points"] if is_home else game["away_points"]
        opp_score = game["away_points"] if is_home else game["home_points"]
        if team_score is None or opp_score is None:
            continue
        pairs.append((int(team_score), int(opp_score)))
    return pairs


def _rating_breakdown(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    games: list[sqlite3.Row],
    sport: str,
) -> RatingBreakdown:
    """Reconstruct a team's `RatingBreakdown` from `rating_breakdowns` rows.

    `OpponentCredit` (contracts.py) only carries `opponent_team_id` from the
    ratings layer (`keener.py` never sees names, only ids) -- this join
    against `teams` (same pattern as `_opponent_result`'s resolution for
    `OpponentResult.opponent_name`) is what populates the real
    `opponent_name` for each entry. Entries are ordered by `contribution`
    descending (largest driver of the rating first), which matches the
    descending-by-significance convention `quality_wins` and
    `common_opponents` already use elsewhere in this module.

    `games` is the same raw per-game score rows `build_team_case` already
    fetches via `_team_games` for `OpponentResult` construction -- reused
    here (issue #37) so `OpponentCredit.explanation` is derived from the
    exact same scores, via the exact same `single_game_credit` call, that
    the persisted `credit`/`contribution` columns were computed from.

    A rated team always has breakdown rows too (`compute_and_store` writes
    both tables together in the same pass -- see compute_ratings.py's
    `_store`/`_store_breakdowns`), but this degrades gracefully (empty
    entries, zero residual) rather than raising if rows are ever missing,
    e.g. a fixture db computed before this table existed.
    """
    rows = conn.execute(
        """
        SELECT opponent_team_id, games_played, wins, losses, credit, contribution
        FROM rating_breakdowns
        WHERE year = ? AND method = ? AND team_id = ? AND sport = ?
        """,
        (year, method, team_id, sport),
    ).fetchall()

    entries: list[OpponentCredit] = []
    residual_contribution = 0.0
    for row in rows:
        if row["opponent_team_id"] is None:
            residual_contribution = float(row["contribution"])
            continue
        opponent_team_id = int(row["opponent_team_id"])
        opponent_name_row = conn.execute(
            "SELECT school FROM teams WHERE id = ?", (opponent_team_id,)
        ).fetchone()
        opponent_name = opponent_name_row["school"] if opponent_name_row is not None else ""
        # Defensive: the rating_breakdowns row and the games query are two
        # different sources (persisted vs. re-queried), so in principle they
        # could disagree on which games were played. If filtering yields no
        # valid scores for this pair, leave explanation="" rather than
        # crashing or guessing -- see this delegation's contract_gaps note.
        scores = _scores_vs_opponent(games, team_id, opponent_team_id)
        entries.append(
            OpponentCredit(
                opponent_team_id=opponent_team_id,
                games_played=int(row["games_played"]),
                wins=int(row["wins"]),
                losses=int(row["losses"]),
                credit=float(row["credit"]),
                contribution=float(row["contribution"]),
                opponent_name=opponent_name,
                explanation=explain_credit(scores),
            )
        )

    entries.sort(key=lambda e: e.contribution, reverse=True)
    return RatingBreakdown(entries=entries, residual_contribution=residual_contribution)


def _require_year(conn: sqlite3.Connection, year: int, method: str, sport: Sport) -> None:
    years = list_available_years(conn, method, sport)
    if year not in years:
        raise UnknownYearError(year, years)


# ---------------------------------------------------------------------------
# public API (signatures fixed by contracts.py -- do not rename/reorder)
# ---------------------------------------------------------------------------


def list_available_years(
    conn: sqlite3.Connection, method: str = "keener", sport: Sport = "cfb"
) -> list[int]:
    """Distinct years for which ratings exist under `method`/`sport`, ascending."""
    rows = conn.execute(
        "SELECT DISTINCT year FROM ratings WHERE method = ? AND sport = ? ORDER BY year",
        (method, sport),
    ).fetchall()
    return [int(r["year"]) for r in rows]


def resolve_team(
    conn: sqlite3.Connection,
    year: int,
    query: str,
    method: str = "keener",
    sport: Sport = "cfb",
) -> int:
    """Resolve a team name query to a team_id, scoped to teams that have a
    rating row for `year`/`method`/`sport` (a team without a rating can't have
    a TeamCase built for it anyway).

    Resolution order:
      1. Exact match (case-insensitive, whitespace-trimmed).
      2. Substring match (either direction), case-insensitive.
      3. Fuzzy match via difflib.get_close_matches.

    Raises AmbiguousTeamError if any stage other than a unique exact match
    yields more than one candidate (its `candidates` list is always
    non-empty). Raises UnknownTeamError -- carrying only the query, year and
    sport -- if no stage matches anything at all. Raises UnknownYearError if
    there are no ratings at all for year/method/sport.
    """
    _require_year(conn, year, method, sport)
    candidates = _rated_teams(conn, year, method, sport)

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
    close = difflib.get_close_matches(q, names, n=FUZZY_MATCH_LIMIT, cutoff=FUZZY_MATCH_CUTOFF)
    if len(close) == 1:
        matched = close[0]
        return int(next(r["team_id"] for r in candidates if r["school"] == matched))

    # 0 matches and >1 are opposite failures and must not share an error
    # (issue #100): >1 is "which of these did you mean", 0 is "no such rated
    # team". Conflating them produced an `ambiguous_team` payload with an
    # empty candidate list, i.e. a "did you mean:" prompt with nothing under
    # it. AmbiguousTeamError.candidates is therefore non-empty from every
    # raise site in this module, by construction.
    if len(close) > 1:
        raise AmbiguousTeamError(query, sorted(close))

    raise UnknownTeamError(query, year, sport)


def _team_games(
    conn: sqlite3.Connection, year: int, team_id: int, sport: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, week, season_type, neutral_site,
               home_team_id, away_team_id, home_team, away_team,
               home_points, away_points
        FROM games
        WHERE season = ? AND sport = ? AND completed = 1
          AND (home_team_id = ? OR away_team_id = ?)
        ORDER BY
            CASE season_type WHEN 'regular' THEN 0 ELSE 1 END,
            week
        """,
        (year, sport, team_id, team_id),
    ).fetchall()


def _opponent_result(
    game: sqlite3.Row, team_id: int, ratings: dict[int, sqlite3.Row]
) -> OpponentResult | None:
    is_home = game["home_team_id"] == team_id
    team_score = game["home_points"] if is_home else game["away_points"]
    opp_score = game["away_points"] if is_home else game["home_points"]
    opponent_id = game["away_team_id"] if is_home else game["home_team_id"]
    opponent_name = game["away_team"] if is_home else game["home_team"]

    if team_score is None or opp_score is None:
        # No score, no result to report.
        return None

    # Equal scores are a tie by definition (contracts.TeamRating.ties), in
    # every sport -- the same definition the ratings layer uses to count
    # `ratings.ties`, so the listed games and the record always agree. CFB's
    # completed 0-0 rows for small-school games CFBD never reported are bad
    # data, not ties; ingest stores them with NULL scores (#128), so they are
    # skipped just above -- no sport exception here.
    result: Literal["W", "L", "T"] = (
        "W" if team_score > opp_score else "L" if team_score < opp_score else "T"
    )
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
    conn: sqlite3.Connection,
    year: int,
    team: str,
    method: str = "keener",
    sport: Sport = "cfb",
) -> TeamCase:
    team_id = resolve_team(conn, year, team, method=method, sport=sport)

    rating_row = conn.execute(
        "SELECT rating, rank, wins, losses, ties FROM ratings "
        "WHERE year = ? AND method = ? AND team_id = ? AND sport = ?",
        (year, method, team_id, sport),
    ).fetchone()
    # resolve_team only returns ids scoped to rated teams, so this must exist.
    assert rating_row is not None

    team_name_row = conn.execute("SELECT school FROM teams WHERE id = ?", (team_id,)).fetchone()
    team_name = team_name_row["school"] if team_name_row is not None else team

    ratings = _ratings_map(conn, year, method, sport)
    games = _team_games(conn, year, team_id, sport)
    rating_breakdown = _rating_breakdown(conn, year, method, team_id, games, sport)

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
        ties=int(rating_row["ties"]),
        rating_breakdown=rating_breakdown,
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
        ties=case.ties,
        rating_breakdown=case.rating_breakdown,
        quality_wins=case.quality_wins,
        worst_loss=case.worst_loss,
    )


def build_comparison(
    conn: sqlite3.Connection,
    year: int,
    team_a: str,
    team_b: str,
    method: str = "keener",
    sport: Sport = "cfb",
) -> ComparisonResult:
    team_a_id = resolve_team(conn, year, team_a, method=method, sport=sport)
    team_b_id = resolve_team(conn, year, team_b, method=method, sport=sport)
    if team_a_id == team_b_id:
        team_name_row = conn.execute(
            "SELECT school FROM teams WHERE id = ?", (team_a_id,)
        ).fetchone()
        resolved_name = team_name_row["school"] if team_name_row is not None else team_a
        raise SameTeamComparisonError(resolved_name)

    case_a = build_team_case(conn, year, team_a, method=method, sport=sport)
    case_b = build_team_case(conn, year, team_b, method=method, sport=sport)

    # Head-to-head: any completed game this season between the two teams.
    h2h_games = conn.execute(
        """
        SELECT week, season_type, neutral_site, home_team_id, away_team_id,
               home_team, away_team, home_points, away_points
        FROM games
        WHERE season = ? AND sport = ? AND completed = 1
          AND ((home_team_id = ? AND away_team_id = ?)
            OR (home_team_id = ? AND away_team_id = ?))
        ORDER BY CASE season_type WHEN 'regular' THEN 0 ELSE 1 END, week
        """,
        (year, sport, case_a.team_id, case_b.team_id, case_b.team_id, case_a.team_id),
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


def _verdict_rating_format(method: str) -> str:
    """The verdict's format spec for `method`'s ratings.

    Raises ValueError for a method with no registered format. The public API
    only reaches this with a method that has stored ratings, and a database
    written by a newer or experimental engine can hold rows for a method this
    table doesn't know. Guessing a precision for such a method is the bug
    #95 fixed, so this refuses instead.
    """
    if method not in VERDICT_RATING_FORMATS:
        raise ValueError(
            f"no verdict rating format registered for method {method!r}; "
            f"registered: {list(VERDICT_RATING_FORMATS)}"
        )
    return VERDICT_RATING_FORMATS[method]


def _build_verdict(
    case_a: TeamCase,
    case_b: TeamCase,
    meetings: list[HeadToHeadMeeting],
    common_opponents: list[CommonOpponent],
    rating_diff: float,
) -> str:
    # Looked up before any prose is built, so an unregistered method raises
    # whatever the data, including when the ratings are exactly tied.
    rating_format = _verdict_rating_format(case_a.method)
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
                # winner=None: a tied meeting (issue #83). Null-score meetings
                # never reach `meetings`, so this is always equal scores.
                parts.append(
                    f"{case_a.team_name} and {case_b.team_name} tied head-to-head "
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
            f"{leader} rates higher overall "
            f"({case_a.rating:{rating_format}} vs {case_b.rating:{rating_format}}, "
            f"rank {case_a.rank} vs {case_b.rank})."
        )
    else:
        parts.append("Ratings are effectively tied.")

    return " ".join(parts)
