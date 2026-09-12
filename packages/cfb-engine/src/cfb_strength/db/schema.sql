-- `sport` (added #51, sprint 2: NFL support) distinguishes rows sharing this
-- one sqlite db rather than splitting into a new datastore. `source_id`
-- (teams/games only) carries nflverse's native string id (team abbreviation /
-- composite game id) for traceability and idempotent re-ingest -- CFB rows
-- leave it NULL (sqlite UNIQUE treats multiple NULLs as distinct, so this
-- coexists with the CFBD-native integer `id` PK). See ingest/nflverse/ for
-- the surrogate-id minting that keeps NFL's string-keyed natural ids from
-- colliding with CFBD's native integer ids on these same PK columns.
--
-- NOTE: the unique indexes on teams.source_id / games.source_id are NOT
-- declared here. This script runs unconditionally against a possibly
-- pre-existing (pre-#51) db via CREATE TABLE IF NOT EXISTS, which is a no-op
-- on an already-existing table -- so a fresh-db-only index here would raise
-- "no such column: source_id" against a real pre-existing db, before
-- connection.py's migration below has had a chance to add the column. See
-- `_migrate_sport_columns` in connection.py, which creates both indexes
-- itself once it has guaranteed the column exists either way.
--
-- `mascot` / `alternate_names` (added for epic #76, populated by #77's CFBD
-- `/teams` ingest) are display/search metadata only -- `school` remains the
-- canonical identity string every other table, the verdict lookup, the
-- persona grounding check, and the narration cache key on. `alternate_names`
-- holds a JSON array of strings (CFBD's `alternateNames` plus its
-- `abbreviation`, deduped); NULL and '[]' both mean "no aliases known".
-- These are subject to the same pre-existing-db caveat as source_id above:
-- declaring them here only covers a *fresh* db, so `_migrate_team_alias_columns`
-- in connection.py adds them to an already-created `teams` table.
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    school TEXT NOT NULL,
    classification TEXT,
    sport TEXT NOT NULL DEFAULT 'cfb',
    source_id TEXT,
    mascot TEXT,
    alternate_names TEXT
);

CREATE TABLE IF NOT EXISTS team_season (
    team_id INTEGER NOT NULL REFERENCES teams(id),
    year INTEGER NOT NULL,
    conference TEXT,
    classification TEXT,
    sport TEXT NOT NULL DEFAULT 'cfb',
    PRIMARY KEY (team_id, year)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER,
    season_type TEXT NOT NULL,
    start_date TEXT,
    neutral_site INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_points INTEGER,
    away_points INTEGER,
    home_conference TEXT,
    away_conference TEXT,
    venue TEXT,
    raw_json TEXT NOT NULL,
    sport TEXT NOT NULL DEFAULT 'cfb',
    source_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_home ON games(home_team_id);
CREATE INDEX IF NOT EXISTS idx_games_away ON games(away_team_id);
-- idx_games_source_id: see the teams.source_id note above -- created in
-- connection.py's migration, not here, for the same reason.

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'keener',
    team_id INTEGER NOT NULL REFERENCES teams(id),
    rating REAL NOT NULL,
    rank INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    sport TEXT NOT NULL DEFAULT 'cfb',
    UNIQUE(year, method, team_id)
);
CREATE INDEX IF NOT EXISTS idx_ratings_year_method ON ratings(year, method);

-- opponent_team_id NULL marks the "background" row: the epsilon-regularizer
-- residual folded into one line rather than one row per unplayed team.
CREATE TABLE IF NOT EXISTS rating_breakdowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'keener',
    team_id INTEGER NOT NULL REFERENCES teams(id),
    opponent_team_id INTEGER REFERENCES teams(id),
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,
    credit REAL,
    contribution REAL NOT NULL,
    computed_at TEXT NOT NULL,
    sport TEXT NOT NULL DEFAULT 'cfb'
);
CREATE INDEX IF NOT EXISTS idx_rating_breakdowns_year_method_team
    ON rating_breakdowns(year, method, team_id);

-- sport is part of the PK here (unlike the tables above): year/season_type
-- alone would collide between a CFB and an NFL ingest run of the same
-- year/season_type, and team_id-based disambiguation (which is what lets the
-- other tables skip this) doesn't apply to this table -- it has no team_id.
CREATE TABLE IF NOT EXISTS ingestion_log (
    year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    game_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    sport TEXT NOT NULL DEFAULT 'cfb',
    PRIMARY KEY (year, season_type, sport)
);
