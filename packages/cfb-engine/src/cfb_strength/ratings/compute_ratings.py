"""Compute-and-store entry point: read games for one or more seasons from the
database, run a `RatingMethod` over them, and write the resulting
`TeamRating`s to the `ratings` table.

Storage strategy: delete-then-insert per (year, method). This is simpler and
safer than an upsert here because a full recompute always produces a
complete, self-consistent rank ordering for the year -- there is no partial-
update scenario where keeping stale rows around is useful (a rank number is
only meaningful relative to the rest of that year+method's rows). Everything
runs inside one transaction per year so a failure partway through a year
does not leave that year's `ratings` rows half-deleted / half-written.

FBS-only display ranks vs. full win-graph
--------------------------------------------
`RatingMethod.rate()` is handed every team that appears in any game for the
year -- FBS and non-FBS alike -- because a game against a weak non-FBS
opponent still needs to be credited correctly inside the win-graph (see
`keener.py`). But the `ratings` table is a *displayed* ranking, and ranking
an FCS team #1 because it curb-stomped three FCS cupcakes is not a useful
answer to "who is the best team in FBS." So after `rate()` returns, this
module filters down to teams whose `team_season.classification` for that
year is FBS, and *re-ranks that filtered subset* (1..K) before writing rows
-- the stored `rank` column is always "rank among FBS teams that season,"
never the raw rank among the full win-graph. Rating values themselves are
left untouched (they still reflect the full win-graph, including
credit/blame from non-FBS opponents).
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import get_args

from cfb_strength.contracts import (
    CareerRatingMethod,
    Game,
    RatingMethod,
    Sport,
    TeamRating,
)
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.elo import ELO_CONFIGS, EloCareerRating, EloRating
from cfb_strength.ratings.franchise_lineage import FRANCHISE_LINEAGE
from cfb_strength.ratings.keener import KeenerRating

MethodFactory = Callable[[sqlite3.Connection, str], "RatingMethod | CareerRatingMethod"]

METHODS: dict[str, MethodFactory] = {
    "keener": lambda conn, sport: KeenerRating(),
    "elo": lambda conn, sport: EloRating(ELO_CONFIGS[sport]),
    "elo_career": lambda conn, sport: EloCareerRating(
        ELO_CONFIGS[sport], _franchise_successors(conn, sport)
    ),
}
"""Registered rating methods, as *factories* rather than shared instances.

Three reasons it has to be a factory:

1. **Per-sport tuning.** `EloRating` is constructed with an `EloConfig`, so
   there is no one instance that is correct for both cfb and nfl -- hence
   the `sport` argument. (`ELO_CONFIGS[sport]` raises a `ValueError` naming
   the registered sports for anything else; it never falls back to a
   default, because rating NFL games at CFB's k/hfa would be
   wrong-but-plausible, the worst failure mode.)
2. **The lineage lookup.** `EloCareerRating` needs franchise relocations
   resolved from the `teams` table, which needs a live connection -- hence
   the `conn` argument. Resolving it here rather than inside `elo.py` keeps
   the ratings algorithm a pure function of its inputs, with no db import
   (enforced by `.importlinter`).
3. **No state can leak between years.** A fresh instance per call is a real
   safety property now that one registered method is stateful across
   seasons: a module-level singleton that accumulated ratings would make
   `compute-ratings --years 2000-2023` depend on how many years preceded
   the one being written.

