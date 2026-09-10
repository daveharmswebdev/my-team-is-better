CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    school TEXT NOT NULL,
    classification TEXT
);

CREATE TABLE IF NOT EXISTS team_season (
    team_id INTEGER NOT NULL REFERENCES teams(id),
    year INTEGER NOT NULL,
    conference TEXT,
    classification TEXT,
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
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_home ON games(home_team_id);
CREATE INDEX IF NOT EXISTS idx_games_away ON games(away_team_id);

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
    UNIQUE(year, method, team_id)
);
CREATE INDEX IF NOT EXISTS idx_ratings_year_method ON ratings(year, method);

CREATE TABLE IF NOT EXISTS ingestion_log (
    year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    game_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (year, season_type)
);
