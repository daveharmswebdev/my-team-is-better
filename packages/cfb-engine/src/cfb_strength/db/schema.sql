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
    -- issue #83: completed games with equal scores (see contracts.TeamRating).
    -- Added to a pre-existing db by connection.py's migration.
    ties INTEGER NOT NULL DEFAULT 0,
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

-- Issue #183: the shown work behind a season Elo rating (contracts.EloLedger).
-- One row per (displayed team, game), in the walk's order; every numeric
-- column is the value `ratings/elo.py::_walk` actually used or produced, from
-- that team's side. Written only for a method that produces a ledger
-- (`elo`); keener and elo_career write no rows here, so absence is visible in
-- the database, the same convention `rating_breakdowns` follows for Elo.
CREATE TABLE IF NOT EXISTS elo_ledger_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    method TEXT NOT NULL,
    sport TEXT NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    game_number INTEGER NOT NULL,
    week INTEGER,
    season_type TEXT NOT NULL,
    start_date TEXT,
    opponent_team_id INTEGER NOT NULL REFERENCES teams(id),
    venue TEXT NOT NULL CHECK (venue IN ('home', 'away', 'neutral')),
    team_points INTEGER NOT NULL,
    opponent_points INTEGER NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('W', 'L', 'T')),
    rating_before REAL NOT NULL,
    opponent_rating_before REAL NOT NULL,
    home_field_adjustment REAL NOT NULL,
    rating_gap REAL NOT NULL,
    win_expectancy REAL NOT NULL,
    mov_multiplier REAL NOT NULL,
    shift REAL NOT NULL,
    rating_after REAL NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE (year, method, sport, team_id, game_number)
);
CREATE INDEX IF NOT EXISTS idx_elo_ledger_steps_year_method_sport_team
    ON elo_ledger_steps(year, method, sport, team_id);

-- Issue #183: the EloConfig constants a (year, method, sport) ledger was
-- computed with -- stored rather than re-read from ELO_CONFIGS at display
-- time, so the panel can never print a tuning other than the one that
-- produced the number.
CREATE TABLE IF NOT EXISTS elo_ledger_configs (
    year INTEGER NOT NULL,
    method TEXT NOT NULL,
    sport TEXT NOT NULL,
    starting_rating REAL NOT NULL,
    k REAL NOT NULL,
    hfa REAL NOT NULL,
    scale REAL NOT NULL,
    mov_scale REAL NOT NULL,
    mov_autocorr REAL NOT NULL,
    -- Issue #194: the MOV denominator floor as a fraction of mov_scale.
    -- Pre-#194 dbs get it via `_migrate_elo_ledger_floor_column`.
    mov_denom_floor_fraction REAL NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (year, method, sport)
);

-- Player stats (issue #289, epic #288). New tables, so `CREATE TABLE IF NOT
-- EXISTS` covers a pre-existing db too; no connection.py migration. Shaped so
-- that CFB players, pre-1999 seasons and game-winning drives are additive:
--   * a player's team lives on each stat/starter row, never on `players`;
--   * `player_source_ids` crosswalks every source's own id (gsis, pfr, espn,
--     cfbd) to one player, so a later source attaches instead of duplicating;
--   * season totals are stored in their own right (old eras have no game
--     logs), keyed without `source` so a career can't be counted twice;
--   * a stat a source didn't track is NULL, never 0.
-- The stat columns of both stat tables are exactly `contracts.PlayerStats`,
-- in order (tests/test_player_schema.py).
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    sport TEXT NOT NULL,
    display_name TEXT NOT NULL,
    position TEXT,
    birth_date TEXT
);

CREATE TABLE IF NOT EXISTS player_source_ids (
    player_id INTEGER NOT NULL REFERENCES players(id),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_player_source_ids_player ON player_source_ids(player_id);

-- `source` says who claims this start: sources disagree about starters.
CREATE TABLE IF NOT EXISTS game_starters (
    game_id INTEGER NOT NULL REFERENCES games(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    position TEXT NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    sport TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (game_id, team_id, position)
);
CREATE INDEX IF NOT EXISTS idx_game_starters_player ON game_starters(player_id);

CREATE TABLE IF NOT EXISTS player_game_stats (
    player_id INTEGER NOT NULL REFERENCES players(id),
    game_id INTEGER NOT NULL REFERENCES games(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    sport TEXT NOT NULL,
    completions INTEGER,
    attempts INTEGER,
    passing_yards INTEGER,
    passing_tds INTEGER,
    passing_interceptions INTEGER,
    sacks_suffered INTEGER,
    sack_yards_lost INTEGER,
    carries INTEGER,
    rushing_yards INTEGER,
    rushing_tds INTEGER,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX IF NOT EXISTS idx_player_game_stats_game ON player_game_stats(game_id);

-- team_id NULL: the totals span several teams, or the source doesn't say.
CREATE TABLE IF NOT EXISTS player_season_stats (
    player_id INTEGER NOT NULL REFERENCES players(id),
    season INTEGER NOT NULL,
    season_type TEXT NOT NULL CHECK (season_type IN ('regular', 'postseason')),
    team_id INTEGER REFERENCES teams(id),
    games INTEGER,
    source TEXT NOT NULL,
    sport TEXT NOT NULL,
    completions INTEGER,
    attempts INTEGER,
    passing_yards INTEGER,
    passing_tds INTEGER,
    passing_interceptions INTEGER,
    sacks_suffered INTEGER,
    sack_yards_lost INTEGER,
    carries INTEGER,
    rushing_yards INTEGER,
    rushing_tds INTEGER,
    PRIMARY KEY (player_id, season, season_type)
);

-- Reserved for game-winning drives and similar per-game labels. A feat is a
-- definition applied to a game, not a count, so each row names the definition
-- version it was computed under; a career count is a count of rows. Nothing
-- writes here yet (epic #288, not v1).
CREATE TABLE IF NOT EXISTS player_game_feats (
    player_id INTEGER NOT NULL REFERENCES players(id),
    game_id INTEGER NOT NULL REFERENCES games(id),
    kind TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    sport TEXT NOT NULL,
    PRIMARY KEY (player_id, game_id, kind, definition_version)
);

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