`choices=sorted(METHODS)` in `main()` and the `if method not in METHODS`
guard in `compute_and_store` both read only `.keys()`, so both work
unchanged against factories.
"""


def _franchise_successors(conn: sqlite3.Connection, sport: str) -> dict[int, int]:
    """Resolve `FRANCHISE_LINEAGE`'s source-id pairs into local team ids.

    `franchise_lineage.py` is keyed on `teams.source_id` (nflverse's
    abbreviation) because our ingest mints a *different* surrogate
    `teams.id` for "STL" and "LA" even though they are one continuous
    franchise. This is the only place that translation happens, so
    `ratings/elo.py` never touches the database.

    A pair whose abbreviations are not *both* present in `teams` is skipped
    silently: a fixture or a partial backfill covering only 2020+ has no
    `OAK` row at all, and that is a legitimate database, not an error.

    Returns `{}` for cfb without querying: `FRANCHISE_LINEAGE["cfb"]` is
    empty, and CFB `teams` rows carry `source_id IS NULL`, which
    `IN (...)` never matches anyway.
    """
    lineage = FRANCHISE_LINEAGE.get(sport, {})
    if not lineage:
        return {}

    abbreviations = sorted({a for pair in lineage.items() for a in pair})
    placeholders = ",".join("?" * len(abbreviations))
    rows = conn.execute(
        f"SELECT id, source_id FROM teams WHERE sport = ? AND source_id IN ({placeholders})",
        (sport, *abbreviations),
    ).fetchall()
    team_id_by_abbreviation = {row["source_id"]: row["id"] for row in rows}

    return {
        team_id_by_abbreviation[predecessor]: team_id_by_abbreviation[successor]
        for predecessor, successor in lineage.items()
        if predecessor in team_id_by_abbreviation and successor in team_id_by_abbreviation
    }


def _parse_years(spec: str) -> list[int]:
    """Parse '2005' or '2000-2023' (inclusive) into a list of years."""
    spec = spec.strip()
    if "-" in spec:
        start_s, _, end_s = spec.partition("-")
        start, end = int(start_s), int(end_s)
        if end < start:
            raise ValueError(f"invalid year range {spec!r}: end before start")
        return list(range(start, end + 1))
    return [int(spec)]


def _load_games(
    conn: sqlite3.Connection, year: int, sport: str, history: bool = False
) -> list[Game]:
    """Load completed games for a single `sport`, in chronological order.

    `history=False` (the default) loads `season = year`. `history=True`
    loads `season <= year` -- every season up to and including the target
    one -- which is what a `CareerRatingMethod` needs. Note `<=`, not
    `<`: the target season's own games are part of the replay.

    `sport` must be filtered here, not left implicit: CFB and NFL games for
    an overlapping season (e.g. 2023) live in the same `games` table (#51),
    so an unfiltered query would silently merge two sports' games into one
    win-graph.

    The ordering
    ------------
    This query had no `ORDER BY` at all before the Elo engine, because
    Keener is order-invariant by construction (it accumulates a credit
    matrix, then solves for its dominant eigenvector). A sequential method
    cannot be computed without an order, and -- more importantly -- cannot
    be *reproduced* without a **total** one. Every term below earns its
    place:

    ``season``
        Ascending, so a history load replays oldest-first.
    ``CASE season_type WHEN 'regular' THEN 0 ELSE 1 END``
        Regular season before postseason. Sorting `season_type`
        alphabetically would put 'postseason' first.
    ``week IS NULL, week`` / ``start_date IS NULL, start_date``
        The `x IS NULL` terms are deliberate and must stay. Both columns
        are nullable, and SQLite sorts NULLs **first** in an ASC sort --
        which would place an undated bowl game ahead of that same
        postseason's week-1 games. These terms push unknowns last, the more
        chronologically plausible reading of "we don't know when this
        happened."
    ``id``
        `games.id` is an INTEGER PRIMARY KEY: never null, always unique. It
        leaves no ties for the query planner to break arbitrarily, which is
        what makes this a genuine total order and therefore reproducible
        across runs, machines and SQLite versions. That reproducibility is
        the property Elo actually requires; "roughly chronological" is not
        enough.

    This deliberately diverges from `evidence/proof.py`'s two-key *display*
    ordering. That one only has to look right in a table; this one has to
    produce the same ratings every time it runs.
    """
    season_predicate = "season <= ?" if history else "season = ?"
    rows = conn.execute(
        f"""
        SELECT id, season, week, season_type, start_date,
               home_team_id, away_team_id, home_points, away_points, neutral_site
        FROM games
        WHERE {season_predicate}
          AND sport = ?
          AND completed = 1
          AND home_points IS NOT NULL
          AND away_points IS NOT NULL
        ORDER BY season,
                 CASE season_type WHEN 'regular' THEN 0 ELSE 1 END,
                 week IS NULL, week,
                 start_date IS NULL, start_date,
                 id
        """,
        (year, sport),
    ).fetchall()
    return [
        Game(
            home_team_id=row["home_team_id"],
            away_team_id=row["away_team_id"],
            home_points=row["home_points"],
            away_points=row["away_points"],
            neutral_site=bool(row["neutral_site"]),
            season=row["season"],
            week=row["week"],
            season_type=row["season_type"],
            start_date=row["start_date"],
        )
        for row in rows
    ]


def _fbs_team_ids(conn: sqlite3.Connection, year: int, sport: str) -> set[int]:
    rows = conn.execute(
        """
        SELECT team_id FROM team_season
        WHERE year = ? AND sport = ? AND lower(classification) = 'fbs'
        """,
        (year, sport),
    ).fetchall()
    return {row["team_id"] for row in rows}


def _rerank_for_display(
    ratings: dict[int, TeamRating], display_team_ids: set[int] | None
) -> list[TeamRating]:
    """Filter to `display_team_ids` and re-rank 1..K by rating descending.

    `display_team_ids=None` means "no classification-based restriction
    applies" -- every team in `ratings` is displayed. This is the explicit
    branch for sports with no FBS/FCS-style split (e.g. NFL: every team
    that appears in the win-graph should be ranked/displayed), rather than
    relying on `_fbs_team_ids` incidentally returning an empty set for a
    sport whose `team_season` rows have no 'fbs' classification value.

    If `display_team_ids` is an empty *set* (as opposed to `None`) -- e.g.
    cfb's `team_season` has no rows yet for this year -- this still falls
    back to keeping every team from `ratings` rather than silently writing
    zero rows: an empty classification table is a data gap, not a signal
    that no team is FBS.
    """
    candidates = (
        [tr for tid, tr in ratings.items() if tid in display_team_ids]
        if display_team_ids
        else list(ratings.values())
    )
    candidates.sort(key=lambda tr: (-tr.rating, tr.team_id))
    return [
        TeamRating(
            team_id=tr.team_id,
            rating=tr.rating,
            rank=i + 1,
            wins=tr.wins,
            losses=tr.losses,
            ties=tr.ties,
            rating_breakdown=tr.rating_breakdown,
            elo_ledger=tr.elo_ledger,
        )
        for i, tr in enumerate(candidates)
    ]


def _store(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    ratings: list[TeamRating],
    sport: str,
) -> None:
    """Delete-then-insert, scoped by (year, method, sport).

    `sport` must be in both the DELETE and the INSERT: without it, recomputing
    one sport's ratings for a year would delete the other sport's rows for
    that same year too (both share the `ratings` table per #51), and every
    inserted row would silently take the `sport` column's schema default
    ('cfb') regardless of which sport was actually computed.
    """
    computed_at = datetime.now(UTC).isoformat()
    with conn:
        conn.execute(
            "DELETE FROM ratings WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
        conn.executemany(
            """
            INSERT INTO ratings (
                year, method, team_id, rating, rank, wins, losses, ties, computed_at, sport
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    year,
                    method,
                    tr.team_id,
                    tr.rating,
                    tr.rank,
                    tr.wins,
                    tr.losses,
                    tr.ties,
                    computed_at,
                    sport,
                )
                for tr in ratings
            ],
        )


