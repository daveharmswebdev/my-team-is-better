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
from datetime import datetime, timezone

from cfb_strength.contracts import Game, RatingMethod, TeamRating
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.keener import KeenerRating

METHODS: dict[str, RatingMethod] = {
    "keener": KeenerRating(),
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


def _load_games(conn: sqlite3.Connection, year: int, sport: str) -> list[Game]:
    """Load one year's completed games for a single `sport`.

    `sport` must be filtered here, not left implicit: CFB and NFL games for
    an overlapping season (e.g. 2023) live in the same `games` table (#51),
    so an unfiltered query would silently merge two sports' games into one
    win-graph.
    """
    rows = conn.execute(
        """
        SELECT home_team_id, away_team_id, home_points, away_points, neutral_site
        FROM games
        WHERE season = ?
          AND sport = ?
          AND completed = 1
          AND home_points IS NOT NULL
          AND away_points IS NOT NULL
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
            rating_breakdown=tr.rating_breakdown,
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
    computed_at = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "DELETE FROM ratings WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
        conn.executemany(
            """
            INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, computed_at, sport)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    computed_at = datetime.now(timezone.utc).isoformat()
    rows: list[
        tuple[
            int, str, int, int | None, int | None, int | None, int | None,
            float | None, float, str, str,
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


def compute_and_store(
    conn: sqlite3.Connection, year: int, method: str, sport: str = "cfb"
) -> int:
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

    games = _load_games(conn, year, sport)
    if not games:
        _store(conn, year, method, [], sport)
        _store_breakdowns(conn, year, method, [], sport)
        return 0

    full_ratings = METHODS[method].rate(games)

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
        choices=("cfb", "nfl"),
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
