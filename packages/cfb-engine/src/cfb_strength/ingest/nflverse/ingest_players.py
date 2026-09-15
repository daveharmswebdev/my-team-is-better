"""NFL player-stats ingest (issue #289, epic #288): the projected nflverse
weekly stat lines and `players.csv`, cache-first, into the `players`,
`player_source_ids`, `game_starters`, `player_game_stats` and
`player_season_stats` tables.

    uv run python -m cfb_strength.ingest.nflverse.ingest_players --years 1999-2025

Flags:
    --years YEARS   Required. Same syntax and 1999-2025 window as
                    `ingest_season` (its `parse_years`, `MIN_YEAR`, `MAX_YEAR`).
    --force         Refetch `players.csv` and each season's weekly file live
                    and rewrite their projected cache files. `teams.csv` is
                    the games ingest's cache and is never refetched here.
    --db-path       Override the sqlite db path.

Requires each season's games in the db already (run `ingest_season` first):
games carry the ids, scores, season types and listed QBs this joins to, and
a season with none raises. The rules live in `player_normalize.py`'s
docstring and the cache projection in `client.py`'s.

Idempotent: a season deletes its own starter, game-stat and nflverse
season-stat rows and writes them again in one transaction, upserts its
players and replaces their source ids, then removes NFL players no row
references any more. Re-running a season leaves every table identical.

Returns 0 when every requested season ingested; 1 when no valid years were
requested or any season raised (each season's error is printed, and the
others still run).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import astuple, dataclass
from pathlib import Path

from cfb_strength.config import DB_PATH, RAW_DIR
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.nflverse.client import (
    NflverseClientError,
    get_players,
    get_stats_player_week,
    get_teams,
)
from cfb_strength.ingest.nflverse.ingest_season import MAX_YEAR, MIN_YEAR, parse_years
from cfb_strength.ingest.nflverse.player_normalize import (
    SEASON_ROW_SOURCE,
    STAT_FIELDS,
    GameInfo,
    PlayerSeasonReport,
    RosterEntry,
    SeasonBuild,
    build_franchise_lookup,
    build_player_season,
    build_roster,
    game_info,
)


@dataclass(frozen=True)
class PlayerIngestReport:
    seasons: tuple[PlayerSeasonReport, ...]
    fetched_live: bool


@dataclass(frozen=True)
class _SharedInputs:
    franchise: dict[str, str]
    roster: dict[str, RosterEntry]
    fetched_live: bool


def load_season_games(conn: sqlite3.Connection, year: int) -> list[GameInfo]:
    rows = conn.execute(
        """
        SELECT id, source_id, season_type, home_team_id, away_team_id,
               home_points, away_points, raw_json
        FROM games WHERE sport = 'nfl' AND season = ?
        ORDER BY source_id
        """,
        (year,),
    ).fetchall()
    if not rows:
        raise ValueError(
            f"season {year} has no nfl games in the db; ingest them first "
            f"(cfb_strength.ingest.nflverse.ingest_season --years {year})"
        )
    return [game_info(dict(row)) for row in rows]


_STAT_COLUMNS = ", ".join(STAT_FIELDS)
_STAT_PARAMS = ", ".join(f":{name}" for name in STAT_FIELDS)


def _check_gsis_ids_against_db(conn: sqlite3.Connection, build: SeasonBuild) -> None:
    """A minted player id already held by a different gsis id is a
    collision across seasons; `build_player_season` checks within one."""
    for row in build.source_ids:
        if row.source != "gsis":
            continue
        existing = conn.execute(
            "SELECT source_id FROM player_source_ids WHERE player_id = ? AND source = 'gsis'",
            (row.player_id,),
        ).fetchone()
        if existing is not None and existing[0] != row.source_id:
            raise ValueError(
                f"surrogate id collision: player id {row.player_id} is gsis "
                f"{existing[0]!r} in the db and {row.source_id!r} in this season"
            )


def _write_season(conn: sqlite3.Connection, year: int, build: SeasonBuild) -> None:
    season_games = "SELECT id FROM games WHERE sport = 'nfl' AND season = ?"
    conn.execute(f"DELETE FROM game_starters WHERE game_id IN ({season_games})", (year,))
    conn.execute(f"DELETE FROM player_game_stats WHERE game_id IN ({season_games})", (year,))
    conn.execute(
        "DELETE FROM player_season_stats WHERE sport = 'nfl' AND season = ? AND source = ?",
        (year, SEASON_ROW_SOURCE),
    )

    conn.executemany(
        """
        INSERT INTO players (id, sport, display_name, position, birth_date)
        VALUES (:id, :sport, :display_name, :position, :birth_date)
        ON CONFLICT(id) DO UPDATE SET
            sport = excluded.sport,
            display_name = excluded.display_name,
            position = excluded.position,
            birth_date = excluded.birth_date
        """,
        [
            {
                "id": p.id,
                "sport": p.sport,
                "display_name": p.display_name,
                "position": p.position,
                "birth_date": p.birth_date,
            }
            for p in build.players
        ],
    )
    conn.executemany(
        "DELETE FROM player_source_ids WHERE player_id = ?", [(p.id,) for p in build.players]
    )
    conn.executemany(
        "INSERT INTO player_source_ids (player_id, source, source_id) VALUES (?, ?, ?)",
        [(s.player_id, s.source, s.source_id) for s in build.source_ids],
    )

    conn.executemany(
        f"""
        INSERT INTO player_game_stats (player_id, game_id, team_id, sport, {_STAT_COLUMNS})
        VALUES (:player_id, :game_id, :team_id, :sport, {_STAT_PARAMS})
        """,
        [
            {
                "player_id": r.player_id,
                "game_id": r.game_id,
                "team_id": r.team_id,
                "sport": r.sport,
                **dict(zip(STAT_FIELDS, astuple(r.stats), strict=True)),
            }
            for r in build.game_stats
        ],
    )
    conn.executemany(
        f"""
        INSERT INTO player_season_stats (
            player_id, season, season_type, team_id, games, source, sport, {_STAT_COLUMNS}
        ) VALUES (
            :player_id, :season, :season_type, :team_id, :games, :source, :sport, {_STAT_PARAMS}
        )
        """,
        [
            {
                "player_id": r.player_id,
                "season": r.season,
                "season_type": r.season_type,
                "team_id": r.team_id,
                "games": r.games,
                "source": r.source,
                "sport": r.sport,
                **dict(zip(STAT_FIELDS, astuple(r.stats), strict=True)),
            }
            for r in build.season_stats
        ],
    )
    conn.executemany(
        """
        INSERT INTO game_starters (game_id, team_id, position, player_id, sport, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (s.game_id, s.team_id, s.position, s.player_id, s.sport, s.source)
            for s in build.starters
        ],
    )

    unreferenced = """
        sport = 'nfl'
        AND id NOT IN (SELECT player_id FROM player_game_stats)
        AND id NOT IN (SELECT player_id FROM game_starters)
        AND id NOT IN (SELECT player_id FROM player_season_stats)
        AND id NOT IN (SELECT player_id FROM player_game_feats)
    """
    conn.execute(
        "DELETE FROM player_source_ids "
        f"WHERE player_id IN (SELECT id FROM players WHERE {unreferenced})"
    )
    conn.execute(f"DELETE FROM players WHERE {unreferenced}")