def _store_breakdowns(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    ratings: list[TeamRating],
    sport: str,
) -> None:
    """Delete-then-insert one row per `OpponentCredit` entry, plus one
    `opponent_team_id IS NULL` residual row, per displayed team -- same
    pattern as `_store()`, scoped by year+method+sport (see `_store()`'s
    docstring for why `sport` must be in both the DELETE and the INSERT)."""
    computed_at = datetime.now(UTC).isoformat()
    rows: list[
        tuple[
            int,
            str,
            int,
            int | None,
            int | None,
            int | None,
            int | None,
            float | None,
            float,
            str,
            str,
        ]
    ] = []
    for tr in ratings:
        for entry in tr.rating_breakdown.entries:
            rows.append(
                (
                    year,
                    method,
                    tr.team_id,
                    entry.opponent_team_id,
                    entry.games_played,
                    entry.wins,
                    entry.losses,
                    entry.credit,
                    entry.contribution,
                    computed_at,
                    sport,
                )
            )
        # The `opponent_team_id IS NULL` residual row is emitted only when
        # this team actually has a decomposition. Previously it was
        # unconditional (outside the entries loop but inside the per-team
        # loop), which for a method with no per-opponent decomposition at
        # all -- Elo returns the default `RatingBreakdown()` -- would write
        # one junk `contribution=0.0` row per team per year per method,
        # asserting a breakdown that does not exist.
        #
        # This cannot perturb Keener's real rows: every team in Keener's
        # output played at least one game and so has at least one
        # `OpponentCredit`. The single behavior change is `keener.py`'s
        # `n == 1` early-return path, whose residual row was actually
        # *wrong* -- Keener returns `rating=1.0` there, so the stored row
        # asserted `1.0 == 0.0 + 0.0`, violating `RatingBreakdown`'s
        # documented invariant. Dropping it is a fix, and it is
        # unobservable through the only reader: `evidence/proof.py`
        # initializes `residual_contribution = 0.0` and only overwrites it
        # if a NULL-opponent row exists, so both states deserialize
        # identically.
        if tr.rating_breakdown.entries or tr.rating_breakdown.residual_contribution:
            rows.append(
                (
                    year,
                    method,
                    tr.team_id,
                    None,
                    None,
                    None,
                    None,
                    None,
                    tr.rating_breakdown.residual_contribution,
                    computed_at,
                    sport,
                )
            )

    with conn:
        conn.execute(
            "DELETE FROM rating_breakdowns WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
        conn.executemany(
            """
            INSERT INTO rating_breakdowns (
                year, method, team_id, opponent_team_id, games_played, wins, losses,
                credit, contribution, computed_at, sport
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _store_elo_ledgers(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    ratings: list[TeamRating],
    sport: str,
) -> None:
    """Delete-then-insert the Elo ledger (issue #183) for (year, method,
    sport): one `elo_ledger_steps` row per displayed team per game, and one
    `elo_ledger_configs` row holding the constants the walk ran with.

    The DELETE is unconditional, from both tables, even when no team has a
    ledger: re-running replaces, and a method that writes no ledger (keener,
    elo_career) leaves none behind for its own (year, method, sport). `sport`
    is in both statements for `_store()`'s reason.

    One config row can only describe ledgers that share their constants, so
    ledgers that disagree raise before anything is written rather than
    printing the wrong tuning beside some team's path. A single walk never
    produces that; the check is a guard, not a code path.
    """
    computed_at = datetime.now(UTC).isoformat()
    ledgers = [(tr.team_id, tr.elo_ledger) for tr in ratings if tr.elo_ledger is not None]

    config_row: tuple[int, str, str, float, float, float, float, float, float, str] | None
    config_row = None
    if ledgers:
        constants = {
            (
                ledger.starting_rating,
                ledger.k,
                ledger.hfa,
                ledger.scale,
                ledger.mov_scale,
                ledger.mov_autocorr,
            )
            for _, ledger in ledgers
        }
        if len(constants) != 1:
            raise ValueError(
                f"Elo ledgers for {year}/{method}/{sport} disagree on their "
                f"constants: {sorted(constants)}"
            )
        ((starting_rating, k, hfa, scale, mov_scale, mov_autocorr),) = constants
        config_row = (
            year,
            method,
            sport,
            starting_rating,
            k,
            hfa,
            scale,
            mov_scale,
            mov_autocorr,
            computed_at,
        )

    step_rows: list[
        tuple[
            int,
            str,
            str,
            int,
            int,
            int | None,
            str,
            str | None,
            int,
            str,
            int,
            int,
            str,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            str,
        ]
    ] = [
        (
            year,
            method,
            sport,
            team_id,
            step.game_number,
            step.week,
            step.season_type,
            step.start_date,
            step.opponent_team_id,
            step.venue,
            step.team_points,
            step.opponent_points,
            step.result,
            step.rating_before,
            step.opponent_rating_before,
            step.home_field_adjustment,
            step.rating_gap,
            step.win_expectancy,
            step.mov_multiplier,
            step.shift,
            step.rating_after,
            computed_at,
        )
        for team_id, ledger in ledgers
        for step in ledger.steps
    ]

    with conn:
        conn.execute(
            "DELETE FROM elo_ledger_steps WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
        conn.execute(
            "DELETE FROM elo_ledger_configs WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
        conn.executemany(
            """
            INSERT INTO elo_ledger_steps (
                year, method, sport, team_id, game_number, week, season_type,
                start_date, opponent_team_id, venue, team_points, opponent_points,
                result, rating_before, opponent_rating_before, home_field_adjustment,
                rating_gap, win_expectancy, mov_multiplier, shift, rating_after,
                computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            step_rows,
        )
        if config_row is not None:
            conn.execute(
                """
                INSERT INTO elo_ledger_configs (
                    year, method, sport, starting_rating, k, hfa, scale, mov_scale,
                    mov_autocorr, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                config_row,
            )


def compute_and_store(conn: sqlite3.Connection, year: int, method: str, sport: str = "cfb") -> int:
    """Compute ratings for one year/method/sport and store them. Returns the
    number of displayed rows written.

    `sport` defaults to "cfb" so every pre-existing call site (evidence/mcp
    integration tests, golden-dataset regressions) that predates #57 is
    unaffected and produces byte-for-byte identical CFB output.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; available: {sorted(METHODS)}")

    # Idempotent (every statement in schema.sql is CREATE TABLE/INDEX IF NOT
    # EXISTS) -- guarantees `rating_breakdowns` exists even for a connection
    # handed in directly (bypassing `main()`'s own ensure_schema call), e.g.
    # a pre-built fixture db copied from before this table existed.
    ensure_schema(conn)

    # A fresh instance per call -- see METHODS' docstring for why that is a
    # safety property, not a nicety.
    impl = METHODS[method](conn, sport)
    if isinstance(impl, CareerRatingMethod):
        # A career method's rating for `year` depends on every prior
        # season, so it is handed the full history and told which season it
        # is rating.
        games = _load_games(conn, year, sport, history=True)
        full_ratings = impl.rate_through(games, year) if games else {}
    else:
        games = _load_games(conn, year, sport)
        full_ratings = impl.rate(games) if games else {}

    # `if not full_ratings`, not `if not games`: the same predicate for
    # Keener (which returns {} only for an empty game list), and it
    # additionally covers a career method that loaded prior seasons but
    # found no game in the target year.
    if not full_ratings:
        _store(conn, year, method, [], sport)
        _store_breakdowns(conn, year, method, [], sport)
        _store_elo_ledgers(conn, year, method, [], sport)
        return 0

    if sport == "cfb":
        # FBS-only display ranks vs. full win-graph (see module docstring).
        display_team_ids = _fbs_team_ids(conn, year, sport)
    else:
        # No FBS/FCS-style classification split exists for other sports
        # (e.g. NFL has no `team_season.classification` concept -- #51
        # writes `classification=None` for every NFL row) -- every team
        # that appears in the win-graph is displayed. Explicit branch
        # rather than relying on `_fbs_team_ids` incidentally returning an
        # empty set for a sport with no 'fbs' classification value, which
        # would trip `_rerank_for_display`'s empty-set data-gap fallback
        # for the wrong reason.
        display_team_ids = None

    display_ratings = _rerank_for_display(full_ratings, display_team_ids)
    _store(conn, year, method, display_ratings, sport)
    _store_breakdowns(conn, year, method, display_ratings, sport)
    _store_elo_ledgers(conn, year, method, display_ratings, sport)
    return len(display_ratings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compute-ratings",
        description="Compute and store team ratings for one or more seasons.",
    )
    parser.add_argument(
        "--years",
        required=True,
        help="Year (e.g. 2005) or inclusive range (e.g. 2000-2023).",
    )
    parser.add_argument(
        "--method",
        default="keener",
        choices=sorted(METHODS),
        help="Rating method to use (default: keener).",
    )
    parser.add_argument(
        "--sport",
        default="cfb",
        choices=get_args(Sport),
        help="Sport to compute ratings for (default: cfb). Mirrors "
        "`ingest --sport`; scopes both the win-graph read and the "
        "ratings/rating_breakdowns write so cfb and nfl rows for the same "
        "year never collide or bleed into each other.",
    )
    args = parser.parse_args(argv)

    try:
        years = _parse_years(args.years)
    except ValueError as exc:
        print(f"error: {exc}", flush=True)
        return 2

    conn = get_conn()
    try:
        ensure_schema(conn)
        for year in years:
            count = compute_and_store(conn, year, args.method, args.sport)
            print(f"{year} [{args.method}/{args.sport}]: wrote {count} team ratings")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
