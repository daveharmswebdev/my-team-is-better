import sqlite3
import warnings
from pathlib import Path

from cfb_strength.config import DB_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Tables that gained a `sport` column for #51 (NFL support) after already
# shipping without one. `CREATE TABLE IF NOT EXISTS` in schema.sql is a no-op
# against a pre-existing db, so a real pre-#51 local `data/cfb.sqlite3` needs
# these added via ALTER TABLE instead -- guarded here in Python since sqlite
# has no "ADD COLUMN IF NOT EXISTS". Existing rows backfill to 'cfb' via the
# column default; no data rewrite needed.
_SPORT_COLUMN_TABLES = ("teams", "team_season", "games", "ratings", "rating_breakdowns")

# teams/games only: nflverse's native string id, for traceability + idempotent
# re-ingest (see schema.sql's comment on the teams table).
_SOURCE_ID_TABLES = ("teams", "games")

# Columns `teams` gained for epic #76 (mascot/city-searchable typeahead),
# populated by #77's CFBD `/teams` ingest. Same pre-existing-db problem as the
# #51 columns above: schema.sql's `CREATE TABLE IF NOT EXISTS` is a no-op
# against a real local `data/cfb.sqlite3`, so these are added here too.
# Nullable with no default -- unlike `sport`, there is no sensible backfill
# value, and populating them is the ingest's job, not the migration's.
_TEAM_ALIAS_COLUMNS = (("mascot", "TEXT"), ("alternate_names", "TEXT"))


class StaleDatabaseWarning(UserWarning):
    """`ensure_schema` had to migrate a db that already holds games (#97).

    Schema currency disguises data staleness: the migrations below add the
    missing columns, but no migration can add the NFL rows or mascots an old
    build never ingested. A migration firing on a populated db is the one
    moment this code *knows* the db predates the current schema, so it says
    so instead of returning a current-looking db silently. `cfb doctor` is
    the full check.
    """