def _load_shared_inputs(*, force: bool, raw_dir: Path) -> _SharedInputs:
    teams_raw, teams_live = get_teams(raw_dir=raw_dir)
    players_raw, players_live = get_players(force=force, raw_dir=raw_dir)
    return _SharedInputs(
        franchise=build_franchise_lookup(teams_raw),
        roster=build_roster(players_raw),
        fetched_live=teams_live or players_live,
    )


def _ingest_year(
    conn: sqlite3.Connection, year: int, shared: _SharedInputs, *, force: bool, raw_dir: Path
) -> tuple[PlayerSeasonReport, bool]:
    # Games first: a season with no games raises before any fetch.
    games = load_season_games(conn, year)
    stat_rows, fetched_live = get_stats_player_week(year, force=force, raw_dir=raw_dir)
    build = build_player_season(year, stat_rows, games, shared.franchise, shared.roster)
    try:
        _check_gsis_ids_against_db(conn, build)
        _write_season(conn, year, build)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return build.report, fetched_live


def ingest_players(
    conn: sqlite3.Connection,
    years: Sequence[int],
    *,
    force: bool = False,
    raw_dir: Path = RAW_DIR,
) -> PlayerIngestReport:
    """Ingest each season in `years`, in order. Raises on the first season
    that fails; seasons before it stay written."""
    shared = _load_shared_inputs(force=force, raw_dir=raw_dir)
    reports: list[PlayerSeasonReport] = []
    fetched_live = shared.fetched_live
    for year in years:
        report, live = _ingest_year(conn, year, shared, force=force, raw_dir=raw_dir)
        reports.append(report)
        fetched_live = fetched_live or live
    return PlayerIngestReport(seasons=tuple(reports), fetched_live=fetched_live)


