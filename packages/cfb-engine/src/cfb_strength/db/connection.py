import sqlite3
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


def _migrate_sport_columns(conn: sqlite3.Connection) -> None:
    """Bring a pre-#51 db up to the current schema in place, preserving
    existing rows. Safe to call against a brand-new db too -- every check is
    a no-op there since schema.sql already created these columns fresh.
    """
    for table in _SPORT_COLUMN_TABLES:
        if not _has_column(conn, table, "sport"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN sport TEXT NOT NULL DEFAULT 'cfb'")

    for table in _SOURCE_ID_TABLES:
        if not _has_column(conn, table, "source_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN source_id TEXT")

    # ingestion_log's PK widens from (year, season_type) to
    # (year, season_type, sport) -- sqlite can't ALTER a PRIMARY KEY, and
    # unlike the tables above there's no team_id here to disambiguate sport
    # without it. This table is a regenerable operational log (re-running
    # ingest repopulates it), not data worth a real migration, so a
    # pre-existing old-shape table is dropped and recreated fresh rather than
    # migrated in place.
    if not _has_column(conn, "ingestion_log", "sport"):
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


def _migrate_team_alias_columns(conn: sqlite3.Connection) -> None:
    """Add `teams.mascot` / `teams.alternate_names` (epic #76) to a
    pre-existing db. A no-op against a fresh db, where schema.sql already
    declared them, and idempotent when called twice -- sqlite has no
    "ADD COLUMN IF NOT EXISTS", hence the explicit `_has_column` guard.

    Existing rows are left with NULL in both columns rather than backfilled:
    the alias data comes from a CFBD `/teams` fetch the ingest path owns
    (#77), and a NULL mascot is a legitimate end state anyway (every NFL row,
    plus any CFB team CFBD has no mascot for).
    """
    for column, column_type in _TEAM_ALIAS_COLUMNS:
        if not _has_column(conn, "teams", column):
            conn.execute(f"ALTER TABLE teams ADD COLUMN {column} {column_type}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    _migrate_sport_columns(conn)
    _migrate_team_alias_columns(conn)
    conn.commit()
