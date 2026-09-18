"""Empirical-proof layer: schedules, quality wins, worst losses, and
head-to-head / common-opponent comparisons between two teams.

This module reads the `ratings`, `games`, and `teams` tables (plus
`rating_breakdowns`, `elo_ledger_steps` and `elo_ledger_configs`) directly via
SQL. It must never import `cfb_strength.ratings` or `cfb_strength.ingest` --
the database is the integration boundary, not Python imports (enforced by
import-linter's independence contract).
"""

from __future__ import annotations

import difflib
import sqlite3
from typing import Literal, cast

from cfb_strength.contracts import (
    AmbiguousTeamError,
    CommonOpponent,
    CommonOpponentMeeting,
    ComparisonResult,
    ComparisonTeamSummary,
    EloGameStep,
    EloLedger,
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
#   printed false precision ("1523.456789"). One place separates most
#   neighbouring teams, which an integer often would not.
#
# No fixed precision rules out a printed dead heat. Two ratings closer than
# half the last printed place print as equal (e.g. "1531.2 vs 1531.2"), and
# keener's `.6f` does this for a few real pairs too. This table makes such
# dead heats rare, not impossible. Issue #149 chose wording over precision:
# `_build_verdict` compares the two formatted strings and, when they match
# but the ratings differ, says "rates a hair higher overall" instead of
# "rates higher overall". The numbers printed never change.
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


# The two tables issue #183 added. `_elo_ledger` checks both exist before it
# queries either, so a pre-#183 database opened read-only (apps/api and the
# MCP server never run ensure_schema) fails as `StaleDatabaseError` instead
# of a bare `sqlite3.OperationalError: no such table` (issue #192).
ELO_LEDGER_TABLES: tuple[str, ...] = ("elo_ledger_configs", "elo_ledger_steps")


class StaleDatabaseError(RuntimeError):
    """Raised by evidence functions when the database predates the schema
    they read (issue #192): today, the Elo ledger tables from issue #183.

    Deliberately loud rather than degrading to "no ledger" (the #97 spirit).
    A reader that opens the db read-only cannot migrate it, and a stale db is
    stale whichever method is asked -- `build_team_case` reads the ledger for
    every method -- so every verdict fails, keener included, with a message
    that names the missing table(s), the diagnosis and the fix. A
    RuntimeError, not a ValueError: nothing about the request was wrong.
    """

    def __init__(self, missing_tables: tuple[str, ...]):
        names = ", ".join(missing_tables)
        noun = "table" if len(missing_tables) == 1 else "tables"
        super().__init__(
            f"stale database: missing {noun} {names}. This database was built "
            "before the Elo ledger (issue #183) and is opened read-only, so nothing "
            "has added the ledger tables to it. Run `cfb doctor` for the diagnosis; "
            "the fix is a rebuild of the ratings (`cfb rate --years ... --method elo`, "
            "or the full render.yaml build sequence)."
        )
        self.missing_tables = missing_tables


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _rated_teams(conn: sqlite3.Connection, year: int, method: str, sport: str) -> list[sqlite3.Row]:
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


def _require_elo_ledger_tables(conn: sqlite3.Connection) -> None:
    """Raise `StaleDatabaseError` unless both #183 ledger tables exist.

    One `sqlite_master` lookup per call (so one per `_elo_ledger`, never one
    per step). Checking before querying is what turns "no such table" into a
    named, explained error; catching sqlite's OperationalError afterwards
    would also have to guess which of several possible causes it was.
    """
    placeholders = ", ".join("?" for _ in ELO_LEDGER_TABLES)
    present = {
        row[0]
        for row in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
            ELO_LEDGER_TABLES,
        )
    }
    missing = tuple(t for t in ELO_LEDGER_TABLES if t not in present)
    if missing:
        raise StaleDatabaseError(missing)