def format_season_report(report: PlayerSeasonReport) -> str:
    starters = " ".join(f"{source}={n}" for source, n in report.starters_by_source.items())
    lines = [
        f"{report.season}: stat_lines={report.stat_lines} season_rows={report.season_rows} "
        f"players={report.players_written} "
        f"without_players_csv={len(report.players_without_roster_entry)} "
        f"starters: {starters}"
    ]
    if report.players_without_roster_entry:
        lines.append(f"  not in players.csv: {', '.join(report.players_without_roster_entry)}")
    for s in report.skipped:
        lines.append(f"  skipped ({s.reason}): {s.game_id} {s.player_id or '-'} {s.player_name}")
    lines.append(
        "  games with no stat lines: " + (", ".join(report.games_without_stat_lines) or "none")
    )
    lines.append(
        "  sides without a starter: "
        + (", ".join(f"{g} {side}" for g, side in report.sides_without_starter) or "none")
    )
    for d in report.derived_starters:
        lines.append(
            f"  starter repaired: {d.game_id} {d.side} listed {d.listed_player_id} "
            f"{d.listed_player_name} -> {d.starter_player_id} {d.starter_player_name} "
            f"({d.attempts} att)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-players-nflverse",
        description="Ingest nflverse NFL player stats and starters into the project sqlite db.",
    )
    parser.add_argument(
        "--years",
        required=True,
        help='Years to ingest: "2024", "1999-2025", "2023,2024", or a mix.',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch players.csv and the weekly stat files live and rewrite their cache.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the sqlite db path (defaults to config.DB_PATH).",
    )
    args = parser.parse_args(argv)

    try:
        requested = parse_years(args.years)
    except ValueError as e:
        print(f"error: could not parse --years {args.years!r}: {e}", file=sys.stderr)
        return 1
    years = [y for y in requested if MIN_YEAR <= y <= MAX_YEAR]
    outside = [y for y in requested if y not in years]
    if outside:
        print(f"warning: skipping years outside {MIN_YEAR}-{MAX_YEAR}: {outside}", file=sys.stderr)
    if not years:
        print(f"error: no valid years to ingest in {MIN_YEAR}-{MAX_YEAR}", file=sys.stderr)
        return 1

    db_path = Path(args.db_path) if args.db_path else DB_PATH
    conn = get_conn(db_path)
    errors: list[str] = []
    ingested = 0
    try:
        ensure_schema(conn)
        try:
            shared = _load_shared_inputs(force=args.force, raw_dir=RAW_DIR)
        except (NflverseClientError, ValueError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        fetched_live = shared.fetched_live
        for year in years:
            try:
                report, live = _ingest_year(conn, year, shared, force=args.force, raw_dir=RAW_DIR)
            except (NflverseClientError, ValueError, KeyError, sqlite3.Error) as e:
                errors.append(f"{year}: {e}")
                print(f"error: {year}: {e}", file=sys.stderr)
                continue
            ingested += 1
            fetched_live = fetched_live or live
            print(format_season_report(report))
    finally:
        conn.close()

    print(f"\nlive fetches this run: {'yes' if fetched_live else 'no (cache hit)'}")
    if errors:
        print(f"\n{len(errors)} season(s) failed to ingest:", file=sys.stderr)
        for msg in errors:
            print(f"  - {msg}", file=sys.stderr)
        return 1
    return 0 if ingested else 1


if __name__ == "__main__":
    raise SystemExit(main())
