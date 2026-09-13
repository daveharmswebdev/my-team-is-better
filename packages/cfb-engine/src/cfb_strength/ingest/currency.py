"""`cfb doctor`: is this sqlite db's *data* current, not just its schema?
(issue #97, epic #113)

A stale machine-local `data/cfb.sqlite3` used to be indistinguishable from a
fresh one. A pre-#51 db is a complete-looking CFB ingest with no NFL rows and
no mascots, and `ensure_schema` migrates the missing *columns* into it, which
yields a current-schema db whose data is still stale. This module is the
check that tells the two apart. It reports, per league:

  a. `schema_not_current` -- a table, column or index `ensure_schema` would
     add is missing. Reported, never fixed.
  b. `league_has_no_games` -- a league in `contracts.Sport` with zero `games`
     rows.
  c. `season_behind_cache` -- a season present in the committed raw cache
     that the db's `games` lacks for that league.
  d. `season_missing_ratings` -- a season with games but no `ratings` rows
     for some method in `contracts.Method`.
  e. `no_cfb_mascots` -- zero CFB teams with a mascot although the CFBD
     `/teams` cache is committed (the #77 enrichment never ran).

plus `raw_cache_missing` when `--raw-dir` does not exist, so a typo'd path
fails loudly instead of silently skipping (c) and (e).

Guarantees:

* **Read-only.** The db is opened with `get_conn(path, read_only=True)` and
  is never handed to `ensure_schema`. The "what would `ensure_schema`
  produce?" reference for (a) comes from running `ensure_schema` against a
  throwaway in-memory db instead, so a column added to schema.sql or a new
  `_migrate_*` step is expected here automatically, with no second
  hand-maintained column list to drift.
* **Tolerant of old shapes.** Tables or columns a stale db lacks are read as
  the migration would backfill them. A pre-#51 `games` row with no `sport`
  column counts as CFB (the column's schema default), and a missing
  `teams.mascot` counts as NULL. So the report describes the data the db
  really holds rather than crashing on the schema gap (a).
* **Leagues and methods come from the contract aliases** (`get_args(Sport)`,
  `get_args(Method)`), never from a hand-written tuple.

"Present in the cache" (c) means a season the league's own ingest would write
from that cache: a season inside that ingest's `MIN_YEAR`..`MAX_YEAR`. This
matters because nflverse's whole-history `games.csv` already carries the
in-progress 2026 season, which `cfb ingest --sport nfl` deliberately skips.
Without the window, every correctly built db (including Render's) would be
reported as behind. For CFB, a season counts when either its regular or its
postseason cache file exists, using the CFBD client's own `cache_path`.

This lives in `ingest` because ingest owns the cache-path conventions. It may
import both the CFBD and nflverse ingest paths. The forbidden contracts in
`.importlinter` stop those two paths importing each other, and neither one
imports this module.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from cfb_strength.config import DB_PATH, RAW_DIR, SEASON_TYPES
from cfb_strength.contracts import Method, Sport
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest import ingest_season as cfbd_ingest
from cfb_strength.ingest.client import cache_path as cfbd_games_cache_path
from cfb_strength.ingest.client import teams_cache_path as cfbd_teams_cache_path
from cfb_strength.ingest.nflverse import ingest_season as nflverse_ingest
from cfb_strength.ingest.nflverse.client import games_cache_path as nflverse_games_cache_path

EXPECTED_SPORTS: tuple[Sport, ...] = get_args(Sport)
EXPECTED_METHODS: tuple[Method, ...] = get_args(Method)

ProblemCode = Literal[
    "schema_not_current",
    "raw_cache_missing",
    "league_has_no_games",
    "season_behind_cache",
    "season_missing_ratings",
    "no_cfb_mascots",
]


class DatabaseUnavailableError(RuntimeError):
    """The db path does not exist, or is not a readable sqlite database."""


@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    sport: Sport | None
    message: str
    seasons: tuple[int, ...] = ()


@dataclass(frozen=True)
class LeagueReport:
    sport: Sport
    game_seasons: tuple[int, ...]
    cached_seasons: tuple[int, ...]
    # method -> seasons with at least one ratings row, keyed in `Method` order.
    rated_seasons: Mapping[str, tuple[int, ...]]


@dataclass(frozen=True)
class AliasCoverage:
    teams: int
    with_mascot: int
    teams_cache_present: bool


@dataclass(frozen=True)
class CurrencyReport:
    db_path: Path
    raw_dir: Path
    missing_schema: tuple[str, ...]
    leagues: tuple[LeagueReport, ...]
    cfb_aliases: AliasCoverage
    problems: tuple[Problem, ...]

    @property
    def is_current(self) -> bool:
        return not self.problems


# ---------------------------------------------------------------------------
# committed raw cache: which seasons would each league's ingest write?
# ---------------------------------------------------------------------------


def _cfbd_cached_seasons(raw_dir: Path) -> frozenset[int]:
    return frozenset(
        year
        for year in range(cfbd_ingest.MIN_YEAR, cfbd_ingest.MAX_YEAR + 1)
        if any(cfbd_games_cache_path(year, st, raw_dir).exists() for st in SEASON_TYPES)
    )


def _nflverse_cached_seasons(raw_dir: Path) -> frozenset[int]:
    path = nflverse_games_cache_path(raw_dir)
    if not path.exists():
        return frozenset()
    with path.open(newline="") as f:
        seasons = {int(row["season"]) for row in csv.DictReader(f) if row.get("season")}
    return frozenset(
        s for s in seasons if nflverse_ingest.MIN_YEAR <= s <= nflverse_ingest.MAX_YEAR
    )


# One reader per league's cache layout. tests/test_db_currency.py fails if
# its keys and `Sport` disagree.
CACHED_SEASON_READERS: Mapping[str, Callable[[Path], frozenset[int]]] = {
    "cfb": _cfbd_cached_seasons,
    "nfl": _nflverse_cached_seasons,
}


# ---------------------------------------------------------------------------
# schema: the db's actual shape vs. what ensure_schema would produce
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Schema:
    # table -> column -> declared default (SQL text, e.g. "'cfb'"), or None
    columns: Mapping[str, Mapping[str, str | None]]
    indexes: frozenset[str]


def _read_schema(conn: sqlite3.Connection) -> _Schema:
    tables = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    columns = {
        table: {
            str(row[1]): (None if row[4] is None else str(row[4]))
            for row in conn.execute(f'PRAGMA table_info("{table}")')
        }
        for table in tables
    }
    indexes = frozenset(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    )
    return _Schema(columns=columns, indexes=indexes)


def _reference_schema() -> _Schema:
    """What `ensure_schema` produces, read off a throwaway in-memory db. The
    db under check is never passed to `ensure_schema` -- see the module
    docstring."""
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        ensure_schema(reference)
        return _read_schema(reference)
    finally:
        reference.close()


def _missing_schema(actual: _Schema, reference: _Schema) -> tuple[str, ...]:
    missing: list[str] = []
    for table, columns in reference.columns.items():
        if table not in actual.columns:
            missing.append(table)
            continue
        missing.extend(f"{table}.{column}" for column in columns if column not in actual.columns[table])
    missing.extend(sorted(reference.indexes - actual.indexes))
    return tuple(missing)


def _column_expr(actual: _Schema, reference: _Schema, table: str, column: str) -> str:
    """SQL for `column` as the migration would leave it: the column itself if
    the db has it, else its schema.sql default (NULL if it has none)."""
    if column in actual.columns.get(table, {}):
        return f'"{column}"'
    default = reference.columns.get(table, {}).get(column)
    return "NULL" if default is None else default


# ---------------------------------------------------------------------------
# per-league data
# ---------------------------------------------------------------------------


def _league_report(
    conn: sqlite3.Connection, actual: _Schema, reference: _Schema, sport: Sport, raw_dir: Path
) -> LeagueReport:
    game_seasons: tuple[int, ...] = ()
    if "games" in actual.columns:
        sport_expr = _column_expr(actual, reference, "games", "sport")
        game_seasons = tuple(
            int(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT season FROM games WHERE {sport_expr} = ? ORDER BY season",
                (sport,),
            )
        )

    rated_seasons: dict[str, tuple[int, ...]] = {}
    for method in EXPECTED_METHODS:
        if "ratings" not in actual.columns:
            rated_seasons[method] = ()
            continue
        sport_expr = _column_expr(actual, reference, "ratings", "sport")
        method_expr = _column_expr(actual, reference, "ratings", "method")
        rated_seasons[method] = tuple(
            int(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT year FROM ratings "
                f"WHERE {sport_expr} = ? AND {method_expr} = ? ORDER BY year",
                (sport, method),
            )
        )

    reader = CACHED_SEASON_READERS.get(sport)
    cached = reader(raw_dir) if reader is not None and raw_dir.is_dir() else frozenset()

    return LeagueReport(
        sport=sport,
        game_seasons=game_seasons,
        cached_seasons=tuple(sorted(cached)),
        rated_seasons=rated_seasons,
    )


def _cfb_alias_coverage(
    conn: sqlite3.Connection, actual: _Schema, reference: _Schema, raw_dir: Path
) -> AliasCoverage:
    cache_present = cfbd_teams_cache_path(raw_dir).exists()
    if "teams" not in actual.columns:
        return AliasCoverage(teams=0, with_mascot=0, teams_cache_present=cache_present)
    sport_expr = _column_expr(actual, reference, "teams", "sport")
    mascot_expr = _column_expr(actual, reference, "teams", "mascot")
    row = conn.execute(
        f"SELECT COUNT(*), COUNT({mascot_expr}) FROM teams WHERE {sport_expr} = ?", ("cfb",)
    ).fetchone()
    return AliasCoverage(
        teams=int(row[0]), with_mascot=int(row[1]), teams_cache_present=cache_present
    )


def format_seasons(seasons: tuple[int, ...] | list[int]) -> str:
    """`(1998, 1999, 2000, 2005)` -> `"1998-2000, 2005"`."""
    if not seasons:
        return "none"
    ordered = sorted(set(seasons))
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for season in ordered[1:]:
        if season == prev + 1:
            prev = season
            continue
        runs.append((start, prev))
        start = prev = season
    runs.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def _find_problems(
    missing_schema: tuple[str, ...],
    raw_dir: Path,
    leagues: tuple[LeagueReport, ...],
    aliases: AliasCoverage,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []

    if missing_schema:
        problems.append(
            Problem(
                "schema_not_current",
                None,
                "schema is behind what `ensure_schema` would produce; missing: "
                + ", ".join(missing_schema)
                + ". Not fixed here (the doctor is read-only). A db this old very likely "
                "holds data this old too, so rebuild it rather than migrating it.",
            )
        )

    if not raw_dir.is_dir():
        problems.append(
            Problem(
                "raw_cache_missing",
                None,
                f"raw cache directory {raw_dir} does not exist, so the behind-the-cache "
                "and mascot checks could not run (pass --raw-dir)",
            )
        )

    for league in leagues:
        sport = league.sport
        if not league.game_seasons:
            problems.append(
                Problem(
                    "league_has_no_games",
                    sport,
                    f"{sport}: no games rows at all; this league was never ingested "
                    f"(`cfb ingest --sport {sport} --years ...`)",
                )
            )

        have_games = set(league.game_seasons)
        behind = tuple(s for s in league.cached_seasons if s not in have_games)
        if behind:
            problems.append(
                Problem(
                    "season_behind_cache",
                    sport,
                    f"{sport}: {len(behind)} season(s) in the committed raw cache have no "
                    f"games in the db: {format_seasons(behind)}; the db is behind the cache "
                    f"(`cfb ingest --sport {sport} --years ...`)",
                    behind,
                )
            )

        for method, rated in league.rated_seasons.items():
            rated_set = set(rated)
            unrated = tuple(s for s in league.game_seasons if s not in rated_set)
            if unrated:
                problems.append(
                    Problem(
                        "season_missing_ratings",
                        sport,
                        f"{sport}: {len(unrated)} season(s) with games have no `{method}` "
                        f"ratings: {format_seasons(unrated)} "
                        f"(`cfb rate --sport {sport} --method {method} --years ...`)",
                        unrated,
                    )
                )

    if aliases.teams_cache_present and aliases.with_mascot == 0:
        problems.append(
            Problem(
                "no_cfb_mascots",
                "cfb",
                f"cfb: none of the {aliases.teams} CFB teams has a teams.mascot although the "
                "CFBD teams cache is committed; the team-alias enrichment (#77) never ran "
                "against this db (`cfb ingest` runs it)",
            )
        )

    return tuple(problems)


def check_currency(db_path: Path | str = DB_PATH, raw_dir: Path | str = RAW_DIR) -> CurrencyReport:
    """Inspect `db_path` read-only against the raw cache in `raw_dir`.

    Raises `DatabaseUnavailableError` if `db_path` does not exist or is not a
    readable sqlite database. Never creates, migrates or writes the file.
    """
    db_path = Path(db_path)
    raw_dir = Path(raw_dir)
    if not db_path.is_file():
        raise DatabaseUnavailableError(
            f"database {db_path} does not exist (or is not a regular file); nothing to check"
        )

    reference = _reference_schema()
    try:
        conn = get_conn(db_path, read_only=True)
    except sqlite3.Error as e:
        raise DatabaseUnavailableError(f"could not open {db_path} read-only: {e}") from e
    try:
        actual = _read_schema(conn)
        leagues = tuple(
            _league_report(conn, actual, reference, sport, raw_dir) for sport in EXPECTED_SPORTS
        )
        aliases = _cfb_alias_coverage(conn, actual, reference, raw_dir)
    except sqlite3.DatabaseError as e:
        raise DatabaseUnavailableError(
            f"{db_path} could not be read as a sqlite database: {e}"
        ) from e
    finally:
        conn.close()

    missing_schema = _missing_schema(actual, reference)
    return CurrencyReport(
        db_path=db_path,
        raw_dir=raw_dir,
        missing_schema=missing_schema,
        leagues=leagues,
        cfb_aliases=aliases,
        problems=_find_problems(missing_schema, raw_dir, leagues, aliases),
    )


def format_report(report: CurrencyReport) -> str:
    lines = [
        f"cfb doctor: {report.db_path}",
        f"raw cache:  {report.raw_dir}",
        "",
        "schema: current"
        if not report.missing_schema
        else f"schema: NOT current (missing {len(report.missing_schema)}: "
        + ", ".join(report.missing_schema)
        + ")",
    ]
    for league in report.leagues:
        lines += [
            "",
            f"[{league.sport}]",
            f"  games:   {format_seasons(league.game_seasons)} ({len(league.game_seasons)} seasons)",
            f"  cache:   {format_seasons(league.cached_seasons)}",
        ]
        for method, seasons in league.rated_seasons.items():
            lines.append(f"  rated {method:<11} {format_seasons(seasons)}")
        if league.sport == "cfb":
            aliases = report.cfb_aliases
            cache = "present" if aliases.teams_cache_present else "absent"
            lines.append(
                f"  mascots: {aliases.with_mascot} of {aliases.teams} CFB teams "
                f"(CFBD teams cache {cache})"
            )

    lines.append("")
    if report.is_current:
        lines.append("OK: the db's data is current.")
    else:
        lines.append(f"NOT CURRENT: {len(report.problems)} problem(s)")
        lines += [f"  - {problem.message}" for problem in report.problems]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cfb doctor",
        description=(
            "Read-only check that a cfb-strength sqlite db's data is current: schema, "
            "every league ingested, no season behind the committed raw cache, every "
            "method rated, CFB mascots enriched. Exits 0 only when it is."
        ),
    )
    parser.add_argument(
        "--db-path", default=None, help="sqlite db to check (defaults to config.DB_PATH)."
    )
    parser.add_argument(
        "--raw-dir", default=None, help="committed raw cache (defaults to config.RAW_DIR)."
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path) if args.db_path else DB_PATH
    raw_dir = Path(args.raw_dir) if args.raw_dir else RAW_DIR
    try:
        report = check_currency(db_path, raw_dir)
    except DatabaseUnavailableError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(format_report(report))
    return 0 if report.is_current else 1


if __name__ == "__main__":
    raise SystemExit(main())