def _elo_ledger(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    sport: str,
) -> EloLedger | None:
    """Read a team's `EloLedger` back from `elo_ledger_configs` and
    `elo_ledger_steps` (issue #183), exactly as stored.

    Steps are ordered by `game_number` (the walk's order), and every
    `opponent_name` comes from `teams.school` through one join rather than a
    query per step. Every numeric field is copied as stored. Nothing is
    recomputed or checked here: the stored values are the walk's own, and
    re-deriving them would be a second, possibly different, answer.

    Returns None when the (year, method, sport) has no config row and this
    team has no steps. That is a method with no ledger (keener, elo_career),
    or elo ratings computed before #183 in a database that `ensure_schema`
    has since brought up to date (the tables exist, empty).

    Raises `StaleDatabaseError` (issue #192) before any ledger query when
    either ledger table is absent altogether: a pre-#183 database opened
    read-only, which no caller on that path migrates. That fires for every
    method, keener included, because a stale db is stale regardless of the
    method asked, and a bare "no such table" from sqlite would say nothing
    about why or what to do.

    Raises ValueError, naming the missing table, when only one side is
    present (a config row but no steps for this rated team, or steps with no
    config row), or when a step's opponent has no `teams` row. Any of those is
    a corrupt database. Inventing constants, dropping a step, or showing a
    blank opponent would present fabricated work as evidence.
    """
    _require_elo_ledger_tables(conn)
    config = conn.execute(
        """
        SELECT starting_rating, k, hfa, scale, mov_scale, mov_autocorr,
               mov_denom_floor_fraction
        FROM elo_ledger_configs c
        WHERE c.year = ? AND c.method = ? AND c.sport = ?
        """,
        (year, method, sport),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT s.game_number, s.week, s.season_type, s.start_date,
               s.opponent_team_id, s.venue, s.team_points, s.opponent_points,
               s.result, s.rating_before, s.opponent_rating_before,
               s.home_field_adjustment, s.rating_gap, s.win_expectancy,
               s.mov_multiplier, s.shift, s.rating_after,
               t.school AS opponent_name
        FROM elo_ledger_steps s
        LEFT JOIN teams t ON t.id = s.opponent_team_id
        WHERE s.year = ? AND s.method = ? AND s.sport = ? AND s.team_id = ?
        ORDER BY s.game_number
        """,
        (year, method, sport, team_id),
    ).fetchall()

    if config is None and not rows:
        return None
    scope = f"year={year}, method={method!r}, sport={sport!r}"
    if config is None:
        raise ValueError(
            f"corrupt Elo ledger: no elo_ledger_configs row for {scope}, "
            f"although team_id={team_id} has {len(rows)} stored ledger step(s)"
        )
    if not rows:
        raise ValueError(
            f"corrupt Elo ledger: no elo_ledger_steps rows for team_id={team_id} "
            f"({scope}), although a ledger config exists and the team is rated"
        )

    steps: list[EloGameStep] = []
    for row in rows:
        if row["opponent_name"] is None:
            raise ValueError(
                f"corrupt Elo ledger: step {row['game_number']} for team_id={team_id} "
                f"({scope}) names opponent_team_id={row['opponent_team_id']}, "
                "which has no row in teams"
            )
        steps.append(
            EloGameStep(
                game_number=int(row["game_number"]),
                opponent_team_id=int(row["opponent_team_id"]),
                venue=cast(Literal["home", "away", "neutral"], row["venue"]),
                team_points=int(row["team_points"]),
                opponent_points=int(row["opponent_points"]),
                result=cast(Literal["W", "L", "T"], row["result"]),
                rating_before=float(row["rating_before"]),
                opponent_rating_before=float(row["opponent_rating_before"]),
                home_field_adjustment=float(row["home_field_adjustment"]),
                rating_gap=float(row["rating_gap"]),
                win_expectancy=float(row["win_expectancy"]),
                mov_multiplier=float(row["mov_multiplier"]),
                shift=float(row["shift"]),
                rating_after=float(row["rating_after"]),
                week=int(row["week"]) if row["week"] is not None else None,
                season_type=str(row["season_type"]),
                start_date=str(row["start_date"]) if row["start_date"] is not None else None,
                opponent_name=str(row["opponent_name"]),
            )
        )

    return EloLedger(
        starting_rating=float(config["starting_rating"]),
        k=float(config["k"]),
        hfa=float(config["hfa"]),
        scale=float(config["scale"]),
        mov_scale=float(config["mov_scale"]),
        mov_autocorr=float(config["mov_autocorr"]),
        mov_denom_floor_fraction=float(config["mov_denom_floor_fraction"]),
        steps=steps,
    )


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


def _team_games(conn: sqlite3.Connection, year: int, team_id: int, sport: str) -> list[sqlite3.Row]:
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

    # Issue #294: where THIS TEAM played, the same vocabulary as
    # `EloGameStep.venue` -- not `games.venue`, which is the stadium name.
    # Neutral wins over home/away: a neutral-site game is "neutral" for both
    # sides, which is also what keeps `OpponentResult`'s venue/neutral_site
    # invariant true from either perspective. The derivation is total --
    # `games.neutral_site` is NOT NULL DEFAULT 0 and both team id columns are
    # NOT NULL (db/schema.sql) -- so there is no unknown case.
    neutral_site = bool(game["neutral_site"])
    venue: Literal["home", "away", "neutral"] = (
        "neutral" if neutral_site else "home" if is_home else "away"
    )

    return OpponentResult(
        game_id=int(game["id"]),
        opponent_team_id=int(opponent_id),
        opponent_name=opponent_name,
        opponent_rank=int(opp_rating_row["rank"]) if opp_rating_row is not None else None,
        opponent_rating=float(opp_rating_row["rating"]) if opp_rating_row is not None else None,
        result=result,
        team_score=int(team_score),
        opponent_score=int(opp_score),
        week=int(game["week"]) if game["week"] is not None else None,
        season_type=game["season_type"],
        venue=venue,
        neutral_site=neutral_site,
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
    elo_ledger = _elo_ledger(conn, year, method, team_id, sport)

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
        elo_ledger=elo_ledger,
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
        elo_ledger=case.elo_ledger,
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
        SELECT id, week, season_type, neutral_site, home_team_id, away_team_id,
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
                    game_id=int(g["id"]),
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
    # each other), with EVERY meeting each side had against that opponent
    # (issue #130). `TeamCase.games` is already chronological (regular season
    # by week, then postseason -- `_team_games`' ORDER BY), so appending per
    # opponent id in that order keeps each list chronological. Before #130
    # this was a dict overwrite that kept only the last meeting per side.
    a_by_opp = _meetings_by_opponent(case_a.games)
    b_by_opp = _meetings_by_opponent(case_b.games)
    common_ids = (set(a_by_opp) & set(b_by_opp)) - {case_a.team_id, case_b.team_id}

    common_opponents: list[CommonOpponent] = []
    for opp_id in common_ids:
        # Name and rank come from the first meeting; every meeting against the
        # same opponent id shares them (both are read from the opponent's own
        # `teams`/`ratings` rows, not the game).
        first = next(o for o in case_a.games if o.opponent_team_id == opp_id)
        common_opponents.append(
            CommonOpponent(
                opponent_team_id=opp_id,
                opponent_name=first.opponent_name,
                opponent_rank=first.opponent_rank,
                team_a_meetings=a_by_opp[opp_id],
                team_b_meetings=b_by_opp[opp_id],
            )
        )
    common_opponents.sort(key=lambda c: (c.opponent_rank is None, c.opponent_rank or 0))

    rating_diff = case_a.rating - case_b.rating

    verdict = _build_verdict(case_a, case_b, meetings, common_opponents, rating_diff)

    return ComparisonResult(
        year=year,
        # `method: str` on this signature is narrowed to `Method` by #139; until then, cast.
        method=cast(Method, method),
        team_a=_case_summary(case_a),
        team_b=_case_summary(case_b),
        head_to_head=head_to_head,
        common_opponents=common_opponents,
        rating_diff=rating_diff,
        verdict=verdict,
    )


def _meetings_by_opponent(
    games: list[OpponentResult],
) -> dict[int, list[CommonOpponentMeeting]]:
    """Every meeting per opponent id, in the order `games` lists them.

    Each `OpponentResult` is already team-relative, so the meeting is a
    straight projection: no re-deriving which side the team was on.
    """
    by_opp: dict[int, list[CommonOpponentMeeting]] = {}
    for g in games:
        by_opp.setdefault(g.opponent_team_id, []).append(
            CommonOpponentMeeting(
                game_id=g.game_id,
                result=g.result,
                team_score=g.team_score,
                opponent_score=g.opponent_score,
                week=g.week,
                season_type=g.season_type,
                venue=g.venue,
            )
        )
    return by_opp


def _describe_meeting(m: CommonOpponentMeeting) -> str:
    """One meeting as the verdict states it: "L 31-44 (week 8)".

    The score pair is team-perspective (team_score-opponent_score), the order
    apps/api's persona grounding check accepts against the fact block. A
    postseason meeting is labelled by its season type so it can't be read as
    a regular-season week of the same number.
    """
    if m.season_type == "regular":
        when = f"week {m.week}"
    elif m.week is None:
        when = m.season_type
    else:
        when = f"{m.season_type} week {m.week}"
    return f"{m.result} {m.team_score}-{m.opponent_score} ({when})"


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
            # A decided meeting's winner scored more, so its points are the
            # larger of the two whoever was home (#122). Derived from the
            # scores, not from neutral_site or home/away order.
            winner_points = max(m.home_points, m.away_points)
            loser_points = min(m.home_points, m.away_points)
            if m.winner == case_a.team_name:
                parts.append(
                    f"{case_a.team_name} beat {case_b.team_name} head-to-head "
                    f"{winner_points}-{loser_points} "
                    f"({m.home_team} vs {m.away_team}, week {m.week})."
                )
            elif m.winner == case_b.team_name:
                parts.append(
                    f"{case_b.team_name} beat {case_a.team_name} head-to-head "
                    f"{winner_points}-{loser_points} "
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
            # Every meeting per side (issue #130), so a division opponent met
            # twice no longer reads as a single result.
            a_went = ", ".join(_describe_meeting(m) for m in c.team_a_meetings)
            b_went = ", ".join(_describe_meeting(m) for m in c.team_b_meetings)
            parts.append(
                f"vs common opponent {c.opponent_name} "
                f"(rank {c.opponent_rank}): {case_a.team_name} went {a_went}; "
                f"{case_b.team_name} went {b_went}."
            )

    leader = case_a.team_name if rating_diff > 0 else case_b.team_name if rating_diff < 0 else None
    if leader:
        printed_a = format(case_a.rating, rating_format)
        printed_b = format(case_b.rating, rating_format)
        # Issue #149: the leader is decided by the exact `rating_diff`, but
        # the reader only sees the printed numbers. When those print
        # identically at this method's precision, naming a leader beside two
        # equal numbers reads as a contradiction, so the clause hedges. The
        # test is the two formatted strings, never a float epsilon, so it
        # tracks VERDICT_RATING_FORMATS exactly.
        hedge = "a hair " if printed_a == printed_b else ""
        parts.append(
            f"{leader} rates {hedge}higher overall "
            f"({printed_a} vs {printed_b}, "
            f"rank {case_a.rank} vs {case_b.rank})."
        )
    else:
        parts.append("Ratings are effectively tied.")

    return " ".join(parts)