def get_conn(
    db_path: Path | str = DB_PATH,
    *,
    read_only: bool = False,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open a connection to the project sqlite db.

    `check_same_thread` (issue #44) forwards straight to `sqlite3.connect`.
    It defaults to True -- sqlite's own strict behavior -- because that is
    right for every single-threaded caller (the CLI, the MCP server, the
    tests): using one connection from two threads is a real bug there and
    should fail loudly.

    `apps/api` passes False, and needs to. FastAPI dispatches a sync
    generator dependency and the sync route handler to `run_in_threadpool`
    *independently*, so the thread that opens the connection in
    `api.deps.get_db_conn` is routinely not the thread the route body then
    uses it on -- which sqlite rejects, surfacing as an intermittent HTTP
    500. Opting out is safe there rather than merely expedient: that
    dependency opens a fresh connection per request and closes it in the
    same `finally`, so each connection belongs to exactly one logical
    request and is never used by two threads *at once* -- only, possibly,
    by two threads in sequence. Anything that genuinely shared one
    connection across concurrent work would still be unsafe, and passing
    this flag would be hiding the problem instead of fixing it.
    """
    db_path = Path(db_path)
    if read_only:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, check_same_thread=check_same_thread
        )
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _migrate_sport_columns(conn: sqlite3.Connection) -> list[str]:
    """Bring a pre-#51 db up to the current schema in place, preserving
    existing rows. Safe to call against a brand-new db too -- every check is
    a no-op there since schema.sql already created these columns fresh.

    Returns what it had to add (`table.column`), empty when nothing -- the
    signal `ensure_schema`'s staleness warning keys on.
    """
    added: list[str] = []
    for table in _SPORT_COLUMN_TABLES:
        if not _has_column(conn, table, "sport"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN sport TEXT NOT NULL DEFAULT 'cfb'")
            added.append(f"{table}.sport")

    for table in _SOURCE_ID_TABLES:
        if not _has_column(conn, table, "source_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN source_id TEXT")
            added.append(f"{table}.source_id")

    # ingestion_log's PK widens from (year, season_type) to
    # (year, season_type, sport) -- sqlite can't ALTER a PRIMARY KEY, and
    # unlike the tables above there's no team_id here to disambiguate sport
    # without it. This table is a regenerable operational log (re-running
    # ingest repopulates it), not data worth a real migration, so a
    # pre-existing old-shape table is dropped and recreated fresh rather than
    # migrated in place.
    if not _has_column(conn, "ingestion_log", "sport"):
        added.append("ingestion_log.sport (table rebuilt)")
        conn.execute("DROP TABLE ingestion_log")
        conn.execute(
            """
            CREATE TABLE ingestion_log (
                year INTEGER NOT NULL,
                season_type TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                game_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                sport TEXT NOT NULL DEFAULT 'cfb',
                PRIMARY KEY (year, season_type, sport)
            )
            """
        )

    # Created here rather than in schema.sql: see schema.sql's comment on the
    # teams table for why these can't be plain `CREATE ... IF NOT EXISTS`
    # statements in that file.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_source_id ON teams(source_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_games_source_id ON games(source_id)")
    return added


def _migrate_team_alias_columns(conn: sqlite3.Connection) -> list[str]:
    """Add `teams.mascot` / `teams.alternate_names` (epic #76) to a
    pre-existing db. A no-op against a fresh db, where schema.sql already
    declared them, and idempotent when called twice -- sqlite has no
    "ADD COLUMN IF NOT EXISTS", hence the explicit `_has_column` guard.

    Existing rows are left with NULL in both columns rather than backfilled:
    the alias data comes from a CFBD `/teams` fetch the ingest path owns
    (#77), and a NULL mascot is a legitimate end state anyway (every NFL row,
    plus any CFB team CFBD has no mascot for).
    """
    added: list[str] = []
    for column, column_type in _TEAM_ALIAS_COLUMNS:
        if not _has_column(conn, "teams", column):
            conn.execute(f"ALTER TABLE teams ADD COLUMN {column} {column_type}")
            added.append(f"teams.{column}")
    return added


def _migrate_ratings_ties_column(conn: sqlite3.Connection) -> list[str]:
    """Add `ratings.ties` (issue #83) to a pre-existing db.

    Existing rows backfill to 0 via the column default. That is honest for
    every CFB row and wrong only for an NFL season containing a real tie,
    and only until that season is re-rated -- `compute_and_store` rewrites
    its (year, method, sport) rows wholesale. Production always builds from
    an empty db, so it never sees the stale window.
    """
    if not _has_column(conn, "ratings", "ties"):
        conn.execute("ALTER TABLE ratings ADD COLUMN ties INTEGER NOT NULL DEFAULT 0")
        return ["ratings.ties"]
    return []


def _schema_objects(conn: sqlite3.Connection) -> set[str]:
    return {
        f"{row[0]} {row[1]}"
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
        )
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    before = _schema_objects(conn)
    conn.executescript(SCHEMA_PATH.read_text())
    added = [
        *_migrate_sport_columns(conn),
        *_migrate_team_alias_columns(conn),
        *_migrate_ratings_ties_column(conn),
    ]
    # Whole tables/indexes too, not only ALTER TABLE columns: schema.sql's
    # `CREATE ... IF NOT EXISTS` and the migration's indexes also only add
    # something to a db that predates them. (ingestion_log's drop-and-rebuild
    # exists before and after, so it is reported by the column list above.)
    added += sorted(_schema_objects(conn) - before)
    conn.commit()

    # Issue #97. Only a migration that actually fired on a db already holding
    # games is a staleness signal: a fresh db, an already-current db, and an
    # empty pre-existing db (nothing in it can be stale) all stay quiet.
    if added and conn.execute("SELECT EXISTS (SELECT 1 FROM games)").fetchone()[0]:
        db_file = conn.execute("PRAGMA database_list").fetchone()[2] or "this database"
        warnings.warn(
            StaleDatabaseWarning(
                f"{db_file} predates the current schema: ensure_schema just added "
                f"{', '.join(added)} to a database that already holds games, so its data "
                "may predate the current schema too (e.g. no NFL rows, no team mascots), "
                "which no migration can backfill. Run `cfb doctor --db-path "
                f"{db_file}` to check it, or rebuild it from the committed raw cache."
            ),
            stacklevel=2,
        )
