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


def get_conn(db_path: Path | str = DB_PATH, *, read_only: bool = False) -> sqlite3.Connection:
    db_path = Path(db_path)
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    _migrate_sport_columns(conn)
    conn.commit()
