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
  c. `season_behind_cache` -- a (season, season_type) pair the league's
     ingest would write from the committed raw cache, but that the db's
     `games` lacks. Pairs, not bare seasons: a db built mid-season without
     the postseason has the season but not its champion.
  d. `season_missing_ratings` -- a season with games but no `ratings` rows
     for some method in `contracts.Method`.
  e. `no_cfb_mascots` -- the db has CFB teams, but not one has a mascot,
     although the CFBD `/teams` cache is committed (the #77 enrichment never
     ran). Deliberately a zero rule, not a coverage threshold: CFBD has no
     mascot for some real teams. A db with no CFB teams at all is (b)'s
     problem, not this one's.
  f. `cache_past_max_year` -- the cache holds a *finished* season past the
     league's ingest `MAX_YEAR` (NFL: a Super Bowl row whose two scores both
     parse as integers; CFB: a postseason file whose latest-dated games are
     all completed -- see `_postseason_finished`). `cfb ingest`
     skips it, so no db can ever be current with it: MAX_YEAR needs a bump
     (the #9 class of bug). An unfinished season past MAX_YEAR -- the season
     in progress -- is only a note, which never changes the exit code.

plus two problems about `--raw-dir` itself, because a check that silently
skips is a false green:

  * `raw_cache_missing` -- the directory does not exist.
  * `raw_cache_unrecognized` -- it exists but doesn't look like this league's
    committed cache: CFB has no in-window `{year}_{season_type}.json` or no
    `teams.json`; NFL has no `nfl/games.csv`, no `season`/`game_type`
    columns, or no in-window game that nflverse ingest would keep.

Guarantees:

* **Read-only.** The db is opened read-only through `get_conn` and is never
  handed to `ensure_schema`. The "what would `ensure_schema` produce?"
  reference for (a) comes from running `ensure_schema` against a throwaway
  in-memory db instead, so a column added to schema.sql or a new `_migrate_*`
  step is expected here automatically, with no second hand-maintained column
  list to drift. A WAL-mode db with no -wal file is opened `immutable`, so
  that no platform's SQLite creates -wal/-shm next to it (see
  `_open_read_only`).
