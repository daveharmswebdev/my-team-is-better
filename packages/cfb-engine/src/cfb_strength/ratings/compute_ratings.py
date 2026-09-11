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


def _load_games(conn: sqlite3.Connection, year: int) -> list[Game]:
    rows = conn.execute(
        """
        SELECT home_team_id, away_team_id, home_points, away_points, neutral_site
        FROM games
        WHERE season = ?
          AND completed = 1
          AND home_points IS NOT NULL
          AND away_points IS NOT NULL
        """,
        (year,),
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


def _fbs_team_ids(conn: sqlite3.Connection, year: int) -> set[int]:
    rows = conn.execute(
        """
        SELECT team_id FROM team_season
        WHERE year = ? AND lower(classification) = 'fbs'
        """,
        (year,),
    ).fetchall()
    return {row["team_id"] for row in rows}


def _rerank_fbs_only(
    ratings: dict[int, TeamRating], fbs_team_ids: set[int]
) -> list[TeamRating]:
    """Filter to FBS teams and re-rank 1..K by rating descending.

    If `fbs_team_ids` is empty (e.g. `team_season` has no rows yet for this
    year), falls back to keeping every team from `ratings` rather than
    silently writing zero rows -- an empty classification table is a data
    gap, not a signal that no team is FBS.
    """
    candidates = (
        [tr for tid, tr in ratings.items() if tid in fbs_team_ids]
        if fbs_team_ids
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
    conn: sqlite3.Connection, year: int, method: str, ratings: list[TeamRating]
) -> None:
    computed_at = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute("DELETE FROM ratings WHERE year = ? AND method = ?", (year, method))
        conn.executemany(
            """
            INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (year, method, tr.team_id, tr.rating, tr.rank, tr.wins, tr.losses, computed_at)
                for tr in ratings
            ],
        )


def _store_breakdowns(
    conn: sqlite3.Connection, year: int, method: str, ratings: list[TeamRating]
) -> None:
    """Delete-then-insert one row per `OpponentCredit` entry, plus one
    `opponent_team_id IS NULL` residual row, per displayed team -- same
    pattern as `_store()`, scoped by year+method."""
    computed_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[int, str, int, int | None, int | None, int | None, int | None, float | None, float, str]] = []
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
            )
        )

    with conn:
        conn.execute(
            "DELETE FROM rating_breakdowns WHERE year = ? AND method = ?", (year, method)
        )
        conn.executemany(
            """
            INSERT INTO rating_breakdowns (
                year, method, team_id, opponent_team_id, games_played, wins, losses,
                credit, contribution, computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def compute_and_store(conn: sqlite3.Connection, year: int, method: str) -> int:
    """Compute ratings for one year/method and store them. Returns the
    number of FBS rows written."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; available: {sorted(METHODS)}")

    # Idempotent (every statement in schema.sql is CREATE TABLE/INDEX IF NOT
    # EXISTS) -- guarantees `rating_breakdowns` exists even for a connection
    # handed in directly (bypassing `main()`'s own ensure_schema call), e.g.
    # a pre-built fixture db copied from before this table existed.
    ensure_schema(conn)

    games = _load_games(conn, year)
    if not games:
        _store(conn, year, method, [])
        _store_breakdowns(conn, year, method, [])
        return 0

    full_ratings = METHODS[method].rate(games)
    fbs_ids = _fbs_team_ids(conn, year)
    display_ratings = _rerank_fbs_only(full_ratings, fbs_ids)
    _store(conn, year, method, display_ratings)
    _store_breakdowns(conn, year, method, display_ratings)
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
            count = compute_and_store(conn, year, args.method)
            print(f"{year} [{args.method}]: wrote {count} FBS team ratings")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
