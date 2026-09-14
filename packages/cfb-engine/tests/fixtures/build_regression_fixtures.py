"""Regenerate the committed engine regression fixtures (issue #110).

    cd packages/cfb-engine
    uv run python tests/fixtures/build_regression_fixtures.py

writes `tests/fixtures/cfb_regression.sqlite3` and
`tests/fixtures/nfl_regression.sqlite3`. `--out-dir DIR` writes them
somewhere else instead, and `--league cfb|nfl` builds only one.

Not part of the pytest suite (the name doesn't match `test_*.py`, so it is
never collected), and nothing under `src/` imports it. Two test modules
import it: `tests/test_regression_fixtures_regenerate_identically.py` calls
`build` to regenerate both fixtures into a temp dir, and
`tests/test_regression_fixture_generator.py` tests its safety guarantees.

Provenance
----------
Each fixture is built through the real ingest path, never extracted from a
machine-local db:

1. A fresh sqlite db at the current schema (`get_conn` + `ensure_schema`).
2. Every season in that league's ingest window (`MIN_YEAR`..`MAX_YEAR` of
   `ingest.ingest_season` or `ingest.nflverse.ingest_season`), both season
   types, through that ingest's own `ingest_one`, in the order `cfb ingest`
   runs them. For CFB, `enrich_team_aliases` runs once afterwards, as in
   `cfb ingest`, so `teams.mascot` / `teams.alternate_names` come from the
   committed CFBD `/teams` cache. Ingesting the whole window, not only the
   fixture seasons, keeps each `teams` row exactly as a production build
   leaves it (`_write_teams` keeps the most recently ingested school name
   and classification).
3. Cache-first with zero live calls. `live_fetches_disabled` replaces every
   client function that reaches the network (`LIVE_FETCH_FUNCTIONS`) with
   one that raises. It first checks that each of those names exists and is
   callable, so a rename fails loudly instead of leaving the real function
   in place. Every result's `fetched_live` is checked too. The committed
   `data/raw/` must hold everything; the script fails instead of fetching.
4. Pruned to the fixture seasons: `games` of those seasons, the `teams`
   those games reference, the `team_season` rows for those team/season
   pairs, and those seasons' `ingestion_log` rows.
5. No ratings. `ratings` and `rating_breakdowns` stay empty, because the
   golden tests must compute every rating themselves.
6. `ingestion_log.fetched_at` is set to `FIXTURE_FETCHED_AT`, then the db is
   VACUUMed. Ingest stamps `fetched_at` with the wall clock, the only
   run-dependent value in the db, so without this two runs would differ.
   With it, rerunning the script on an unchanged cache and schema produces
   byte-identical files with the same SQLite build. A different SQLite
   version may lay pages out differently, so the tests compare logical
   content, never bytes.

The build writes to a `.partial` file beside the destination and renames it
into place only after every check passes. On any failure, including
Ctrl-C, it removes the `.partial` file and its `-journal` / `-wal` / `-shm`
before re-raising, and the existing fixture is left untouched.

Seasons: CFB 2001, 2003, 2004, 2005, 2013, 2017, 2019 (the PRD's seven
golden years). NFL 1999, 2004, 2013, 2022.

What catches a stale committed fixture
--------------------------------------
Regenerate after any change to the schema, to either ingest path, or to the
committed cache for these seasons. Three things in the suite catch a fixture
that wasn't regenerated, and each covers something different:

* `tests/test_regression_fixtures_regenerate_identically.py` rebuilds both
  fixtures with `build` and compares the logical content (every row of
  every table, and the schema) with the committed files. It is the only one
  that notices a changed score, a missing game, or an edited mascot or
  `ingestion_log` row, whether the fixture or the cache changed.
* `tests/test_regression_fixtures_currency.py` runs `cfb doctor`'s check.
  It covers the schema and which (season, season_type) batches are present,
  and never looks at game content or counts.
* `StaleDatabaseWarning` is an error in pytest (pyproject.toml), so a
  fixture at an old schema also fails every test that opens it.

After regenerating, rebuild `apps/api`'s own fixture
(`apps/api/tests/fixtures/build_fixture.py`), which starts from
`cfb_regression.sqlite3`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import NoReturn

from cfb_strength import config
from cfb_strength.config import SEASON_TYPES
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest import client as cfbd_client
from cfb_strength.ingest import ingest_season as cfbd_ingest
from cfb_strength.ingest.nflverse import client as nflverse_client
from cfb_strength.ingest.nflverse import ingest_season as nflverse_ingest
from cfb_strength.ingest.nflverse.normalize import build_team_lookup

FIXTURES_DIR = Path(__file__).resolve().parent
ENGINE_DIR = FIXTURES_DIR.parents[1]
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"

# A fixed placeholder, not a real fetch time. See step 6 of the docstring.
FIXTURE_FETCHED_AT = "1970-01-01T00:00:00+00:00"

# Every client function that reaches the network. Each `get_*` function
# looks these up as module globals at call time, so replacing them disables
# live fetching. tests/test_regression_fixture_generator.py fails if a
# client function that touches `requests` is missing from this list.
LIVE_FETCH_FUNCTIONS: tuple[tuple[ModuleType, str], ...] = (
    (cfbd_client, "_fetch_games_live"),
    (cfbd_client, "_fetch_teams_live"),
    (nflverse_client, "_fetch_csv_live"),
)


@dataclass(frozen=True)
class FixtureSpec:
    sport: str
    filename: str
    seasons: tuple[int, ...]
    build: Callable[[sqlite3.Connection], None]


def _refuse_live_fetch(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError(
        "build_regression_fixtures.py never fetches live data: the committed cache "
        f"under {COMMITTED_RAW_DIR} is missing something ingest asked for"
    )


@contextmanager
def live_fetches_disabled() -> Iterator[None]:
    """Replace every `LIVE_FETCH_FUNCTIONS` entry with `_refuse_live_fetch`
    for the duration of the block, then put the originals back.

    Every name is checked before any is replaced. Replacing a name that no
    longer exists would just add an unused attribute and leave the renamed
    real function reachable, which is how a rename once turned this guard
    into a no-op."""
    unusable = [
        f"{module.__name__}.{name}"
        for module, name in LIVE_FETCH_FUNCTIONS
        if not callable(getattr(module, name, None))
    ]
    if unusable:
        raise RuntimeError(
            "refusing to build: cannot disable live fetching, because "
            f"{', '.join(unusable)} is not a callable any more (renamed or removed?). "
            "Update LIVE_FETCH_FUNCTIONS in build_regression_fixtures.py."
        )
    originals = [(module, name, getattr(module, name)) for module, name in LIVE_FETCH_FUNCTIONS]
    try:
        for module, name, _ in originals:
            setattr(module, name, _refuse_live_fetch)
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


def _ingest_cfb(conn: sqlite3.Connection) -> None:
    # `ingest_one` reads `config.RAW_DIR` and has no raw_dir parameter, so the
    # environment must not have redirected it away from the committed cache.
    if config.RAW_DIR.resolve() != COMMITTED_RAW_DIR:
        raise RuntimeError(
            f"config.RAW_DIR is {config.RAW_DIR}, not the committed cache {COMMITTED_RAW_DIR}; "
            "unset CFB_DATA_DIR and rerun"
        )
    for year in range(cfbd_ingest.MIN_YEAR, cfbd_ingest.MAX_YEAR + 1):
        for season_type in SEASON_TYPES:
            result = cfbd_ingest.ingest_one(conn, year, season_type)
            if result.fetched_live:
                raise RuntimeError(f"cfb {year} {season_type} was fetched live")
    aliases = cfbd_ingest.enrich_team_aliases(conn, raw_dir=COMMITTED_RAW_DIR)
    if aliases.fetched_live:
        raise RuntimeError("the CFBD /teams payload was fetched live")


def _ingest_nfl(conn: sqlite3.Connection) -> None:
    games_raw, games_live = nflverse_client.get_games(raw_dir=COMMITTED_RAW_DIR)
    teams_raw, teams_live = nflverse_client.get_teams(raw_dir=COMMITTED_RAW_DIR)
    if games_live or teams_live:
        raise RuntimeError("an nflverse CSV was fetched live")
    team_lookup = build_team_lookup(teams_raw)
    for year in range(nflverse_ingest.MIN_YEAR, nflverse_ingest.MAX_YEAR + 1):
        for season_type in SEASON_TYPES:
            nflverse_ingest.ingest_one(conn, year, season_type, games_raw, team_lookup)


FIXTURES: dict[str, FixtureSpec] = {
    "cfb": FixtureSpec(
        "cfb", "cfb_regression.sqlite3", (2001, 2003, 2004, 2005, 2013, 2017, 2019), _ingest_cfb
    ),
    "nfl": FixtureSpec("nfl", "nfl_regression.sqlite3", (1999, 2004, 2013, 2022), _ingest_nfl),
}


def _count(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _prune(conn: sqlite3.Connection, spec: FixtureSpec) -> None:
    placeholders = ",".join("?" * len(spec.seasons))
    seasons = spec.seasons
    with conn:
        conn.execute(f"DELETE FROM games WHERE season NOT IN ({placeholders})", seasons)
        conn.execute(
            """
            DELETE FROM team_season WHERE NOT EXISTS (
                SELECT 1 FROM games g
                WHERE g.season = team_season.year
                  AND team_season.team_id IN (g.home_team_id, g.away_team_id)
            )
            """
        )
        conn.execute(
            """
            DELETE FROM teams WHERE id NOT IN (
                SELECT home_team_id FROM games UNION SELECT away_team_id FROM games
            )
            """
        )
        conn.execute(f"DELETE FROM ingestion_log WHERE year NOT IN ({placeholders})", seasons)
        conn.execute("UPDATE ingestion_log SET fetched_at = ?", (FIXTURE_FETCHED_AT,))


def _check(conn: sqlite3.Connection, spec: FixtureSpec) -> None:
    for table in ("ratings", "rating_breakdowns"):
        if _count(conn, f"SELECT COUNT(*) FROM {table}"):
            raise RuntimeError(f"{spec.filename}: {table} must be empty")
    for table in ("games", "teams", "team_season", "ingestion_log"):
        sports = {row[0] for row in conn.execute(f"SELECT DISTINCT sport FROM {table}")}
        if sports != {spec.sport}:
            raise RuntimeError(f"{spec.filename}: {table} holds sports {sorted(sports)}")
    for season_type in SEASON_TYPES:
        found = tuple(
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT season FROM games WHERE season_type = ? ORDER BY season",
                (season_type,),
            )
        )
        if found != spec.seasons:
            raise RuntimeError(f"{spec.filename}: {season_type} seasons {found} != {spec.seasons}")
        logged = tuple(
            row[0]
            for row in conn.execute(
                "SELECT year FROM ingestion_log WHERE season_type = ? ORDER BY year",
                (season_type,),
            )
        )
        if logged != spec.seasons:
            raise RuntimeError(f"{spec.filename}: {season_type} ingestion_log {logged}")
    if spec.sport == "cfb" and not _count(conn, "SELECT COUNT(mascot) FROM teams"):
        raise RuntimeError(f"{spec.filename}: no team has a mascot")


def _remove_partial(partial: Path) -> None:
    for path in (partial, *(Path(f"{partial}{suffix}") for suffix in ("-journal", "-wal", "-shm"))):
        path.unlink(missing_ok=True)


def build(spec: FixtureSpec, out_dir: Path) -> Path:
    """Build one fixture into `out_dir`. Callers must be inside
    `live_fetches_disabled()`; `main` is."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / spec.filename
    partial = out_dir / f".{spec.filename}.partial"
    _remove_partial(partial)

    try:
        conn = get_conn(partial)
        try:
            ensure_schema(conn)
            spec.build(conn)
            _prune(conn, spec)
            _check(conn, spec)
            conn.execute("VACUUM")
        finally:
            conn.close()
        os.replace(partial, dest)
    except BaseException:
        # Ctrl-C included: never leave a half-built db beside the fixtures.
        _remove_partial(partial)
        raise

    conn = get_conn(dest, read_only=True)
    try:
        counts = {
            table: _count(conn, f"SELECT COUNT(*) FROM {table}")
            for table in ("games", "teams", "team_season", "ingestion_log")
        }
        mascots = _count(conn, "SELECT COUNT(mascot) FROM teams")
    finally:
        conn.close()
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    print(
        f"{dest}: seasons {', '.join(map(str, spec.seasons))}; "
        + ", ".join(f"{table}={n}" for table, n in counts.items())
        + f", mascots={mascots}; {dest.stat().st_size} bytes; sha256 {digest}"
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the committed engine regression fixtures from the committed cache."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=FIXTURES_DIR,
        help="where to write the fixtures (default: tests/fixtures).",
    )
    parser.add_argument(
        "--league", choices=sorted(FIXTURES), help="build only this league's fixture."
    )
    args = parser.parse_args(argv)

    leagues = [args.league] if args.league else list(FIXTURES)
    with live_fetches_disabled():
        for league in leagues:
            build(FIXTURES[league], args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