* **Tolerant of old shapes.** Tables or columns a stale db lacks are read as
  the migration would backfill them. A pre-#51 `games` row with no `sport`
  column counts as CFB (the column's schema default), and a missing
  `teams.mascot` counts as NULL. So the report describes the data the db
  really holds rather than crashing on the schema gap (a).
* **Leagues, methods and season types come from their single definitions**
  (`get_args(Sport)`, `get_args(Method)`, `config.SEASON_TYPES`), never from
  a hand-written tuple.

"Would write from the cache" (c) is read the way each ingest reads it. A
season counts only inside that ingest's `MIN_YEAR`..`MAX_YEAR`, because
nflverse's whole-history `games.csv` already carries the in-progress 2026
season, which `cfb ingest --sport nfl` deliberately skips. CFB pairs come
from the files the CFBD client's own `cache_path` names; a file holding `[]`
writes no games and is not a pair. NFL rows get the window first, then
nflverse ingest's own `REGULAR_GAME_TYPES` / `POSTSEASON_GAME_TYPES` filter:
a row of any other game type is skipped exactly as ingest skips it, never
treated as an unreadable cache.

This lives in `ingest` because ingest owns the cache-path conventions. It may
import both the CFBD and nflverse ingest paths. The forbidden contracts in
`.importlinter` stop those two paths importing each other, and neither one
imports this module.
"""

from __future__ import annotations

import argparse
import csv
import json
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
    "raw_cache_unrecognized",
    "league_has_no_games",
    "season_behind_cache",
    "season_missing_ratings",
    "no_cfb_mascots",
    "cache_past_max_year",
]

Pair = tuple[int, str]


class DatabaseUnavailableError(RuntimeError):
    """The db path does not exist, or is not a readable sqlite database."""


@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    sport: Sport | None
    message: str
    seasons: tuple[int, ...] = ()
    # (season, season_type) pairs, for `season_behind_cache`.
    pairs: tuple[Pair, ...] = ()


@dataclass(frozen=True)
class LeagueReport:
    sport: Sport
    game_seasons: tuple[int, ...]
    # season_type -> seasons, keyed in `config.SEASON_TYPES` order.
    game_seasons_by_type: Mapping[str, tuple[int, ...]]
    cached_seasons_by_type: Mapping[str, tuple[int, ...]]
    # method -> seasons with at least one ratings row, keyed in `Method` order.
    rated_seasons: Mapping[Method, tuple[int, ...]]
    cache_beyond_max_year: tuple[int, ...] = ()
    # The subset of `cache_beyond_max_year` that is already finished.
    cache_finished_beyond_max_year: tuple[int, ...] = ()
    cache_max_year: int | None = None
    # Why `--raw-dir` doesn't look like this league's cache, when it doesn't.
    cache_unrecognized: str | None = None


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
    notes: tuple[str, ...] = ()

    @property
    def is_current(self) -> bool:
        return not self.problems


# ---------------------------------------------------------------------------
# committed raw cache: which (season, season_type) pairs would ingest write?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheScan:
    pairs: frozenset[Pair]
    beyond_max_year: tuple[int, ...]
    max_year: int
    unrecognized: str | None = None
    finished_beyond_max_year: tuple[int, ...] = ()


def _holds_no_games(path: Path) -> bool:
    if path.stat().st_size > 64:
        return False
    try:
        return bool(json.loads(path.read_text()) == [])
    except ValueError:
        return False


def _postseason_finished(path: Path) -> bool:
    """Whether a CFBD postseason file describes a finished postseason.

    The rule: every game at the file's latest `startDate` is `completed`.
    The last-dated postseason game is the national championship, played
    after every bowl, so once it is complete the season is over. That holds
    even if an earlier bowl never happens: CFBD keeps a game that was never
    played as `completed: false` for good (the committed cache already holds
    forfeited and cancelled games like that), so requiring *every* game to be
    complete would leave a finished season stuck as a note forever. A file
    with no dated game proves nothing and counts as unfinished. `startDate`s
    are compared as CFBD's ISO-8601 UTC strings, which sort chronologically.
    Only read for seasons past MAX_YEAR, so it is small.
    """
    try:
        games = json.loads(path.read_text())
    except ValueError:
        return False
    if not isinstance(games, list):
        return False
    dated = [
        game
        for game in games
        if isinstance(game, dict) and isinstance(game.get("startDate"), str) and game["startDate"]
    ]
    if not dated:
        return False
    last = max(str(game["startDate"]) for game in dated)
    return all(game.get("completed") is True for game in dated if game["startDate"] == last)


def _cfbd_cache_scan(raw_dir: Path) -> CacheScan:
    min_year, max_year = cfbd_ingest.MIN_YEAR, cfbd_ingest.MAX_YEAR
    pairs: set[Pair] = set()
    beyond: set[int] = set()
    finished: set[int] = set()
    for path in raw_dir.glob("*_*.json"):
        year_text, _, season_type = path.stem.partition("_")
        if not year_text.isdigit() or season_type not in SEASON_TYPES:
            continue
        year = int(year_text)
        if cfbd_games_cache_path(year, season_type, raw_dir) != path:
            continue
        if year > max_year:
            beyond.add(year)
            if season_type == "postseason" and _postseason_finished(path):
                finished.add(year)
        elif year >= min_year and not _holds_no_games(path):
            pairs.add((year, season_type))

    reasons: list[str] = []
    if not pairs:
        reasons.append(f"no {{year}}_{{season_type}}.json game files for {min_year}-{max_year}")
    teams = cfbd_teams_cache_path(raw_dir)
    if not teams.is_file():
        reasons.append(f"no {teams.name}")
    return CacheScan(
        pairs=frozenset(pairs),
        beyond_max_year=tuple(sorted(beyond)),
        max_year=max_year,
        unrecognized="; ".join(reasons) or None,
        finished_beyond_max_year=tuple(sorted(finished)),
    )


# nflverse ingest's own row filter (ingest/nflverse/ingest_season.py
# `_filter_raw_games`): `regular` batches keep REGULAR_GAME_TYPES, every other
# batch keeps POSTSEASON_GAME_TYPES, and a row of any other type is dropped.
_NFL_SEASON_TYPE_BY_GAME_TYPE: Mapping[str, str] = {
    **{game_type: "regular" for game_type in nflverse_ingest.REGULAR_GAME_TYPES},
    **{game_type: "postseason" for game_type in nflverse_ingest.POSTSEASON_GAME_TYPES},
}
# The last playoff round: a season whose Super Bowl has a score is over.
_NFL_FINAL_GAME_TYPE = "SB"


def _nfl_score(cell: str | None) -> int | None:
    """An nflverse score cell as an int, or None when the game has no score
    yet: empty, "NA", or anything else that isn't a whole number."""
    if cell is None:
        return None
    try:
        return int(cell)
    except ValueError:
        return None


def _nflverse_cache_scan(raw_dir: Path) -> CacheScan:
    min_year, max_year = nflverse_ingest.MIN_YEAR, nflverse_ingest.MAX_YEAR
    path = nflverse_games_cache_path(raw_dir)
    name = path.relative_to(raw_dir)

    def unrecognized(reason: str) -> CacheScan:
        return CacheScan(frozenset(), (), max_year, reason)

    if not path.is_file():
        return unrecognized(f"no {name}")

    pairs: set[Pair] = set()
    beyond: set[int] = set()
    finished: set[int] = set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        missing = [c for c in ("season", "game_type") if c not in columns]
        if missing:
            return unrecognized(f"{name} has no {' / '.join(missing)} column")
        has_scores = "home_score" in columns and "away_score" in columns
        for row in reader:
            try:
                season = int(row["season"])
            except (TypeError, ValueError):
                # ingest matches `season` as the string of a requested year,
                # so a row like this is never ingested either.
                continue
            game_type = row["game_type"]
            # The window first: a season past MAX_YEAR is noted (or, once
            # finished, reported) whatever its rows' game types are.
            if season > max_year:
                beyond.add(season)
                played = not has_scores or (
                    _nfl_score(row["home_score"]) is not None
                    and _nfl_score(row["away_score"]) is not None
                )
                if game_type == _NFL_FINAL_GAME_TYPE and played:
                    finished.add(season)
                continue
            if season < min_year:
                continue
            season_type = _NFL_SEASON_TYPE_BY_GAME_TYPE.get(game_type)
            if season_type is not None:
                pairs.add((season, season_type))

    if not pairs:
        return unrecognized(
            f"{name} has no games nflverse ingest would keep for {min_year}-{max_year}"
        )
    return CacheScan(
        pairs=frozenset(pairs),
        beyond_max_year=tuple(sorted(beyond)),
        max_year=max_year,
        finished_beyond_max_year=tuple(sorted(finished)),
    )


# One reader per league's cache layout. tests/test_db_currency.py fails if
# its keys and `Sport` disagree, and a league without one is reported as an
# unrecognized cache rather than silently skipped.
CACHED_SEASON_READERS: Mapping[Sport, Callable[[Path], CacheScan]] = {
    "cfb": _cfbd_cache_scan,
    "nfl": _nflverse_cache_scan,
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
        missing.extend(
            f"{table}.{column}" for column in columns if column not in actual.columns[table]
        )
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


def _by_type(pairs: set[Pair] | frozenset[Pair]) -> dict[str, tuple[int, ...]]:
    return {
        season_type: tuple(sorted(s for s, t in pairs if t == season_type))
        for season_type in SEASON_TYPES
    }


def _league_report(
    conn: sqlite3.Connection, actual: _Schema, reference: _Schema, sport: Sport, raw_dir: Path
) -> LeagueReport:
    game_pairs: set[Pair] = set()
    if "games" in actual.columns:
        sport_expr = _column_expr(actual, reference, "games", "sport")
        type_expr = _column_expr(actual, reference, "games", "season_type")
        game_pairs = {
            (int(row[0]), str(row[1]))
            for row in conn.execute(
                f"SELECT DISTINCT season, {type_expr} FROM games WHERE {sport_expr} = ?",
                (sport,),
            )
        }

    rated_seasons: dict[Method, tuple[int, ...]] = {}
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

    scan: CacheScan | None = None
    unrecognized: str | None = None
    if raw_dir.is_dir():
        reader = CACHED_SEASON_READERS.get(sport)
        if reader is None:
            unrecognized = "no raw cache reader is registered for this league"
        else:
            scan = reader(raw_dir)
            unrecognized = scan.unrecognized

    return LeagueReport(
        sport=sport,
        game_seasons=tuple(sorted({season for season, _ in game_pairs})),
        game_seasons_by_type=_by_type(game_pairs),
        cached_seasons_by_type=_by_type(scan.pairs if scan else frozenset()),
        rated_seasons=rated_seasons,
        cache_beyond_max_year=scan.beyond_max_year if scan else (),
        cache_finished_beyond_max_year=scan.finished_beyond_max_year if scan else (),
        cache_max_year=scan.max_year if scan else None,
        cache_unrecognized=unrecognized,
    )


def _cfb_alias_coverage(
    conn: sqlite3.Connection, actual: _Schema, reference: _Schema, raw_dir: Path
) -> AliasCoverage:
    cache_present = cfbd_teams_cache_path(raw_dir).is_file()
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


def _pairs_of(by_type: Mapping[str, tuple[int, ...]]) -> set[Pair]:
    return {(season, season_type) for season_type, seasons in by_type.items() for season in seasons}


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
        if league.cache_unrecognized is not None:
            problems.append(
                Problem(
                    "raw_cache_unrecognized",
                    sport,
                    f"{sport}: {raw_dir} doesn't look like this league's committed raw cache "
                    f"({league.cache_unrecognized}), so the behind-the-cache check"
                    + (" and the mascot check" if sport == "cfb" else "")
                    + " could not run (pass the right --raw-dir)",
                )
            )

        if not league.game_seasons:
            problems.append(
                Problem(
                    "league_has_no_games",
                    sport,
                    f"{sport}: no games rows at all; this league was never ingested "
                    f"(`cfb ingest --sport {sport} --years ...`)",
                )
            )

        missing_pairs = tuple(
            sorted(
                _pairs_of(league.cached_seasons_by_type) - _pairs_of(league.game_seasons_by_type),
                key=lambda pair: (pair[0], SEASON_TYPES.index(pair[1])),
            )
        )
        if missing_pairs:
            per_type = "; ".join(
                f"{season_type} {format_seasons([s for s, t in missing_pairs if t == season_type])}"
                for season_type in SEASON_TYPES
                if any(t == season_type for _, t in missing_pairs)
            )
            problems.append(
                Problem(
                    "season_behind_cache",
                    sport,
                    f"{sport}: {len(missing_pairs)} season/season-type batch(es) in the committed "
                    f"raw cache have no games in the db ({per_type}); the db is behind the "
                    f"cache (`cfb ingest --sport {sport} --years ...`)",
                    seasons=tuple(sorted({season for season, _ in missing_pairs})),
                    pairs=missing_pairs,
                )
            )

        if league.cache_finished_beyond_max_year:
            problems.append(
                Problem(
                    "cache_past_max_year",
                    sport,
                    f"{sport}: the raw cache holds finished season(s) "
                    f"{format_seasons(league.cache_finished_beyond_max_year)} past this league's "
                    f"ingest MAX_YEAR ({league.cache_max_year}), which `cfb ingest` skips, so no "
                    "db can include them: bump MAX_YEAR (see #9)",
                    seasons=league.cache_finished_beyond_max_year,
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

    if aliases.teams > 0 and aliases.teams_cache_present and aliases.with_mascot == 0:
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


def _notes(leagues: tuple[LeagueReport, ...]) -> tuple[str, ...]:
    notes: list[str] = []
    for league in leagues:
        finished = set(league.cache_finished_beyond_max_year)
        unfinished = [s for s in league.cache_beyond_max_year if s not in finished]
        if unfinished:
            notes.append(
                f"{league.sport}: the raw cache holds season(s) {format_seasons(unfinished)} past "
                f"this league's ingest MAX_YEAR ({league.cache_max_year}), which `cfb ingest` "
                "skips. Not finished in the cache yet, so this is expected for the season in "
                "progress; once it finishes, MAX_YEAR needs a bump (see #9)."
            )
    return tuple(notes)


def _is_wal_mode(db_path: Path) -> bool:
    """Header bytes 18/19 (file format write/read version) are 2 in WAL mode."""
    try:
        with db_path.open("rb") as f:
            header = f.read(20)
    except OSError:
        return False
    return (
        len(header) == 20
        and header.startswith(b"SQLite format 3\x00")
        and header[18:20] == b"\x02\x02"
    )


def _wal_file(db_path: Path) -> Path:
    return Path(f"{db_path}-wal")


def _open_read_only(db_path: Path) -> sqlite3.Connection:
    """Open `db_path` read-only, choosing `immutable` only when it is safe.

    The decision rests on the -wal file alone. When a WAL-mode db has no -wal
    file, its main file holds every checkpointed commit and there is nothing
    else to read. That is also exactly what a main-file-only copy of a live
    db contains: commits still sitting in the live db's -wal were never in
    that copy, and the doctor reports the file it was given. A -shm is only
    an index into a -wal, so a stale lone -shm changes nothing. A plain
    `mode=ro` open there is platform-dependent: macOS's SQLite refuses it
    (SQLITE_CANTOPEN), while Linux's may succeed by creating -wal/-shm next
    to the db. `immutable=1` reads the main file as-is and creates nothing,
    on every platform.

    It is never used while a -wal file exists: immutable ignores -wal, so a
    live db's un-checkpointed commits would be silently missed. Immutable
    also takes no locks, so a db should not be checked this way while
    `cfb ingest` or `cfb rate` is writing to it.
    """
    immutable = _is_wal_mode(db_path) and not _wal_file(db_path).exists()
    return get_conn(db_path, read_only=True, immutable=immutable)


def _unreadable(db_path: Path, error: sqlite3.Error) -> DatabaseUnavailableError:
    # The WAL hint only when a -wal file exists, the one case the open used
    # WAL machinery at all (see `_open_read_only`). A WAL-looking header on
    # its own may just be a corrupt file.
    if _is_wal_mode(db_path) and _wal_file(db_path).exists():
        return DatabaseUnavailableError(
            f"{db_path} is a WAL-mode sqlite database, and a read-only open could not use its "
            f"-wal file ({error}): it, or its -shm, is not usable from here, and the doctor will "
            "not change them. Run it where those files are accessible, or check a copy switched "
            "out of WAL mode (`PRAGMA journal_mode = DELETE`)."
        )
    return DatabaseUnavailableError(f"{db_path} could not be read as a sqlite database: {error}")


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
        conn = _open_read_only(db_path)
    except sqlite3.Error as e:
        raise _unreadable(db_path, e) from e
    try:
        actual = _read_schema(conn)
        leagues = tuple(
            _league_report(conn, actual, reference, sport, raw_dir) for sport in EXPECTED_SPORTS
        )
        aliases = _cfb_alias_coverage(conn, actual, reference, raw_dir)
    except sqlite3.DatabaseError as e:
        raise _unreadable(db_path, e) from e
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
        notes=_notes(leagues),
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
        lines += ["", f"[{league.sport}]"]
        for season_type, seasons in league.game_seasons_by_type.items():
            lines.append(f"  games {season_type:<11} {format_seasons(seasons)}")
        if league.cache_unrecognized is not None:
            lines.append(f"  cache       UNRECOGNIZED ({league.cache_unrecognized})")
        else:
            for season_type, seasons in league.cached_seasons_by_type.items():
                lines.append(f"  cache {season_type:<11} {format_seasons(seasons)}")
        for method, seasons in league.rated_seasons.items():
            lines.append(f"  rated {method:<11} {format_seasons(seasons)}")
        if league.sport == "cfb":
            aliases = report.cfb_aliases
            cache = "present" if aliases.teams_cache_present else "absent"
            lines.append(
                f"  mascots: {aliases.with_mascot} of {aliases.teams} CFB teams "
                f"(CFBD teams cache {cache})"
            )

    if report.notes:
        lines += ["", "notes (do not affect the exit code):"]
        lines += [f"  - {note}" for note in report.notes]

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
            "every league ingested, no season/season-type batch behind the committed raw "
            "cache, every method rated, at least one CFB mascot, no finished season past "
            "an ingest's MAX_YEAR. Exits 0 only when it is."
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
